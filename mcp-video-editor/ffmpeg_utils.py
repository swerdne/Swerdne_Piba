"""Infraestrutura comum do servidor: caminhos seguros, validação e execução do FFmpeg.

Tudo que toca o sistema de arquivos ou chama um processo externo passa por aqui,
pra que as regras de segurança (sandbox no VIDEO_WORKDIR, nunca sobrescrever sem
``overwrite=True``, nunca ``shell=True``, timeout) fiquem num lugar só.

Variáveis de ambiente:
    VIDEO_WORKDIR         Diretório de trabalho; nenhum caminho pode sair dele.
                          Padrão: ``./workspace`` (criado se não existir).
    VIDEO_FFMPEG_TIMEOUT  Timeout, em segundos, de cada comando do ffmpeg (padrão 900).
    VIDEO_MAX_JOBS        Quantos ffmpeg podem rodar ao mesmo tempo (padrão 2).
    FFMPEG_BIN / FFPROBE_BIN  Caminho dos executáveis (padrão: procurados no PATH).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import uuid
from collections import deque
from collections.abc import Awaitable, Callable, Iterable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

logger = logging.getLogger("video_editor")

# ---------------------------------------------------------------------------
# Extensões permitidas
# ---------------------------------------------------------------------------

VIDEO_EXTS = frozenset({
    ".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".flv", ".ts", ".mpg", ".mpeg", ".wmv", ".3gp",
})
AUDIO_EXTS = frozenset({".mp3", ".aac", ".m4a", ".wav", ".flac", ".ogg", ".opus", ".wma"})
IMAGE_EXTS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"})
SUBTITLE_EXTS = frozenset({".srt", ".ass", ".ssa", ".vtt"})
FONT_EXTS = frozenset({".ttf", ".otf", ".ttc"})
MEDIA_EXTS = VIDEO_EXTS | AUDIO_EXTS

DEFAULT_TIMEOUT = 900.0
STDERR_TAIL_LINES = 12


class VideoEditorError(Exception):
    """Erro de uso ou de execução, com mensagem pronta pra ser mostrada ao modelo."""


class FFmpegError(VideoEditorError):
    """O ffmpeg/ffprobe terminou com erro ou estourou o timeout."""


# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------


def get_workdir() -> Path:
    """Diretório de trabalho (sandbox). Lido a cada chamada pra facilitar testes."""
    raw = os.environ.get("VIDEO_WORKDIR") or str(Path.cwd() / "workspace")
    workdir = Path(raw).expanduser().resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    return workdir


def get_timeout() -> float:
    try:
        value = float(os.environ.get("VIDEO_FFMPEG_TIMEOUT", DEFAULT_TIMEOUT))
    except ValueError:
        return DEFAULT_TIMEOUT
    return value if value > 0 else DEFAULT_TIMEOUT


def ffmpeg_bin() -> str:
    return os.environ.get("FFMPEG_BIN") or shutil.which("ffmpeg") or "ffmpeg"


def ffprobe_bin() -> str:
    return os.environ.get("FFPROBE_BIN") or shutil.which("ffprobe") or "ffprobe"


_semaphore: asyncio.Semaphore | None = None
_semaphore_loop: asyncio.AbstractEventLoop | None = None


def _job_semaphore() -> asyncio.Semaphore:
    """Semáforo que limita ffmpeg simultâneos (recriado se o event loop mudar)."""
    global _semaphore, _semaphore_loop
    loop = asyncio.get_running_loop()
    if _semaphore is None or _semaphore_loop is not loop:
        try:
            jobs = max(1, int(os.environ.get("VIDEO_MAX_JOBS", "2")))
        except ValueError:
            jobs = 2
        _semaphore = asyncio.Semaphore(jobs)
        _semaphore_loop = loop
    return _semaphore


def check_ffmpeg() -> dict[str, str | None]:
    """Confere se ffmpeg e ffprobe existem e devolve as versões (None = não achado)."""
    result: dict[str, str | None] = {}
    for name, binary in (("ffmpeg", ffmpeg_bin()), ("ffprobe", ffprobe_bin())):
        try:
            proc = subprocess.run(
                [binary, "-version"], capture_output=True, text=True, timeout=15, check=False
            )
            first_line = proc.stdout.splitlines()[0] if proc.stdout else ""
            result[name] = first_line if proc.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired):
            result[name] = None
    return result


_filters_cache: set[str] | None = None


def available_filters() -> set[str]:
    """Nomes dos filtros que este ffmpeg tem (drawtext e subtitles dependem da build)."""
    global _filters_cache
    if _filters_cache is None:
        try:
            proc = subprocess.run(
                [ffmpeg_bin(), "-hide_banner", "-filters"],
                capture_output=True, text=True, timeout=15, check=False,
            )
            names = set()
            for line in proc.stdout.splitlines():
                parts = line.split()
                if len(parts) >= 3 and "->" in parts[2]:
                    names.add(parts[1])
            _filters_cache = names
        except (OSError, subprocess.TimeoutExpired):
            _filters_cache = set()
    return _filters_cache


def require_filter(name: str, hint: str) -> None:
    if name not in available_filters():
        raise VideoEditorError(
            f"O ffmpeg instalado não tem o filtro '{name}'. {hint}"
        )


# ---------------------------------------------------------------------------
# Caminhos (sandbox)
# ---------------------------------------------------------------------------


def _resolve_in_workdir(path: str, what: str) -> Path:
    if not isinstance(path, str) or not path.strip():
        raise VideoEditorError(f"Informe o caminho de {what}.")
    if "\x00" in path:
        raise VideoEditorError(f"Caminho de {what} inválido.")
    workdir = get_workdir()
    candidate = Path(path.strip()).expanduser()
    if not candidate.is_absolute():
        candidate = workdir / candidate
    # resolve() segue symlinks: um link dentro do workdir que aponta pra fora é barrado.
    resolved = candidate.resolve()
    if resolved != workdir and not resolved.is_relative_to(workdir):
        raise VideoEditorError(
            f"Caminho de {what} fora do diretório de trabalho: '{path}'. "
            f"Use caminhos relativos a {workdir}."
        )
    return resolved


def _check_ext(p: Path, allowed: Iterable[str], what: str) -> None:
    allowed = frozenset(allowed)
    if p.suffix.lower() not in allowed:
        raise VideoEditorError(
            f"Extensão '{p.suffix or '(nenhuma)'}' não permitida para {what}. "
            f"Permitidas: {', '.join(sorted(allowed))}."
        )


def resolve_input(path: str, allowed_exts: Iterable[str], what: str = "entrada") -> Path:
    """Valida um arquivo de entrada: dentro do workdir, existe, é arquivo, extensão ok."""
    p = _resolve_in_workdir(path, what)
    _check_ext(p, allowed_exts, what)
    if not p.exists():
        raise VideoEditorError(f"Arquivo de {what} não encontrado: '{path}'.")
    if not p.is_file():
        raise VideoEditorError(f"'{path}' não é um arquivo.")
    return p


def resolve_output(
    path: str,
    allowed_exts: Iterable[str],
    overwrite: bool = False,
    inputs: Iterable[Path] = (),
    what: str = "saída",
) -> Path:
    """Valida um arquivo de saída. Cria as pastas intermediárias (dentro do workdir)."""
    p = _resolve_in_workdir(path, what)
    _check_ext(p, allowed_exts, what)
    if p in set(inputs):
        raise VideoEditorError("O arquivo de saída não pode ser o mesmo de uma entrada.")
    if p.exists():
        if p.is_dir():
            raise VideoEditorError(f"'{path}' é uma pasta, não um arquivo.")
        if not overwrite:
            raise VideoEditorError(
                f"O arquivo '{path}' já existe. Use overwrite=true para substituí-lo "
                "ou escolha outro nome."
            )
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def resolve_dir(path: str, what: str = "pasta de saída") -> Path:
    p = _resolve_in_workdir(path, what)
    if p.exists() and not p.is_dir():
        raise VideoEditorError(f"'{path}' existe e não é uma pasta.")
    p.mkdir(parents=True, exist_ok=True)
    return p


def rel(p: Path) -> str:
    """Caminho relativo ao workdir (é o que o modelo deve usar nas próximas chamadas)."""
    try:
        return str(p.relative_to(get_workdir()))
    except ValueError:
        return str(p)


@asynccontextmanager
async def atomic_output(final: Path):
    """Entrega um caminho temporário na mesma pasta e só renomeia pro final se der certo.

    Assim uma falha ou timeout nunca deixa um arquivo pela metade no lugar do
    destino (nem destrói o arquivo antigo quando ``overwrite=True``).
    """
    tmp = final.with_name(f".{final.stem}.tmp-{uuid.uuid4().hex[:8]}{final.suffix}")
    try:
        yield tmp
        if not tmp.exists() or tmp.stat().st_size == 0:
            raise FFmpegError("O ffmpeg terminou sem gerar o arquivo de saída.")
        os.replace(tmp, final)
    finally:
        tmp.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Validação de valores
# ---------------------------------------------------------------------------

_TIME_RE = re.compile(r"^(?:(\d+):)?(?:(\d+):)?(\d+(?:\.\d+)?)$")


def parse_time(value: str | float | int | None, what: str = "tempo") -> float | None:
    """Aceita segundos (``12.5``) ou ``HH:MM:SS(.ms)`` / ``MM:SS``. None passa direto."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise VideoEditorError(f"{what} inválido: {value!r}.")
    if isinstance(value, (int, float)):
        seconds = float(value)
    else:
        m = _TIME_RE.match(str(value).strip())
        if not m:
            raise VideoEditorError(
                f"{what} inválido: '{value}'. Use segundos (ex: 12.5) ou HH:MM:SS(.ms)."
            )
        a, b, c = m.groups()
        parts = [x for x in (a, b) if x is not None]
        seconds = float(c)
        if len(parts) == 2:
            seconds += int(parts[0]) * 3600 + int(parts[1]) * 60
        elif len(parts) == 1:
            seconds += int(parts[0]) * 60
    if seconds != seconds or seconds < 0:  # NaN ou negativo
        raise VideoEditorError(f"{what} não pode ser negativo: {value!r}.")
    return seconds


