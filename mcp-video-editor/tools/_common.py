"""Argumentos de codificação compartilhados pelas tools que geram vídeo."""

from pathlib import Path

from ffmpeg_utils import VideoEditorError

DEFAULT_CRF = 20
DEFAULT_PRESET = "veryfast"
PRESETS = ("ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow")


def video_encode_args(output: Path, crf: int = DEFAULT_CRF, preset: str = DEFAULT_PRESET) -> list[str]:
    """Codecs padrão conforme o contêiner de saída (H.264/AAC; VP9/Opus em .webm)."""
    ext = output.suffix.lower()
    if ext == ".webm":
        return ["-c:v", "libvpx-vp9", "-crf", str(crf + 12), "-b:v", "0", "-row-mt", "1",
                "-deadline", "good", "-cpu-used", "4", "-pix_fmt", "yuv420p", "-c:a", "libopus", "-b:a", "128k"]
    args = ["-c:v", "libx264", "-crf", str(crf), "-preset", preset, "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k"]
    if ext in (".mp4", ".mov", ".m4v"):
        args += ["-movflags", "+faststart"]
    return args


def audio_codec_args(output: Path) -> list[str]:
    """Só a parte de áudio (usado quando o vídeo é copiado sem recodificar)."""
    ext = output.suffix.lower()
    if ext == ".webm":
        return ["-c:a", "libopus", "-b:a", "128k"]
    if ext == ".avi":
        return ["-c:a", "libmp3lame", "-b:a", "192k"]
    return ["-c:a", "aac", "-b:a", "192k"]


def faststart(output: Path) -> list[str]:
    return ["-movflags", "+faststart"] if output.suffix.lower() in (".mp4", ".mov", ".m4v") else []


def check_crf(crf: int) -> int:
    if not isinstance(crf, int) or isinstance(crf, bool) or not 0 <= crf <= 51:
        raise VideoEditorError(f"crf deve ser um inteiro entre 0 e 51 (recebido: {crf!r}).")
    return crf


def check_preset(preset: str) -> str:
    if preset not in PRESETS:
        raise VideoEditorError(f"preset inválido: '{preset}'. Use um de: {', '.join(PRESETS)}.")
    return preset
