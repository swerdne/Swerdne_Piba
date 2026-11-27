"""Tools que desenham sobre a imagem: texto, legendas e marca d'água."""

import tempfile
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations

from ffmpeg_utils import (
    FONT_EXTS, IMAGE_EXTS, SUBTITLE_EXTS, VIDEO_EXTS, VideoEditorError, atomic_output,
    check_range, escape_filter_value, output_result, parse_time, position_expr, probe,
    progress_reporter, require_filter, resolve_input, resolve_output, run_ffmpeg, validate_color,
)

from ._common import video_encode_args

MAX_TEXT_CHARS = 2000


def _time_window(start, end, total: float | None) -> tuple[float, float | None]:
    t0 = parse_time(start, "start") or 0.0
    t1 = parse_time(end, "end")
    if total is not None and t0 >= total:
        raise VideoEditorError(f"start ({t0:.3f}s) é maior ou igual à duração do vídeo ({total:.3f}s).")
    if t1 is not None and t1 <= t0:
        raise VideoEditorError(f"end ({t1:.3f}s) precisa ser maior que start ({t0:.3f}s).")
    return t0, t1


def _enable_expr(t0: float, t1: float | None) -> str | None:
    if t0 <= 0 and t1 is None:
        return None
    if t1 is None:
        return f"gte(t,{t0:.3f})"
    return f"between(t,{t0:.3f},{t1:.3f})"


async def add_text_overlay(
    input: str,
    text: str,
    output: str,
    position: str = "bottom",
    font_size: int = 48,
    color: str = "white",
    start: str | float | None = None,
    end: str | float | None = None,
    box: bool = False,
    box_color: str = "black@0.5",
    border_width: int = 2,
    margin: int = 40,
    font_file: str | None = None,
    overwrite: bool = False,
    ctx: Context = None,
) -> dict[str, Any]:
    """Escreve um texto por cima do vídeo (título, nome, chamada), opcionalmente só num intervalo de tempo.

    O texto aceita acentos, emojis simples e várias linhas (use "\\n"). O som é mantido.

    Args:
        input: Vídeo de origem (relativo ao diretório de trabalho).
        text: Texto a escrever (até 2000 caracteres).
        output: Arquivo de saída. Não pode já existir, a menos que overwrite=true.
        position: top-left, top, top-right, left, center, right, bottom-left,
                  bottom (padrão) ou bottom-right.
        font_size: Tamanho da fonte em pixels (8–400). Para 1080p, 48–72 é legível.
        color: Cor do texto: nome (white, yellow, red...) ou "#RRGGBB".
        start: A partir de quando o texto aparece (segundos ou HH:MM:SS). Vazio = desde o início.
        end: Até quando o texto aparece. Vazio = até o fim.
        box: true = desenha uma caixa atrás do texto (melhora a leitura).
        box_color: Cor da caixa, com opacidade após "@" (ex: "black@0.5").
        border_width: Contorno preto em volta das letras, em pixels (0 = sem contorno).
        margin: Distância da borda do vídeo, em pixels.
        font_file: Fonte .ttf/.otf opcional (dentro do diretório de trabalho). Sem ela,
                   usa a fonte padrão do sistema (fontconfig).
        overwrite: Permite substituir `output` se ele já existir.

    Returns:
        ok, output, duration_seconds, resolution, fps, has_audio.
    """
    require_filter("drawtext", "Instale uma build do FFmpeg com libfreetype (ex: o pacote ffmpeg do apt/brew).")
    if not isinstance(text, str) or not text.strip():
        raise VideoEditorError("Informe o texto.")
    if len(text) > MAX_TEXT_CHARS:
        raise VideoEditorError(f"Texto muito longo (máx. {MAX_TEXT_CHARS} caracteres).")
    font_size = int(check_range(int(font_size), 8, 400, "font_size"))
    border_width = int(check_range(int(border_width), 0, 20, "border_width"))
    margin = int(check_range(int(margin), 0, 2000, "margin"))
    color = validate_color(color)
    box_color = validate_color(box_color)
    src = resolve_input(input, VIDEO_EXTS, "vídeo de entrada")
    font = resolve_input(font_file, FONT_EXTS, "fonte") if font_file else None
    dst = resolve_output(output, VIDEO_EXTS, overwrite, [src])
    info = await probe(src)
    t0, t1 = _time_window(start, end, info.duration)
    x, y = position_expr(position, margin, "w", "h", "text_w", "text_h")

    with tempfile.TemporaryDirectory() as tmpdir:
        # O texto vai num arquivo (textfile=) em vez de inline: evita ter que escapar
        # aspas, dois-pontos, % e barras do texto do usuário dentro do filtro.
        textfile = Path(tmpdir) / "text.txt"
        textfile.write_text(text.replace("\\n", "\n"), encoding="utf-8")
        opts = [
            f"textfile={escape_filter_value(str(textfile))}",
            "expansion=none",
            f"fontsize={font_size}",
            f"fontcolor={color}",
            f"x={x}", f"y={y}",
            "line_spacing=8",
        ]
        if font:
            opts.append(f"fontfile={escape_filter_value(str(font))}")
        if border_width:
            opts += [f"borderw={border_width}", "bordercolor=black"]
        if box:
            opts += ["box=1", f"boxcolor={box_color}", f"boxborderw={max(font_size // 4, 4)}"]
        enable = _enable_expr(t0, t1)
        if enable:
            opts.append(f"enable='{enable}'")
        vf = "drawtext=" + ":".join(opts)
        args = ["-i", str(src), "-vf", vf, "-map", "0:v:0", "-map", "0:a:0?", *video_encode_args(dst)]
        async with atomic_output(dst) as tmp:
            await run_ffmpeg([*args, str(tmp)], duration=info.duration, on_progress=progress_reporter(ctx))
    return await output_result(dst)


