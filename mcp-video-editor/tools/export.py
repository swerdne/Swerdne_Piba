"""Tools de saída: converter/comprimir e extrair frames ou thumbnail."""

from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations

from ffmpeg_utils import (
    VIDEO_EXTS, VideoEditorError, atomic_output, check_range, human_size, output_result, parse_time, probe,
    progress_reporter, rel, resolve_dir, resolve_input, resolve_output, run_ffmpeg,
)

from ._common import DEFAULT_CRF, DEFAULT_PRESET, audio_codec_args, check_crf, check_preset, faststart

# codec -> encoder do ffmpeg e contêineres (extensões de saída) que aceitam esse codec
VIDEO_CODECS: dict[str, dict[str, Any]] = {
    "h264": {"encoder": "libx264", "containers": {".mp4", ".mov", ".mkv", ".m4v", ".avi", ".flv", ".ts"}},
    "h265": {"encoder": "libx265", "containers": {".mp4", ".mov", ".mkv", ".m4v", ".ts"}},
    "vp9": {"encoder": "libvpx-vp9", "containers": {".webm", ".mkv", ".mp4"}},
    "av1": {"encoder": "libsvtav1", "containers": {".mp4", ".mkv", ".webm"}},
    "copy": {"encoder": None, "containers": set(VIDEO_EXTS)},
}
DEFAULT_CODEC_BY_EXT = {".webm": "vp9"}
MAX_FRAMES = 1000
FRAME_FORMATS = ("jpg", "png", "webp")


def _video_codec_args(codec: str, crf: int, preset: str) -> list[str]:
    if codec == "h264":
        return ["-c:v", "libx264", "-crf", str(crf), "-preset", preset, "-pix_fmt", "yuv420p"]
    if codec == "h265":
        return ["-c:v", "libx265", "-crf", str(crf), "-preset", preset, "-pix_fmt", "yuv420p", "-tag:v", "hvc1"]
    if codec == "vp9":
        return ["-c:v", "libvpx-vp9", "-crf", str(crf), "-b:v", "0", "-row-mt", "1",
                "-deadline", "good", "-cpu-used", "4", "-pix_fmt", "yuv420p"]
    if codec == "av1":
        return ["-c:v", "libsvtav1", "-crf", str(crf), "-preset", "8", "-pix_fmt", "yuv420p"]
    return ["-c:v", "copy"]


async def convert_format(
    input: str,
    output: str,
    codec: str | None = None,
    crf: int = DEFAULT_CRF,
    preset: str = DEFAULT_PRESET,
    audio_bitrate: str = "128k",
    overwrite: bool = False,
    ctx: Context = None,
) -> dict[str, Any]:
    """Converte um vídeo para outro formato/codec e/ou comprime (reduz o tamanho do arquivo).

    O contêiner é escolhido pela extensão de `output` (.mp4, .mov, .mkv, .webm, .avi...).
    Para COMPRIMIR mantendo o formato, use codec="h264" (ou "h265", ~40% menor, mas mais
    lento e menos compatível) e um crf maior (26–30). Para máxima compatibilidade
    (WhatsApp, Instagram, navegadores): .mp4 com h264.

    Args:
        input: Vídeo de origem (relativo ao diretório de trabalho).
        output: Arquivo de saída. Não pode já existir, a menos que overwrite=true.
        codec: h264, h265, vp9, av1 ou copy (só troca o contêiner, sem recodificar).
               Vazio = h264 (vp9 se a saída for .webm).
        crf: Qualidade constante, 0–51: menor = melhor qualidade e arquivo maior.
             Referência h264/h265: 18 (quase sem perda), 23 (padrão), 28 (bem comprimido).
             vp9/av1 usam escala parecida, porém valores ~10 mais altos (ex: 32).
        preset: Velocidade x compressão para h264/h265: ultrafast ... veryslow
                (padrão veryfast). Mais lento = arquivo menor na mesma qualidade.
        audio_bitrate: Bitrate do áudio recodificado (ex: "96k", "128k", "192k").
        overwrite: Permite substituir `output` se ele já existir.

    Returns:
        ok, output, size_human, input_size_human, compression_ratio, duration_seconds,
        resolution, fps, has_audio, codec.
    """
    src = resolve_input(input, VIDEO_EXTS, "vídeo de entrada")
    dst = resolve_output(output, VIDEO_EXTS, overwrite, [src])
    ext = dst.suffix.lower()
    codec = (codec or DEFAULT_CODEC_BY_EXT.get(ext, "h264")).lower()
    if codec not in VIDEO_CODECS:
        raise VideoEditorError(f"codec inválido: '{codec}'. Use um de: {', '.join(VIDEO_CODECS)}.")
    if ext not in VIDEO_CODECS[codec]["containers"]:
        raise VideoEditorError(
            f"O codec {codec} não é compatível com {ext}. Use uma destas extensões: "
            f"{', '.join(sorted(VIDEO_CODECS[codec]['containers']))}."
        )
    check_crf(crf)
    check_preset(preset)
    if not isinstance(audio_bitrate, str) or not audio_bitrate.rstrip("kK").isdigit():
        raise VideoEditorError(f"audio_bitrate inválido: '{audio_bitrate}'. Ex: \"128k\".")
    info = await probe(src)

    args = ["-i", str(src), "-map", "0:v:0", "-map", "0:a:0?", *_video_codec_args(codec, crf, preset)]
    if codec == "copy":
        args += ["-c:a", "copy"]
    else:
        a_args = ["-c:a", "libopus"] if ext == ".webm" else audio_codec_args(dst)[:2]
        args += [*a_args, "-b:a", audio_bitrate]
    args += faststart(dst)
    async with atomic_output(dst) as tmp:
        await run_ffmpeg([*args, str(tmp)], duration=info.duration, on_progress=progress_reporter(ctx))
    in_size = src.stat().st_size
    out_size = dst.stat().st_size
    return await output_result(
        dst, codec=codec, input_size_human=human_size(in_size),
        compression_ratio=round(in_size / out_size, 2) if out_size else None,
    )


