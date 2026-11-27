"""Tools de edição na linha do tempo e no quadro: cortar, juntar, velocidade, tamanho."""

import tempfile
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations

from ffmpeg_utils import (
    VIDEO_EXTS, VideoEditorError, atomic_output, check_range, output_result, parse_time,
    probe, progress_reporter, rel, resolve_input, resolve_output, run_ffmpeg,
)

from ._common import DEFAULT_CRF, faststart, video_encode_args

MAX_CONCAT_INPUTS = 100


async def trim_video(
    input: str,
    start: str,
    output: str,
    end: str | None = None,
    duration: str | None = None,
    fast: bool = False,
    overwrite: bool = False,
    ctx: Context = None,
) -> dict[str, Any]:
    """Corta um trecho de um vídeo (do tempo `start` até `end`) e salva num novo arquivo.

    Informe `end` OU `duration` (se nenhum dos dois, vai de `start` até o fim).
    Tempos aceitam segundos ("12.5") ou "HH:MM:SS.ms" / "MM:SS" (ex: "00:01:05.250").

    Args:
        input: Vídeo de origem (relativo ao diretório de trabalho).
        start: Início do trecho. Deve ser menor que a duração do vídeo.
        output: Arquivo de saída (.mp4, .mov, .mkv, .webm...). Não pode já existir,
                a menos que overwrite=true.
        end: Fim do trecho (maior que start). Se passar da duração, corta até o fim.
        duration: Alternativa a `end`: duração do trecho em segundos ou HH:MM:SS.
        fast: true = copia os streams sem recodificar (instantâneo, sem perda, mas o
              corte só fica exato em keyframes — pode começar alguns frames antes).
              false (padrão) = recodifica e corta no frame exato.
        overwrite: Permite substituir `output` se ele já existir.

    Returns:
        ok, output, duration_seconds, resolution, fps, has_audio, size_human.
    """
    src = resolve_input(input, VIDEO_EXTS, "vídeo de entrada")
    dst = resolve_output(output, VIDEO_EXTS, overwrite, [src])
    info = await probe(src)
    total = info.duration
    t0 = parse_time(start, "start") or 0.0
    t1 = parse_time(end, "end")
    dur = parse_time(duration, "duration")
    if t1 is not None and dur is not None:
        raise VideoEditorError("Informe `end` ou `duration`, não os dois.")
    if total is not None and t0 >= total:
        raise VideoEditorError(f"start ({t0:.3f}s) é maior ou igual à duração do vídeo ({total:.3f}s).")
    if t1 is not None:
        if t1 <= t0:
            raise VideoEditorError(f"end ({t1:.3f}s) precisa ser maior que start ({t0:.3f}s).")
        dur = t1 - t0
    if dur is not None and dur <= 0:
        raise VideoEditorError("duration precisa ser maior que zero.")
    if total is not None:
        dur = min(dur, total - t0) if dur is not None else total - t0

    args = ["-ss", f"{t0:.3f}", "-i", str(src)]
    if dur is not None:
        args += ["-t", f"{dur:.3f}"]
    args += ["-map", "0:v:0", "-map", "0:a:0?"]
    if fast:
        args += ["-c", "copy", "-avoid_negative_ts", "make_zero", *faststart(dst)]
    else:
        args += video_encode_args(dst)
    async with atomic_output(dst) as tmp:
        await run_ffmpeg([*args, str(tmp)], duration=dur, on_progress=progress_reporter(ctx))
    return await output_result(dst, trimmed_from=round(t0, 3), mode="copy" if fast else "reencode")


