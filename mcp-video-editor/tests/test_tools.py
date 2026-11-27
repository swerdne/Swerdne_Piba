"""As 13 tools rodando de verdade sobre vídeos gerados pelo ffmpeg."""

import pytest

import ffmpeg_utils as fu
from ffmpeg_utils import VideoEditorError
from tools import audio, editing, effects, export, info


def probe(run, path):
    return run(info.get_video_info(path))


def test_get_video_info(workdir, run):
    r = probe(run, "sample.mp4")
    assert r["video"]["resolution"] == "320x240"
    assert r["video"]["fps"] == 25
    assert r["video"]["codec"] == "h264"
    assert r["audio"]["codec"] == "aac"
    assert 2.9 < r["duration_seconds"] < 3.2
    assert r["size_bytes"] > 0
    assert probe(run, "mute.mp4")["audio"] is None


def test_list_media_files(workdir, run):
    r = run(info.list_media_files())
    kinds = {f["path"]: f["kind"] for f in r["files"]}
    assert kinds["sample.mp4"] == "video" and kinds["music.mp3"] == "audio"
    assert kinds["logo.png"] == "image"


def test_trim_video(workdir, run):
    r = run(editing.trim_video("sample.mp4", start="0.5", end="00:00:02", output="out/trim.mp4"))
    assert r["output"] == "out/trim.mp4"
    assert 1.4 < r["duration_seconds"] < 1.6
    assert r["has_audio"]
    r = run(editing.trim_video("sample.mp4", start=1, duration="1", output="trim_fast.mp4", fast=True))
    assert r["mode"] == "copy"


def test_trim_valida_tempos(workdir, run):
    with pytest.raises(VideoEditorError, match="maior ou igual à duração"):
        run(editing.trim_video("sample.mp4", start="10", output="x.mp4"))
    with pytest.raises(VideoEditorError, match="maior que start"):
        run(editing.trim_video("sample.mp4", start="2", end="1", output="x.mp4"))
    with pytest.raises(VideoEditorError, match="já existe"):
        run(editing.trim_video("sample.mp4", start="0", end="1", output="mute.mp4"))


def test_concat_copia_quando_compativel(workdir, run):
    r = run(editing.concat_videos(["sample.mp4", "sample.mp4"], "concat_copy.mp4"))
    assert r["mode"] == "copy"
    assert 5.8 < r["duration_seconds"] < 6.3


def test_concat_recodifica_fontes_diferentes(workdir, run):
    r = run(editing.concat_videos(["sample.mp4", "mute.mp4"], "concat.mp4"))
    assert r["mode"] == "reencode"
    assert r["resolution"] == "320x240"  # resolução do primeiro
    assert r["has_audio"]  # o vídeo mudo ganhou silêncio
    assert 4.8 < r["duration_seconds"] < 5.3


def test_concat_exige_dois(workdir, run):
    with pytest.raises(VideoEditorError, match="pelo menos 2"):
        run(editing.concat_videos(["sample.mp4"], "c.mp4"))


@pytest.mark.parametrize("factor, dur", [(2.0, 1.5), (0.5, 6.0)])
def test_change_speed(workdir, run, factor, dur):
    r = run(editing.change_speed("sample.mp4", factor, f"speed_{factor}.mp4"))
    assert abs(r["duration_seconds"] - dur) < 0.25
    assert r["has_audio"]


def test_change_speed_fora_do_limite(workdir, run):
    with pytest.raises(VideoEditorError, match="entre 0.25 e 4.0"):
        run(editing.change_speed("sample.mp4", 10, "s.mp4"))


@pytest.mark.parametrize("w, h, mode, esperado", [
    (160, -1, "fit", "160x120"),
    (240, 240, "crop", "240x240"),
    (360, 640, "pad", "360x640"),
    (101, 101, "stretch", "100x100"),
])
def test_resize_video(workdir, run, w, h, mode, esperado):
    r = run(editing.resize_video("sample.mp4", f"resize_{mode}.mp4", width=w, height=h, mode=mode))
    assert r["resolution"] == esperado
    assert r["has_audio"]


def test_extract_audio(workdir, run):
    r = run(audio.extract_audio("sample.mp4", "audio.mp3"))
    assert "resolution" not in r and r["has_audio"]
    run(audio.extract_audio("sample.mp4", "audio.wav", format="wav"))
    with pytest.raises(VideoEditorError, match="Extensão"):
        run(audio.extract_audio("sample.mp4", "audio.wav", format="mp3"))
    with pytest.raises(VideoEditorError, match="não tem trilha de áudio"):
        run(audio.extract_audio("mute.mp4", "nada.mp3"))