def check_range(value: float, lo: float, hi: float, what: str) -> float:
    if not (lo <= value <= hi):
        raise VideoEditorError(f"{what} deve estar entre {lo} e {hi} (recebido: {value}).")
    return value


_COLOR_RE = re.compile(r"^(#|0x)?[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$|^[a-zA-Z]{3,20}(@\d*\.?\d+)?$")


def validate_color(color: str) -> str:
    """Cor no formato do ffmpeg: nome (white, red), #RRGGBB, 0xRRGGBB ou com @opacidade."""
    color = (color or "").strip()
    if not _COLOR_RE.match(color):
        raise VideoEditorError(
            f"Cor inválida: '{color}'. Use um nome (white, black, yellow...) ou #RRGGBB."
        )
    if re.fullmatch(r"[0-9a-fA-F]{6}([0-9a-fA-F]{2})?", color):
        color = "#" + color
    return color


POSITIONS = (
    "top-left", "top", "top-right",
    "left", "center", "right",
    "bottom-left", "bottom", "bottom-right",
)


def position_expr(position: str, margin: int, w: str, h: str, ow: str, oh: str) -> tuple[str, str]:
    """Expressões x/y do ffmpeg pra posicionar um elemento (ow x oh) num quadro (w x h)."""
    pos = (position or "").strip().lower().replace("_", "-").replace(" ", "-")
    aliases = {"middle": "center", "centre": "center", "top-center": "top", "bottom-center": "bottom",
               "center-left": "left", "center-right": "right"}
    pos = aliases.get(pos, pos)
    if pos not in POSITIONS:
        raise VideoEditorError(f"Posição inválida: '{position}'. Use uma de: {', '.join(POSITIONS)}.")
    m = int(margin)
    if "left" in pos:
        x = f"{m}"
    elif "right" in pos:
        x = f"{w}-{ow}-{m}"
    else:
        x = f"({w}-{ow})/2"
    if pos.startswith("top"):
        y = f"{m}"
    elif pos.startswith("bottom"):
        y = f"{h}-{oh}-{m}"
    else:
        y = f"({h}-{oh})/2"
    return x, y