async def add_subtitles(
    input: str,
    srt_path: str,
    output: str,
    font_size: int | None = None,
    font_color: str | None = None,
    overwrite: bool = False,
    ctx: Context = None,
) -> dict[str, Any]:
    """Queima (grava permanentemente na imagem) uma legenda .srt/.ass/.vtt no vídeo.

    A legenda passa a fazer parte do vídeo e aparece em qualquer player/rede social (não
    dá para desligar depois). O arquivo de legenda deve estar em UTF-8.

    Args:
        input: Vídeo de origem (relativo ao diretório de trabalho).
        srt_path: Arquivo de legenda (.srt, .ass, .ssa ou .vtt) no diretório de trabalho.
        output: Arquivo de saída. Não pode já existir, a menos que overwrite=true.
        font_size: Tamanho da fonte da legenda (opcional; padrão do libass ≈ 16 numa
                   escala de 288 linhas — 20–28 costuma ficar bom).
        font_color: Cor do texto da legenda, "#RRGGBB" (opcional; padrão branco).
        overwrite: Permite substituir `output` se ele já existir.

    Returns:
        ok, output, duration_seconds, resolution, fps, has_audio.
    """
    require_filter("subtitles", "Instale uma build do FFmpeg com libass.")
    src = resolve_input(input, VIDEO_EXTS, "vídeo de entrada")
    subs = resolve_input(srt_path, SUBTITLE_EXTS, "legenda")
    dst = resolve_output(output, VIDEO_EXTS, overwrite, [src, subs])
    if subs.stat().st_size == 0:
        raise VideoEditorError(f"O arquivo de legenda '{srt_path}' está vazio.")
    try:
        subs.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise VideoEditorError(
            f"A legenda '{srt_path}' não está em UTF-8. Converta o arquivo (ex: salve como UTF-8 no editor)."
        ) from None
    info = await probe(src)
    style = []
    if font_size is not None:
        style.append(f"Fontsize={int(check_range(int(font_size), 4, 200, 'font_size'))}")
    if font_color:
        c = validate_color(font_color).lstrip("#").removeprefix("0x")
        if len(c) != 6:
            raise VideoEditorError("font_color da legenda deve ser #RRGGBB.")
        # ASS usa &HBBGGRR&
        style.append(f"PrimaryColour=&H00{c[4:6]}{c[2:4]}{c[0:2]}&")
    vf = f"subtitles=filename={escape_filter_value(str(subs))}:charenc=UTF-8"
    if style:
        vf += f":force_style={escape_filter_value(','.join(style))}"
    args = ["-i", str(src), "-vf", vf, "-map", "0:v:0", "-map", "0:a:0?", *video_encode_args(dst)]
    async with atomic_output(dst) as tmp:
        await run_ffmpeg([*args, str(tmp)], duration=info.duration, on_progress=progress_reporter(ctx))
    return await output_result(dst)