async def concat_videos(
    inputs: list[str],
    output: str,
    reencode: bool | None = None,
    overwrite: bool = False,
    ctx: Context = None,
) -> dict[str, Any]:
    """Junta dois ou mais vídeos em sequência, na ordem da lista, num único arquivo.

    Modo automático (reencode=null): se todos os vídeos têm o mesmo codec, resolução,
    fps e mesmo tipo de áudio, junta sem recodificar (rápido e sem perda). Caso
    contrário, recodifica tudo para a resolução e fps do PRIMEIRO vídeo (os outros são
    redimensionados com barras pretas, sem distorcer); vídeos sem áudio ganham silêncio.

    Args:
        inputs: Lista de vídeos (2 a 100), relativos ao diretório de trabalho.
        output: Arquivo de saída. Não pode já existir, a menos que overwrite=true.
        reencode: null = automático; true = sempre recodifica (mais seguro com fontes
                  diferentes); false = força cópia direta (falha se forem incompatíveis).
        overwrite: Permite substituir `output` se ele já existir.

    Returns:
        ok, output, duration_seconds, resolution, fps, has_audio, mode (copy/reencode).
    """
    if not isinstance(inputs, list) or len(inputs) < 2:
        raise VideoEditorError("Informe pelo menos 2 vídeos em `inputs`.")
    if len(inputs) > MAX_CONCAT_INPUTS:
        raise VideoEditorError(f"No máximo {MAX_CONCAT_INPUTS} vídeos por vez.")
    srcs = [resolve_input(p, VIDEO_EXTS, f"vídeo de entrada #{i + 1}") for i, p in enumerate(inputs)]
    dst = resolve_output(output, VIDEO_EXTS, overwrite, srcs)
    infos = [await probe(s) for s in srcs]
    for s, inf in zip(srcs, infos, strict=True):
        if not inf.has_video:
            raise VideoEditorError(f"'{rel(s)}' não tem trilha de vídeo.")
    total = sum(i.duration or 0 for i in infos) or None

    def signature(i):
        v, a = i.video, i.audio
        return (v.get("codec_name"), i.width, i.height, i.fps, v.get("pix_fmt"),
                (a or {}).get("codec_name"), (a or {}).get("sample_rate"), (a or {}).get("channels"))

    compatible = len({signature(i) for i in infos}) == 1
    if reencode is None:
        reencode = not compatible
    if not reencode and not compatible:
        raise VideoEditorError(
            "Os vídeos têm codec/resolução/fps/áudio diferentes e não dá pra juntar sem "
            "recodificar. Use reencode=true (ou deixe null)."
        )

    report = progress_reporter(ctx)
    if not reencode:
        with tempfile.TemporaryDirectory() as tmpdir:
            listfile = Path(tmpdir) / "list.txt"
            # Formato do concat demuxer: aspas simples, com ' escapado como '\''.
            listfile.write_text(
                "".join("file '" + str(s).replace("'", "'\\''") + "'\n" for s in srcs), encoding="utf-8"
            )
            async with atomic_output(dst) as tmp:
                await run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(listfile), "-map", "0",
                                  "-c", "copy", *faststart(dst), str(tmp)],
                                 duration=total, on_progress=report)
        return await output_result(dst, mode="copy", inputs=len(srcs))

    first = infos[0]
    w, h = first.width, first.height
    w, h = w - w % 2, h - h % 2  # libx264/yuv420p exigem dimensões pares
    fps = first.fps or 30
    any_audio = any(i.has_audio for i in infos)
    args: list[str] = []
    for s in srcs:
        args += ["-i", str(s)]
    parts, labels = [], []
    for idx, inf in enumerate(infos):
        parts.append(
            f"[{idx}:v:0]scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps={fps},format=yuv420p[v{idx}]"
        )
        labels.append(f"[v{idx}]")
        if any_audio:
            if inf.has_audio:
                parts.append(f"[{idx}:a:0]aformat=sample_rates=48000:channel_layouts=stereo[a{idx}]")
            else:
                parts.append(f"anullsrc=r=48000:cl=stereo,atrim=duration={inf.duration or 0:.3f}[a{idx}]")
            labels.append(f"[a{idx}]")
    n = len(srcs)
    out_labels = "[outv][outa]" if any_audio else "[outv]"
    parts.append(f"{''.join(labels)}concat=n={n}:v=1:a={1 if any_audio else 0}{out_labels}")
    args += ["-filter_complex", ";".join(parts), "-map", "[outv]"]
    if any_audio:
        args += ["-map", "[outa]"]
    args += video_encode_args(dst)
    async with atomic_output(dst) as tmp:
        await run_ffmpeg([*args, str(tmp)], duration=total, on_progress=report)
    return await output_result(dst, mode="reencode", inputs=n)


def _atempo_chain(factor: float) -> str:
    """atempo só aceita 0.5–2.0 por instância em builds antigas; encadeia quando precisa."""
    steps = []
    remaining = factor
    while remaining > 2.0:
        steps.append(2.0)
        remaining /= 2.0
    while remaining < 0.5:
        steps.append(0.5)
        remaining /= 0.5
    steps.append(remaining)
    return ",".join(f"atempo={s:.6f}" for s in steps)


async def change_speed(
    input: str,
    factor: float,
    output: str,
    overwrite: bool = False,
    ctx: Context = None,
) -> dict[str, Any]:
    """Acelera ou desacelera um vídeo (imagem E áudio juntos, mantendo a sincronia).

    O áudio muda de velocidade sem mudar o tom da voz (filtro atempo).

    Args:
        input: Vídeo de origem (relativo ao diretório de trabalho).
        factor: Multiplicador de velocidade, de 0.25 a 4.0. 2.0 = duas vezes mais rápido
                (duração cai pela metade); 0.5 = câmera lenta (duração dobra).
        output: Arquivo de saída. Não pode já existir, a menos que overwrite=true.
        overwrite: Permite substituir `output` se ele já existir.

    Returns:
        ok, output, duration_seconds, resolution, fps, has_audio, factor.
    """
    try:
        factor = float(factor)
    except (TypeError, ValueError):
        raise VideoEditorError(f"factor inválido: {factor!r}.") from None
    check_range(factor, 0.25, 4.0, "factor")
    if factor == 1.0:
        raise VideoEditorError("factor = 1.0 não muda nada. Use > 1 para acelerar ou < 1 para desacelerar.")
    src = resolve_input(input, VIDEO_EXTS, "vídeo de entrada")
    dst = resolve_output(output, VIDEO_EXTS, overwrite, [src])
    info = await probe(src)
    args = ["-i", str(src), "-filter:v", f"setpts=PTS/{factor:.6f}", "-map", "0:v:0"]
    if info.has_audio:
        args += ["-filter:a", _atempo_chain(factor), "-map", "0:a:0"]
    args += video_encode_args(dst)
    out_dur = info.duration / factor if info.duration else None
    async with atomic_output(dst) as tmp:
        await run_ffmpeg([*args, str(tmp)], duration=out_dur, on_progress=progress_reporter(ctx))
    return await output_result(dst, factor=factor)


