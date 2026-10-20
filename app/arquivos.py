"""Entrega de arquivo guardado no banco (audio/foto/video/documento) pro
navegador -- usado pelos Materiais da escala e pela caixa de entrada do
WhatsApp."""
from urllib.parse import quote

from flask import Response, request

# Abre na propria tela (player/imagem); o resto sempre baixa -- nunca serve
# HTML/SVG/script inline (arquivo veio de fora).
_TIPOS_NA_TELA = ("audio/", "video/", "image/jpeg", "image/png", "image/webp", "image/gif", "application/pdf")


def abre_na_tela(mime):
    return bool(mime) and mime.startswith(_TIPOS_NA_TELA)


def resposta_de_arquivo(conteudo, mime, nome, baixar=False):
    """Inline (ou download com `baixar`) e com Range (pedaco do arquivo): o
    Safari do iPhone so toca <audio>/<video> se o servidor responder 206 aos
    pedidos de "bytes=...", e e o que deixa avancar/voltar no player."""
    mime = mime or "application/octet-stream"
    total = len(conteudo)
    inicio, fim, status = 0, total - 1, 200
    pedido = request.headers.get("Range", "")
    if pedido.startswith("bytes=") and total:
        ini_txt, _, fim_txt = pedido[6:].split(",")[0].strip().partition("-")
        try:
            if ini_txt:
                inicio = int(ini_txt)
                fim = min(int(fim_txt), total - 1) if fim_txt else total - 1
            else:  # "bytes=-500" = os ultimos 500
                inicio = max(0, total - int(fim_txt))
        except ValueError:
            inicio, fim = 0, total - 1
        if inicio > fim or inicio >= total:
            resposta = Response(status=416)
            resposta.headers["Content-Range"] = f"bytes */{total}"
            return resposta
        status = 206
    resposta = Response(conteudo[inicio:fim + 1], status=status, mimetype=mime)
    resposta.headers["Accept-Ranges"] = "bytes"
    if status == 206:
        resposta.headers["Content-Range"] = f"bytes {inicio}-{fim}/{total}"
    modo = "attachment" if baixar or not abre_na_tela(mime) else "inline"
    seguro = "".join(c if c.isascii() and c not in '"\\' else "_" for c in nome)
    resposta.headers["Content-Disposition"] = f"{modo}; filename=\"{seguro}\"; filename*=UTF-8''{quote(nome)}"
    resposta.headers["Cache-Control"] = "private, max-age=3600"
    resposta.headers["X-Content-Type-Options"] = "nosniff"
    return resposta