def escape_filter_value(value: str) -> str:
    """Escapa um valor (ex: caminho de arquivo) pra usar dentro de um filtergraph.

    São dois níveis de escape do ffmpeg: o do valor da opção (``\\ ' :``) e o do
    filtergraph (``\\ ' [ ] , ;``). Sem isso, um nome de arquivo com vírgula ou
    dois-pontos quebraria o filtro (ou viraria injeção de filtro).
    """
    level1 = re.sub(r"([\\':])", r"\\\1", value)
    return re.sub(r"([\\'\[\],;])", r"\\\1", level1)


# ---------------------------------------------------------------------------
# Execução
# ---------------------------------------------------------------------------


def summarize_stderr(lines: Iterable[str], max_lines: int = STDERR_TAIL_LINES) -> str:
    """Últimas linhas relevantes do stderr do ffmpeg (sem banner/progresso)."""
    noise = ("frame=", "size=", "Press [q]", "  configuration:", "  lib", "built with")
    kept = [ln.rstrip() for ln in lines if ln.strip() and not ln.lstrip().startswith(noise)]
    tail = kept[-max_lines:]
    return "\n".join(tail) if tail else "(sem saída de erro)"


ProgressCallback = Callable[[float], Awaitable[None]]


async def run_ffmpeg(
    args: list[str],
    *,
    duration: float | None = None,
    on_progress: ProgressCallback | None = None,
    timeout: float | None = None,
) -> str:
    """Roda ``ffmpeg <args>`` sem shell, com timeout e progresso opcional.

    ``duration`` (segundos da saída esperada) permite calcular o progresso a partir
    do ``-progress pipe:1``; ``on_progress`` recebe uma fração 0..1.
    Retorna o stderr resumido; levanta FFmpegError se falhar ou estourar o tempo.
    """
    timeout = timeout or get_timeout()
    cmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-y", "-progress", "pipe:1", "-nostats", *args]
    logger.info("ffmpeg: %s", " ".join(cmd[1:]))
    stderr_tail: deque[str] = deque(maxlen=200)

    async with _job_semaphore():
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise FFmpegError(
                "ffmpeg não encontrado. Instale o FFmpeg e deixe-o no PATH (ou defina FFMPEG_BIN)."
            ) from exc

        async def read_stdout() -> None:
            assert proc.stdout is not None
            last = -1.0
            async for raw in proc.stdout:
                line = raw.decode("utf-8", "replace").strip()
                if not (on_progress and duration and duration > 0):
                    continue
                key, _, val = line.partition("=")
                # out_time_ms é, apesar do nome, em microssegundos (bug histórico do ffmpeg).
                if key in ("out_time_us", "out_time_ms") and val.lstrip("-").isdigit():
                    frac = min(max(int(val) / 1_000_000 / duration, 0.0), 1.0)
                    if frac - last >= 0.02:
                        last = frac
                        try:
                            await on_progress(frac)
                        except Exception:  # progresso nunca derruba o job
                            logger.debug("falha ao reportar progresso", exc_info=True)

        async def read_stderr() -> None:
            assert proc.stderr is not None
            async for raw in proc.stderr:
                stderr_tail.append(raw.decode("utf-8", "replace"))

        try:
            await asyncio.wait_for(asyncio.gather(read_stdout(), read_stderr(), proc.wait()), timeout)
        except (TimeoutError, asyncio.TimeoutError):
            _kill(proc)
            await proc.wait()
            raise FFmpegError(
                f"O ffmpeg passou do tempo limite de {timeout:.0f}s e foi interrompido. "
                "Aumente VIDEO_FFMPEG_TIMEOUT ou processe um trecho menor.\n"
                + summarize_stderr(stderr_tail)
            ) from None
        except asyncio.CancelledError:
            _kill(proc)
            await proc.wait()
            raise

    if proc.returncode != 0:
        raise FFmpegError(
            f"O ffmpeg falhou (código {proc.returncode}):\n{summarize_stderr(stderr_tail)}"
        )
    return summarize_stderr(stderr_tail)