async def add_watermark(
    input: str,
    image: str,
    output: str,
    position: str = "bottom-right",
    opacity: float = 0.7,
    scale: float = 0.15,
    margin: int = 20,
    overwrite: bool = False,
    ctx: Context = None,
) -> dict[str, Any]:
    """Sobrepõe uma imagem (logo, marca d'água) no vídeo inteiro, com posição e transparência.

    PNG com fundo transparente dá o melhor resultado. O som é mantido.

    Args:
        input: Vídeo de origem (relativo ao diretório de trabalho).
        image: Imagem da marca d'água (.png, .jpg, .webp...) no diretório de trabalho.
        output: Arquivo de saída. Não pode já existir, a menos que overwrite=true.
        position: top-left, top, top-right, left, center, right, bottom-left, bottom
                  ou bottom-right (padrão).
        opacity: Opacidade de 0.0 (invisível) a 1.0 (sólida). Padrão 0.7.
        scale: Largura da marca como fração da largura do vídeo (0.01 a 1.0; padrão
               0.15 = 15%). A altura segue a proporção da imagem.
        margin: Distância da borda, em pixels.
        overwrite: Permite substituir `output` se ele já existir.

    Returns:
        ok, output, duration_seconds, resolution, fps, has_audio.
    """
    opacity = check_range(float(opacity), 0.0, 1.0, "opacity")
    scale = check_range(float(scale), 0.01, 1.0, "scale")
    margin = int(check_range(int(margin), 0, 2000, "margin"))
    src = resolve_input(input, VIDEO_EXTS, "vídeo de entrada")
    img = resolve_input(image, IMAGE_EXTS, "imagem")
    dst = resolve_output(output, VIDEO_EXTS, overwrite, [src, img])
    info = await probe(src)
    if not info.has_video:
        raise VideoEditorError(f"'{input}' não tem trilha de vídeo.")
    wm_w = max(2, int(info.width * scale) // 2 * 2)
    x, y = position_expr(position, margin, "main_w", "main_h", "overlay_w", "overlay_h")
    graph = (f"[1:v]scale={wm_w}:-1,format=rgba,colorchannelmixer=aa={opacity:.3f}[wm];"
             f"[0:v][wm]overlay=x={x}:y={y}:format=auto,format=yuv420p[outv]")
    # Sem -loop: o overlay repete o último quadro da imagem (eof_action=repeat) até o fim do vídeo.
    args = ["-i", str(src), "-i", str(img), "-filter_complex", graph,
            "-map", "[outv]", "-map", "0:a:0?", *video_encode_args(dst)]
    async with atomic_output(dst) as tmp:
        await run_ffmpeg([*args, str(tmp)], duration=info.duration, on_progress=progress_reporter(ctx))
    return await output_result(dst)


def register(mcp: FastMCP) -> None:
    write = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)
    for fn in (add_text_overlay, add_subtitles, add_watermark):
        mcp.tool(annotations=write)(fn)

