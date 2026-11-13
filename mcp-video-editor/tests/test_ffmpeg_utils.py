"""Validação, sandbox de caminhos e execução do ffmpeg."""

import os

import pytest

import ffmpeg_utils as fu
from ffmpeg_utils import VideoEditorError


@pytest.mark.parametrize("value, expected", [
    (12, 12.0), (1.5, 1.5), ("7", 7.0), ("2.25", 2.25),
    ("01:05", 65.0), ("00:01:05.250", 65.25), ("1:00:00", 3600.0), (None, None), ("", None),
])
def test_parse_time(value, expected):
    assert fu.parse_time(value) == expected


@pytest.mark.parametrize("value", ["abc", "-3", -1, "1:2:3:4", True])
def test_parse_time_invalido(value):
    with pytest.raises(VideoEditorError):
        fu.parse_time(value)


def test_caminho_fora_do_workdir_e_barrado(workdir):
    for bad in ("../fora.mp4", "/etc/passwd.mp4", "sub/../../fora.mp4"):
        with pytest.raises(VideoEditorError, match="fora do diretório"):
            fu.resolve_output(bad, fu.VIDEO_EXTS)


def test_symlink_para_fora_e_barrado(workdir, tmp_path):
    alvo = tmp_path / "secreto.mp4"
    alvo.write_bytes(b"x")
    os.symlink(alvo, workdir / "link.mp4")
    with pytest.raises(VideoEditorError, match="fora do diretório"):
        fu.resolve_input("link.mp4", fu.VIDEO_EXTS)


def test_entrada_inexistente_e_extensao(workdir):
    with pytest.raises(VideoEditorError, match="não encontrado"):
        fu.resolve_input("nao_existe.mp4", fu.VIDEO_EXTS)
    with pytest.raises(VideoEditorError, match="Extensão"):
        fu.resolve_input("music.mp3", fu.VIDEO_EXTS)


def test_nao_sobrescreve_sem_overwrite(workdir):
    with pytest.raises(VideoEditorError, match="já existe"):
        fu.resolve_output("sample.mp4", fu.VIDEO_EXTS)
    assert fu.resolve_output("sample.mp4", fu.VIDEO_EXTS, overwrite=True) == workdir / "sample.mp4"


def test_saida_cria_subpasta(workdir):
    p = fu.resolve_output("saida/nova/x.mp4", fu.VIDEO_EXTS)
    assert p.parent.is_dir() and p.parent.is_relative_to(workdir)


def test_cor_e_posicao():
    assert fu.validate_color("ff0000") == "#ff0000"
    assert fu.validate_color("white") == "white"
    assert fu.validate_color("black@0.5") == "black@0.5"
    with pytest.raises(VideoEditorError):
        fu.validate_color("red;drop")
    assert fu.position_expr("bottom-right", 10, "W", "H", "w", "h") == ("W-w-10", "H-h-10")
    assert fu.position_expr("center", 0, "W", "H", "w", "h") == ("(W-w)/2", "(H-h)/2")
    with pytest.raises(VideoEditorError):
        fu.position_expr("em cima", 0, "W", "H", "w", "h")


def test_escape_filter_value():
    assert fu.escape_filter_value("a:b") == "a\\\\:b"  # nível 1: a\:b ; nível 2 escapa a barra
    assert fu.escape_filter_value("x,y[z];") == "x\\,y\\[z\\]\\;"


def test_ffmpeg_erro_traz_stderr_resumido(workdir, run):
    with pytest.raises(fu.FFmpegError, match="falhou") as exc:
        run(fu.run_ffmpeg(["-i", str(workdir / "nao_existe.mp4"), str(workdir / "o.mp4")]))
    assert "No such file" in str(exc.value)


def test_ffmpeg_timeout(workdir, run):
    with pytest.raises(fu.FFmpegError, match="tempo limite"):
        run(fu.run_ffmpeg(["-re", "-f", "lavfi", "-i", "testsrc=duration=30", "-f", "null", "-"],
                          timeout=0.5))


def test_check_ffmpeg():
    versions = fu.check_ffmpeg()
    assert versions["ffmpeg"] and versions["ffprobe"]


def test_atomic_output_nao_deixa_lixo(workdir, run):
    destino = workdir / "falha.mp4"

    async def falhar():
        async with fu.atomic_output(destino) as tmp:
            await fu.run_ffmpeg(["-i", "nao_existe.mp4", str(tmp)])

    with pytest.raises(fu.FFmpegError):
        run(falhar())
    assert not destino.exists()
    assert not [p for p in workdir.iterdir() if ".tmp-" in p.name]