RESIZE_MODES = ("fit", "crop", "stretch", "pad")

# Codecs de áudio que cada contêiner aceita sem recodificar.
_AUDIO_COPY_OK = {
    ".mp4": {"aac", "mp3", "ac3", "eac3", "alac", "opus"},
    ".m4v": {"aac", "mp3", "ac3"},
    ".mov": {"aac", "mp3", "alac", "pcm_s16le", "ac3"},
    ".mkv": {"aac", "mp3", "ac3", "eac3", "opus", "vorbis", "flac", "pcm_s16le", "alac"},
    ".webm": {"opus", "vorbis"},
}


def _can_copy_audio(info, dst: Path) -> bool:
    codec = (info.audio or {}).get("codec_name")
    return codec in _AUDIO_COPY_OK.get(dst.suffix.lower(), set())


async def resize_video(
    input: str,
    output: str,
    width: int = -1,
    height: int = -1,
    mode: str = "fit",
    overwrite: bool = False,
    ctx: Context = None,
) -> dict[str, Any]:
    """Redimensiona um vídeo, com opção de cortar (crop) ou pôr barras (pad) para mudar o formato.

    Exemplos: deixar 1280x720 → width=1280, height=-1 (altura proporcional);
    vertical 9:16 para Reels/Shorts a partir de um vídeo 16:9 → width=1080, height=1920,
    mode="crop" (corta as laterais, sem barras) ou mode="pad" (barras pretas).

    Args:
        input: Vídeo de origem (relativo ao diretório de trabalho).
        output: Arquivo de saída. Não pode já existir, a menos que overwrite=true.
        width: Largura em pixels (16–7680). -1 = proporcional à altura.
        height: Altura em pixels (16–4320). -1 = proporcional à largura.
                Pelo menos um dos dois deve ser informado. Valores ímpares são
                arredondados para par (exigência do H.264).
        mode: Só importa quando width E height são informados:
              "fit"/"pad" = cabe inteiro no quadro, completando com barras pretas;
              "crop" = preenche o quadro todo e corta o que sobrar (centralizado);
              "stretch" = estica para o tamanho exato (pode distorcer).
        overwrite: Permite substituir `output` se ele já existir.

    Returns:
        ok, output, resolution, duration_seconds, fps, has_audio.
    """
    mode = (mode or "fit").lower()
    if mode not in RESIZE_MODES:
        raise VideoEditorError(f"mode inválido: '{mode}'. Use um de: {', '.join(RESIZE_MODES)}.")
    for name, val, hi in (("width", width, 7680), ("height", height, 4320)):
        if not isinstance(val, int) or isinstance(val, bool):
            raise VideoEditorError(f"{name} deve ser inteiro.")
        if val != -1 and not 16 <= val <= hi:
            raise VideoEditorError(f"{name} deve ser -1 ou estar entre 16 e {hi} (recebido: {val}).")
    if width == -1 and height == -1:
        raise VideoEditorError("Informe width, height ou os dois.")
    src = resolve_input(input, VIDEO_EXTS, "vídeo de entrada")
    dst = resolve_output(output, VIDEO_EXTS, overwrite, [src])
    info = await probe(src)
    if not info.has_video:
        raise VideoEditorError(f"'{input}' não tem trilha de vídeo.")

    even = lambda v: v - v % 2  # noqa: E731
    if width == -1 or height == -1:
        vf = f"scale={even(width) if width != -1 else -2}:{even(height) if height != -1 else -2}"
    else:
        w, h = even(width), even(height)
        if mode == "stretch":
            vf = f"scale={w}:{h}"
        elif mode == "crop":
            vf = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"
        else:
            vf = f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black"
    vf += ",setsar=1"
    args = ["-i", str(src), "-vf", vf, "-map", "0:v:0", "-map", "0:a:0?",
            *video_encode_args(dst, DEFAULT_CRF)]
    if _can_copy_audio(info, dst):
        # O áudio não muda: copia em vez de recodificar (mais rápido, sem perda).
        idx = args.index("-c:a")
        args[idx:idx + 4] = ["-c:a", "copy"]
    async with atomic_output(dst) as tmp:
        await run_ffmpeg([*args, str(tmp)], duration=info.duration, on_progress=progress_reporter(ctx))
    return await output_result(dst, mode=mode)


def register(mcp: FastMCP) -> None:
    write = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)
    for fn in (trim_video, concat_videos, change_speed, resize_video):
        mcp.tool(annotations=write)(fn)

