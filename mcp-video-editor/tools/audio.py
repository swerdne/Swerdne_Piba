"""Tools de áudio: extrair, trocar/mixar trilha e remover áudio."""

from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations

from ffmpeg_utils import (
    MEDIA_EXTS, VIDEO_EXTS, VideoEditorError, atomic_output, check_range,
    output_result, parse_time, probe, progress_reporter, resolve_input, resolve_output, run_ffmpeg,
)

from ._common import audio_codec_args, faststart

# formato -> (extensões aceitas na saída, argumentos de codec)
AUDIO_FORMATS: dict[str, tuple[tuple[str, ...], list[str]]] = {
    "mp3": ((".mp3",), ["-c:a", "libmp3lame", "-q:a", "2"]),
    "aac": ((".m4a", ".aac"), ["-c:a", "aac", "-b:a", "192k"]),
    "m4a": ((".m4a",), ["-c:a", "aac", "-b:a", "192k"]),
    "wav": ((".wav",), ["-c:a", "pcm_s16le"]),
    "flac": ((".flac",), ["-c:a", "flac"]),
    "ogg": ((".ogg",), ["-c:a", "libvorbis", "-q:a", "5"]),
    "opus": ((".opus", ".ogg"), ["-c:a", "libopus", "-b:a", "128k"]),
}


async def extract_audio(
    input: str,
    output: str,
    format: str = "mp3",
    overwrite: bool = False,
    ctx: Context = None,
) -> dict[str, Any]:
    """Extrai a trilha de áudio de um vídeo para um arquivo de áudio separado.

    Útil para transcrição, podcast, reaproveitar a música ou editar o som à parte.

    Args:
        input: Vídeo de origem (relativo ao diretório de trabalho). Precisa ter áudio.
        output: Arquivo de áudio de saída; a extensão deve combinar com `format`
                (mp3 → .mp3, aac → .m4a/.aac, wav → .wav, flac → .flac, ogg → .ogg,
                opus → .opus). Não pode já existir, a menos que overwrite=true.
        format: mp3 (padrão), aac, m4a, wav, flac, ogg ou opus.
        overwrite: Permite substituir `output` se ele já existir.

    Returns:
        ok, output, duration_seconds, size_human, format.
    """
    fmt = (format or "mp3").lower().lstrip(".")
    if fmt not in AUDIO_FORMATS:
        raise VideoEditorError(f"format inválido: '{format}'. Use um de: {', '.join(AUDIO_FORMATS)}.")
    exts, codec_args = AUDIO_FORMATS[fmt]
    src = resolve_input(input, MEDIA_EXTS, "vídeo de entrada")
    dst = resolve_output(output, exts, overwrite, [src], what=f"saída ({fmt})")
    info = await probe(src)
    if not info.has_audio:
        raise VideoEditorError(f"'{input}' não tem trilha de áudio para extrair.")
    async with atomic_output(dst) as tmp:
        await run_ffmpeg(["-i", str(src), "-map", "0:a:0", "-vn", *codec_args, str(tmp)],
                         duration=info.duration, on_progress=progress_reporter(ctx))
    return await output_result(dst, format=fmt)


