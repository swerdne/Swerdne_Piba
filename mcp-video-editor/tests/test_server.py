"""O servidor de verdade, falando MCP com um cliente em memória."""

import json

import anyio
import pytest
from mcp.shared.memory import create_connected_server_and_client_session

import server

EXPECTED_TOOLS = {
    "get_video_info", "trim_video", "concat_videos", "extract_audio", "add_audio",
    "add_text_overlay", "add_subtitles", "change_speed", "resize_video", "add_watermark",
    "convert_format", "extract_frames", "remove_audio", "list_media_files",
}


def _with_client(fn):
    async def main():
        async with create_connected_server_and_client_session(server.mcp._mcp_server) as client:
            return await fn(client)
    return anyio.run(main)


def test_lista_todas_as_tools_com_descricao(workdir):
    async def go(client):
        return (await client.list_tools()).tools

    tools = {t.name: t for t in _with_client(go)}
    assert set(tools) == EXPECTED_TOOLS
    for t in tools.values():
        assert t.description and len(t.description) > 80, t.name
        # Context é injetado pelo servidor: não pode aparecer como argumento pro modelo.
        assert "ctx" not in t.inputSchema.get("properties", {}), t.name


def test_chama_tool_pelo_protocolo(workdir):
    async def go(client):
        return await client.call_tool("get_video_info", {"path": "sample.mp4"})

    result = _with_client(go)
    assert not result.isError
    data = json.loads(result.content[0].text)
    assert data["video"]["resolution"] == "320x240"


def test_erro_vira_resultado_de_erro_legivel(workdir):
    async def go(client):
        return await client.call_tool("trim_video", {"input": "../x.mp4", "start": "0", "output": "o.mp4"})

    result = _with_client(go)
    assert result.isError
    assert "fora do diretório de trabalho" in result.content[0].text


def test_startup_check(workdir, caplog):
    caplog.set_level("INFO", logger="video_editor")
    assert server.startup_check() is True
    assert "Diretório de trabalho" in caplog.text


@pytest.mark.parametrize("missing", ["/nao/existe/ffmpeg"])
def test_startup_check_sem_ffmpeg(workdir, monkeypatch, caplog, missing):
    monkeypatch.setenv("FFMPEG_BIN", missing)
    assert server.startup_check() is False
    assert "NÃO encontrado" in caplog.text
