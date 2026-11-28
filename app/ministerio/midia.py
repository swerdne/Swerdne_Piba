"""Player junto da cifra: reconhece o link cadastrado na musica (ou no item
do repertorio da escala) e diz como tocar dentro do app.

- YouTube (watch?v=, youtu.be/, /shorts/, /embed/, /live/): embed pelo
  youtube-nocookie, carregado so quando a pessoa toca em "Ouvir aqui"
  (iframe do YouTube pesa e rastreia; ver ministerio/_player.html).
- Arquivo de audio (.mp3, .m4a, .ogg, .wav, .aac, .opus): <audio>.
- Qualquer outro link continua so como link.
"""
import re
from urllib.parse import parse_qs, urlparse

_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_AUDIO = (".mp3", ".m4a", ".ogg", ".oga", ".wav", ".aac", ".opus")


def id_do_youtube(url):
    try:
        partes = urlparse((url or "").strip())
    except ValueError:
        return None
    if partes.scheme not in ("http", "https"):
        return None
    host = (partes.hostname or "").lower()
    if host.startswith("www.") or host.startswith("m."):
        host = host.split(".", 1)[1]
    candidato = None
    if host == "youtu.be":
        candidato = partes.path.strip("/").split("/")[0]
    elif host in ("youtube.com", "music.youtube.com", "youtube-nocookie.com"):
        if partes.path == "/watch":
            candidato = (parse_qs(partes.query).get("v") or [""])[0]
        else:
            pedacos = partes.path.strip("/").split("/")
            if len(pedacos) >= 2 and pedacos[0] in ("shorts", "embed", "live", "v"):
                candidato = pedacos[1]
    return candidato if candidato and _ID.match(candidato) else None


def midia_do_link(url):
    """{"tipo": "youtube", "id": ..., "embed": ...} | {"tipo": "audio", "url": ...} | None."""
    video = id_do_youtube(url)
    if video:
        return {"tipo": "youtube", "id": video,
                "embed": f"https://www.youtube-nocookie.com/embed/{video}?rel=0&playsinline=1&autoplay=1"}
    try:
        partes = urlparse((url or "").strip())
    except ValueError:
        return None
    if partes.scheme == "https" and partes.path.lower().endswith(_AUDIO):
        return {"tipo": "audio", "url": url.strip()}
    return None