@pytest.mark.parametrize("mix", [False, True])
def test_add_audio(workdir, run, mix):
    r = run(audio.add_audio("sample.mp4", "music.mp3", f"com_musica_{mix}.mp4", mix=mix, audio_volume=0.3))
    assert r["mode"] == ("mix" if mix else "replace")
    assert r["has_audio"]
    assert 2.9 < r["duration_seconds"] < 3.2  # duração do vídeo, não da música (5 s)


def test_add_audio_em_video_mudo(workdir, run):
    r = run(audio.add_audio("mute.mp4", "music.mp3", "mute_com_audio.mp4", mix=True))
    assert r["mode"] == "replace" and r["has_audio"]


def test_remove_audio(workdir, run):
    r = run(audio.remove_audio("sample.mp4", "sem_audio.mp4"))
    assert r["has_audio"] is False
    assert r["resolution"] == "320x240"


needs_drawtext = pytest.mark.skipif("drawtext" not in fu.available_filters(), reason="ffmpeg sem drawtext")
needs_subtitles = pytest.mark.skipif("subtitles" not in fu.available_filters(), reason="ffmpeg sem libass")


@needs_drawtext
def test_add_text_overlay(workdir, run):
    r = run(effects.add_text_overlay(
        "sample.mp4", "Olá: 'mundo', 100% [ok];\\nlinha 2", "texto.mp4",
        position="top", font_size=24, color="#ffcc00", start="0.5", end="2", box=True,
    ))
    assert r["resolution"] == "320x240" and r["has_audio"]


@needs_drawtext
def test_add_text_overlay_valida(workdir, run):
    with pytest.raises(VideoEditorError, match="Posição"):
        run(effects.add_text_overlay("sample.mp4", "x", "t.mp4", position="lá em cima"))
    with pytest.raises(VideoEditorError, match="Cor"):
        run(effects.add_text_overlay("sample.mp4", "x", "t.mp4", color="red:x=1"))


@needs_subtitles
def test_add_subtitles(workdir, run):
    r = run(effects.add_subtitles("sample.mp4", "leg, d'água.srt", "legendado.mp4", font_size=24,
                                  font_color="#ffff00"))
    assert r["resolution"] == "320x240"


def test_add_watermark(workdir, run):
    r = run(effects.add_watermark("sample.mp4", "logo.png", "marca.mp4", position="top-right", opacity=0.5))
    assert r["resolution"] == "320x240"
    assert 2.9 < r["duration_seconds"] < 3.2


def test_convert_format(workdir, run):
    r = run(export.convert_format("sample.mp4", "convertido.mkv", codec="h264", crf=30))
    assert r["codec"] == "h264" and r["compression_ratio"]
    r = run(export.convert_format("sample.mp4", "convertido.webm", crf=40))
    assert r["codec"] == "vp9"
    assert probe(run, "convertido.webm")["video"]["codec"] == "vp9"
    r = run(export.convert_format("sample.mp4", "copia.mov", codec="copy"))
    assert probe(run, "copia.mov")["video"]["codec"] == "h264"
    with pytest.raises(VideoEditorError, match="não é compatível"):
        run(export.convert_format("sample.mp4", "x.avi", codec="vp9"))


def test_extract_frames_sequencia_e_thumbnail(workdir, run):
    r = run(export.extract_frames("sample.mp4", "frames", fps=2))
    assert r["mode"] == "sequence" and 5 <= r["count"] <= 7
    assert r["files"][0] == "frames/frame_0001.jpg"
    with pytest.raises(VideoEditorError, match="Já existem"):
        run(export.extract_frames("sample.mp4", "frames", fps=2))
    r = run(export.extract_frames("sample.mp4", "frames", fps=1, overwrite=True, max_frames=2))
    assert r["count"] == 2  # sobras da extração anterior foram apagadas

    r = run(export.extract_frames("sample.mp4", "thumbs", timestamp="00:00:01.5", format="png",
                                  width=160, prefix="capa"))
    assert r == {"ok": True, "output_dir": "thumbs", "count": 1, "files": ["thumbs/capa.png"],
                 "truncated": False, "mode": "thumbnail"}
