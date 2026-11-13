"""Fixtures: mídias curtas geradas pelo próprio ffmpeg (sem arquivos binários no repositório)."""

import asyncio
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

# Permite rodar também a partir da raiz do repositório (fora desta pasta).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# Sem o SDK 1.x (FastMCP) ou sem ffmpeg — ex: rodando a suíte do app Flask —, ignora
# estes testes em vez de quebrar a coleta.
try:
    import mcp.server.fastmcp  # noqa: F401
    _motivo = None if shutil.which("ffmpeg") and shutil.which("ffprobe") else "ffmpeg/ffprobe não instalados"
except ImportError:
    _motivo = "SDK mcp<2 não instalado"
if _motivo:
    collect_ignore_glob = ["test_*.py"]
    print(f"[mcp-video-editor] testes ignorados: {_motivo}", file=sys.stderr)


def _ff(*args: str) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


@pytest.fixture(scope="session")
def media_cache(tmp_path_factory) -> Path:
    """Gera as mídias uma vez por sessão."""
    d = tmp_path_factory.mktemp("media")
    # 3 s, 320x240, 25 fps, com tom de 440 Hz
    _ff("-f", "lavfi", "-i", "testsrc=size=320x240:rate=25:duration=3",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(d / "sample.mp4"))
    # 2 s, 640x360, 30 fps, sem áudio (resolução/fps diferentes, pra testar concat recodificando)
    _ff("-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(d / "mute.mp4"))
    # 5 s de áudio
    _ff("-f", "lavfi", "-i", "sine=frequency=880:duration=5", "-c:a", "libmp3lame", str(d / "music.mp3"))
    # logo 100x50 com transparência
    _ff("-f", "lavfi", "-i", "color=c=red@0.8:size=100x50,format=rgba", "-frames:v", "1", str(d / "logo.png"))
    # legenda com vírgula, espaço e apóstrofo no nome (testa o escape do filtro)
    (d / "leg, d'água.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,500\nOlá, mundo!\n\n2\n00:00:01,500 --> 00:00:03,000\nSegunda: linha\n",
        encoding="utf-8",
    )
    return d


@pytest.fixture
def workdir(tmp_path, media_cache, monkeypatch) -> Path:
    """VIDEO_WORKDIR isolado por teste, já com as mídias de exemplo."""
    wd = tmp_path / "work"
    wd.mkdir()
    for f in media_cache.iterdir():
        shutil.copy(f, wd / f.name)
    monkeypatch.setenv("VIDEO_WORKDIR", str(wd))
    monkeypatch.setenv("VIDEO_FFMPEG_TIMEOUT", "120")
    return wd


@pytest.fixture
def run():
    """Roda uma coroutine (as tools são async) sem precisar de pytest-asyncio."""
    return asyncio.run