def _kill(proc: asyncio.subprocess.Process) -> None:
    try:
        proc.kill()
    except ProcessLookupError:
        pass


async def ffprobe(path: Path, timeout: float = 60.0) -> dict[str, Any]:
    """JSON completo do ffprobe (format + streams)."""
    cmd = [ffprobe_bin(), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise FFmpegError("ffprobe não encontrado. Instale o FFmpeg (o ffprobe vem junto).") from exc
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except (TimeoutError, asyncio.TimeoutError):
        _kill(proc)
        await proc.wait()
        raise FFmpegError(f"ffprobe passou do tempo limite de {timeout:.0f}s.") from None
    if proc.returncode != 0:
        msg = summarize_stderr(err.decode("utf-8", "replace").splitlines())
        raise FFmpegError(f"Não foi possível ler '{rel(path)}' (arquivo corrompido ou não é mídia):\n{msg}")
    try:
        return json.loads(out or b"{}")
    except json.JSONDecodeError as exc:
        raise FFmpegError("Resposta inválida do ffprobe.") from exc


def _parse_rate(rate: str | None) -> float | None:
    if not rate or rate in ("0/0", "0"):
        return None
    try:
        num, _, den = rate.partition("/")
        value = float(num) / float(den or 1)
    except (ValueError, ZeroDivisionError):
        return None
    return round(value, 3) if value > 0 else None


class MediaInfo:
    """Resumo do ffprobe com o que as tools precisam."""

    def __init__(self, path: Path, data: dict[str, Any]):
        self.path = path
        self.raw = data
        fmt = data.get("format", {})
        streams = data.get("streams", [])
        self.video = next(
            (s for s in streams if s.get("codec_type") == "video"
             and not s.get("disposition", {}).get("attached_pic")),
            None,
        )
        self.audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
        self.streams = streams
        self.format = fmt
        dur = fmt.get("duration") or (self.video or {}).get("duration") or (self.audio or {}).get("duration")
        try:
            self.duration = float(dur) if dur is not None else None
        except ValueError:
            self.duration = None

    @property
    def has_video(self) -> bool:
        return self.video is not None

    @property
    def has_audio(self) -> bool:
        return self.audio is not None

    @property
    def width(self) -> int | None:
        return (self.video or {}).get("width")

    @property
    def height(self) -> int | None:
        return (self.video or {}).get("height")

    @property
    def fps(self) -> float | None:
        if not self.video:
            return None
        return _parse_rate(self.video.get("avg_frame_rate")) or _parse_rate(self.video.get("r_frame_rate"))

    def summary(self) -> dict[str, Any]:
        size = int(self.format.get("size") or self.path.stat().st_size)
        info: dict[str, Any] = {
            "path": rel(self.path),
            "container": self.format.get("format_name"),
            "duration_seconds": round(self.duration, 3) if self.duration is not None else None,
            "size_bytes": size,
            "size_human": human_size(size),
            "bit_rate_kbps": round(int(self.format["bit_rate"]) / 1000) if self.format.get("bit_rate") else None,
            "video": None,
            "audio": None,
            "stream_count": len(self.streams),
        }
        if self.video:
            v = self.video
            rotation = None
            for sd in v.get("side_data_list", []) or []:
                if "rotation" in sd:
                    rotation = sd["rotation"]
            info["video"] = {
                "codec": v.get("codec_name"),
                "profile": v.get("profile"),
                "width": v.get("width"),
                "height": v.get("height"),
                "resolution": f"{v.get('width')}x{v.get('height')}",
                "fps": self.fps,
                "pix_fmt": v.get("pix_fmt"),
                "bit_rate_kbps": round(int(v["bit_rate"]) / 1000) if v.get("bit_rate") else None,
                "rotation": rotation,
            }
        if self.audio:
            a = self.audio
            info["audio"] = {
                "codec": a.get("codec_name"),
                "sample_rate": int(a["sample_rate"]) if a.get("sample_rate") else None,
                "channels": a.get("channels"),
                "channel_layout": a.get("channel_layout"),
                "bit_rate_kbps": round(int(a["bit_rate"]) / 1000) if a.get("bit_rate") else None,
            }
        return info


async def probe(path: Path) -> MediaInfo:
    return MediaInfo(path, await ffprobe(path))


def human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def progress_reporter(ctx: Any) -> ProgressCallback | None:
    """Callback de progresso que repassa pro cliente MCP (se houver Context)."""
    if ctx is None:
        return None

    async def report(frac: float) -> None:
        await ctx.report_progress(round(frac * 100, 1), 100.0)

    return report


async def output_result(path: Path, **extra: Any) -> dict[str, Any]:
    """Resposta padrão das tools que geram um arquivo: caminho + metadados do resultado."""
    info = await probe(path)
    summary = info.summary()
    result: dict[str, Any] = {
        "ok": True,
        "output": rel(path),
        "duration_seconds": summary["duration_seconds"],
        "size_human": summary["size_human"],
    }
    if summary["video"]:
        result["resolution"] = summary["video"]["resolution"]
        result["fps"] = summary["video"]["fps"]
    result["has_audio"] = summary["audio"] is not None
    result.update(extra)
    return result