async def extract_frames(
    input: str,
    output_dir: str,
    fps: float | None = 1.0,
    timestamp: str | float | None = None,
    format: str = "jpg",
    width: int | None = None,
    max_frames: int = 300,
    prefix: str = "frame",
    overwrite: bool = False,
    ctx: Context = None,
) -> dict[str, Any]:
    """Extrai imagens de um vídeo: uma sequência de frames OU uma única thumbnail.

    - Thumbnail/capa: passe `timestamp` (ex: "00:00:05") → gera 1 imagem daquele instante.
    - Sequência: passe `fps` (ex: 1 = um frame por segundo; 0.1 = um a cada 10 s) →
      gera prefix_0001.jpg, prefix_0002.jpg... em `output_dir`.

    Args:
        input: Vídeo de origem (relativo ao diretório de trabalho).
        output_dir: Pasta onde salvar as imagens (criada se não existir, dentro do
                    diretório de trabalho).
        fps: Frames por segundo a extrair (0.01 a 60). Ignorado se `timestamp` for dado.
        timestamp: Instante da thumbnail (segundos ou HH:MM:SS). Se informado, gera só 1 imagem.
        format: jpg (padrão), png (sem perda) ou webp.
        width: Largura das imagens em pixels (altura proporcional). Vazio = tamanho original.
        max_frames: Limite de imagens geradas (1 a 1000; padrão 300) para não lotar o disco.
        prefix: Prefixo do nome dos arquivos (letras, números, - e _).
        overwrite: Permite substituir imagens com o mesmo nome que já existam na pasta.

    Returns:
        ok, output_dir, count, files (até 50 primeiros caminhos), truncated.
    """
    fmt = (format or "jpg").lower().lstrip(".")
    if fmt == "jpeg":
        fmt = "jpg"
    if fmt not in FRAME_FORMATS:
        raise VideoEditorError(f"format inválido: '{format}'. Use jpg, png ou webp.")
    if not prefix or not all(c.isalnum() or c in "-_" for c in prefix) or len(prefix) > 50:
        raise VideoEditorError("prefix deve ter só letras, números, - e _ (até 50 caracteres).")
    max_frames = int(check_range(int(max_frames), 1, MAX_FRAMES, "max_frames"))
    if width is not None:
        width = int(check_range(int(width), 16, 7680, "width"))
    src = resolve_input(input, VIDEO_EXTS, "vídeo de entrada")
    info = await probe(src)
    if not info.has_video:
        raise VideoEditorError(f"'{input}' não tem trilha de vídeo.")
    ts = parse_time(timestamp, "timestamp")
    if ts is not None and info.duration is not None and ts >= info.duration:
        raise VideoEditorError(f"timestamp ({ts:.3f}s) passa da duração do vídeo ({info.duration:.3f}s).")
    if ts is None:
        if fps is None:
            raise VideoEditorError("Informe fps (sequência) ou timestamp (thumbnail).")
        fps = check_range(float(fps), 0.01, 60.0, "fps")

    out_dir = resolve_dir(output_dir)
    thumb = ts is not None
    name_glob = f"{prefix}.{fmt}" if thumb else f"{prefix}_[0-9][0-9][0-9][0-9].{fmt}"
    existing = sorted(out_dir.glob(name_glob))
    if existing and not overwrite:
        raise VideoEditorError(
            f"Já existem {len(existing)} imagem(ns) como '{rel(existing[0])}' em '{output_dir}'. "
            "Use overwrite=true, outro prefix ou outra pasta."
        )
    for f in existing:  # evita misturar frames novos com sobras de uma extração anterior
        f.unlink()

    filters = [] if thumb else [f"fps={fps}"]
    if width:
        filters.append(f"scale={width - width % 2}:-2")
    args = ["-ss", f"{ts:.3f}"] if thumb else []
    args += ["-i", str(src), "-map", "0:v:0"]
    if filters:
        args += ["-vf", ",".join(filters)]
    args += {"jpg": ["-q:v", "2"], "webp": ["-quality", "85"], "png": []}[fmt]
    if thumb:
        args += ["-frames:v", "1", "-update", "1", str(out_dir / f"{prefix}.{fmt}")]
        expected = None
    else:
        args += ["-frames:v", str(max_frames), "-start_number", "1", str(out_dir / f"{prefix}_%04d.{fmt}")]
        expected = min(info.duration, max_frames / fps) if info.duration else None
    await run_ffmpeg(args, duration=expected, on_progress=progress_reporter(ctx))

    files = sorted(out_dir.glob(name_glob))
    if not files:
        raise VideoEditorError("Nenhuma imagem foi gerada (o vídeo pode estar vazio ou o tempo fora do vídeo).")
    return {
        "ok": True,
        "output_dir": rel(out_dir),
        "count": len(files),
        "files": [rel(f) for f in files[:50]],
        "truncated": len(files) > 50,
        "mode": "thumbnail" if thumb else "sequence",
    }


def register(mcp: FastMCP) -> None:
    write = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)
    for fn in (convert_format, extract_frames):
        mcp.tool(annotations=write)(fn)