async def add_audio(
    video: str,
    audio: str,
    output: str,
    mix: bool = False,
    audio_volume: float = 1.0,
    original_volume: float = 1.0,
    audio_start: str | float = 0,
    loop_audio: bool = False,
    overwrite: bool = False,
    ctx: Context = None,
) -> dict[str, Any]:
    """Coloca uma trilha de áudio (música, narração) num vídeo: substitui ou mistura com o som original.

    A imagem não é recodificada (rápido, sem perda). O resultado tem sempre a duração do
    vídeo: se o áudio for mais longo, é cortado; se for mais curto, completa com silêncio
    (ou repete, com loop_audio=true).

    Args:
        video: Vídeo de origem (relativo ao diretório de trabalho).
        audio: Arquivo de áudio (.mp3, .wav, .m4a...) ou um vídeo do qual usar o áudio.
        output: Arquivo de saída. Não pode já existir, a menos que overwrite=true.
        mix: false (padrão) = SUBSTITUI o áudio original pela nova trilha.
             true = MISTURA a nova trilha com o áudio original (ex: música de fundo
             sob a voz). Se o vídeo não tiver áudio, equivale a substituir.
        audio_volume: Volume da nova trilha (0.0 a 4.0; 1.0 = sem mudança; 0.2 = música
                      de fundo baixinha).
        original_volume: Volume do áudio original quando mix=true (0.0 a 4.0).
        audio_start: Em que ponto do vídeo a nova trilha começa a tocar (segundos ou
                     HH:MM:SS). Padrão 0.
        loop_audio: Repete a nova trilha até cobrir o vídeo inteiro.
        overwrite: Permite substituir `output` se ele já existir.

    Returns:
        ok, output, duration_seconds, has_audio, mode (replace/mix).
    """
    vol = check_range(float(audio_volume), 0.0, 4.0, "audio_volume")
    orig_vol = check_range(float(original_volume), 0.0, 4.0, "original_volume")
    delay = parse_time(audio_start, "audio_start") or 0.0
    v_src = resolve_input(video, VIDEO_EXTS, "vídeo")
    a_src = resolve_input(audio, MEDIA_EXTS, "áudio")
    dst = resolve_output(output, VIDEO_EXTS, overwrite, [v_src, a_src])
    v_info, a_info = await probe(v_src), await probe(a_src)
    if not v_info.has_video:
        raise VideoEditorError(f"'{video}' não tem trilha de vídeo.")
    if not a_info.has_audio:
        raise VideoEditorError(f"'{audio}' não tem trilha de áudio.")
    if v_info.duration and delay >= v_info.duration:
        raise VideoEditorError("audio_start é maior que a duração do vídeo.")

    args = ["-i", str(v_src)]
    if loop_audio:
        args += ["-stream_loop", "-1"]
    args += ["-i", str(a_src)]
    new = f"[1:a:0]volume={vol:.3f}"
    if delay > 0:
        ms = int(delay * 1000)
        new += f",adelay={ms}|{ms}"
    use_mix = mix and v_info.has_audio
    if use_mix:
        graph = (f"{new}[na];[0:a:0]volume={orig_vol:.3f}[oa];"
                 "[oa][na]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,apad[aout]")
    else:
        graph = f"{new},apad[aout]"
    args += ["-filter_complex", graph, "-map", "0:v:0", "-map", "[aout]", "-c:v", "copy",
             *audio_codec_args(dst), *faststart(dst)]
    if v_info.duration:
        args += ["-t", f"{v_info.duration:.3f}"]
    async with atomic_output(dst) as tmp:
        await run_ffmpeg([*args, str(tmp)], duration=v_info.duration, on_progress=progress_reporter(ctx))
    return await output_result(dst, mode="mix" if use_mix else "replace")


async def remove_audio(
    input: str,
    output: str,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Remove todo o áudio de um vídeo (deixa mudo). Não recodifica a imagem: é rápido e sem perda.

    Args:
        input: Vídeo de origem (relativo ao diretório de trabalho).
        output: Arquivo de saída (de preferência a mesma extensão da entrada).
                Não pode já existir, a menos que overwrite=true.
        overwrite: Permite substituir `output` se ele já existir.

    Returns:
        ok, output, duration_seconds, resolution, has_audio (sempre false).
    """
    src = resolve_input(input, VIDEO_EXTS, "vídeo de entrada")
    dst = resolve_output(output, VIDEO_EXTS, overwrite, [src])
    info = await probe(src)
    if not info.has_video:
        raise VideoEditorError(f"'{input}' não tem trilha de vídeo.")
    async with atomic_output(dst) as tmp:
        await run_ffmpeg(["-i", str(src), "-map", "0:v:0", "-c:v", "copy", "-an", "-sn", "-dn",
                          *faststart(dst), str(tmp)], duration=info.duration)
    return await output_result(dst, had_audio=info.has_audio)


def register(mcp: FastMCP) -> None:
    write = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)
    for fn in (extract_audio, add_audio, remove_audio):
        mcp.tool(annotations=write)(fn)

