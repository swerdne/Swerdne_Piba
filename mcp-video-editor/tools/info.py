"""Tools de leitura: informações de mídia e listagem do diretório de trabalho."""

from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from ffmpeg_utils import (
    AUDIO_EXTS, IMAGE_EXTS, MEDIA_EXTS, VIDEO_EXTS, SUBTITLE_EXTS, VideoEditorError, get_workdir, human_size,
    probe, rel, resolve_input, _resolve_in_workdir,
)

MAX_LISTED = 500


async def get_video_info(path: str) -> dict[str, Any]:
    """Lê os metadados de um arquivo de vídeo ou áudio usando ffprobe (não altera nada).

    Use ANTES de editar, para saber a duração (e escolher tempos válidos para cortes,
    textos e legendas), a resolução (para redimensionar/posicionar marcas d'água), o fps,
    os codecs e se o arquivo tem trilha de áudio.

    Args:
        path: Caminho do arquivo, relativo ao diretório de trabalho (VIDEO_WORKDIR).
              Ex: "entrada/aula.mp4". Aceita vídeo (.mp4, .mov, .mkv, .webm, .avi...)
              e áudio (.mp3, .wav, .m4a...).

    Returns:
        Dicionário com: path, container, duration_seconds, size_bytes, size_human,
        bit_rate_kbps, video {codec, width, height, resolution, fps, pix_fmt, rotation}
        (None se não houver vídeo) e audio {codec, sample_rate, channels} (None se não
        houver áudio).
    """
    p = resolve_input(path, MEDIA_EXTS, "mídia")
    return (await probe(p)).summary()


async def list_media_files(subdir: str = ".") -> dict[str, Any]:
    """Lista os arquivos de mídia disponíveis no diretório de trabalho (recursivamente).

    Use quando não souber o nome exato do arquivo ou para conferir o que já foi gerado.
    Todas as outras tools só enxergam arquivos dentro deste diretório.

    Args:
        subdir: Subpasta a listar, relativa ao diretório de trabalho (padrão: raiz).

    Returns:
        workdir (caminho absoluto) e files: lista de {path, size_human, kind}, onde kind
        é video/audio/image/subtitle. Limitado a 500 itens.
    """
    base = _resolve_in_workdir(subdir, "pasta")
    if not base.is_dir():
        raise VideoEditorError(f"Pasta não encontrada: '{subdir}'.")
    kinds = {**{e: "video" for e in VIDEO_EXTS}, **{e: "audio" for e in AUDIO_EXTS},
             **{e: "image" for e in IMAGE_EXTS}, **{e: "subtitle" for e in SUBTITLE_EXTS}}
    files = []
    for f in sorted(base.rglob("*")):
        if len(files) >= MAX_LISTED:
            break
        if f.is_file() and not f.name.startswith(".") and f.suffix.lower() in kinds:
            files.append({"path": rel(f), "size_human": human_size(f.stat().st_size),
                          "kind": kinds[f.suffix.lower()]})
    return {"workdir": str(get_workdir()), "files": files, "truncated": len(files) >= MAX_LISTED}


def register(mcp: FastMCP) -> None:
    ro = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False)
    mcp.tool(annotations=ro)(get_video_info)
    mcp.tool(annotations=ro)(list_media_files)
