"""Servidor MCP de edição de vídeo (FFmpeg) — transporte stdio.

Uso:
    uv run server.py            # ou: python server.py
    VIDEO_WORKDIR=~/Videos uv run server.py

stdout é reservado ao protocolo MCP: todo log vai para stderr.
"""

import logging
import os
import sys
from pathlib import Path

# Garante que `ffmpeg_utils` e `tools` sejam importáveis mesmo se o servidor for
# iniciado de outra pasta (ex: pelo Claude Desktop, com caminho absoluto).
sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcp.server.fastmcp import FastMCP  # noqa: E402

from ffmpeg_utils import check_ffmpeg, get_timeout, get_workdir  # noqa: E402
from tools import register_all  # noqa: E402

logging.basicConfig(
    stream=sys.stderr,
    level=os.environ.get("VIDEO_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("video_editor")

INSTRUCTIONS = """\
Editor de vídeo baseado em FFmpeg. Todos os caminhos são relativos ao diretório de
trabalho do servidor (VIDEO_WORKDIR); use list_media_files para ver o que existe e
get_video_info antes de editar (duração, resolução, se tem áudio). Cada tool gera um
NOVO arquivo em `output` e nunca sobrescreve um existente, a menos que overwrite=true.
Para várias edições em sequência, use a saída de uma como entrada da próxima.
Tempos aceitam segundos (12.5) ou HH:MM:SS(.ms).
"""

mcp = FastMCP("video-editor", instructions=INSTRUCTIONS)
register_all(mcp)


def startup_check() -> bool:
    """Loga o ambiente e avisa (sem derrubar o servidor) se o FFmpeg não estiver instalado."""
    versions = check_ffmpeg()
    ok = all(versions.values())
    for name, version in versions.items():
        if version:
            logger.info("%s encontrado: %s", name, version)
        else:
            logger.error(
                "%s NÃO encontrado. Instale o FFmpeg (apt install ffmpeg / brew install ffmpeg / "
                "winget install ffmpeg) ou defina %s_BIN. As tools vão falhar até isso ser resolvido.",
                name, name.upper(),
            )
    logger.info("Diretório de trabalho: %s (timeout por comando: %.0fs)", get_workdir(), get_timeout())
    return ok


def main() -> None:
    startup_check()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
