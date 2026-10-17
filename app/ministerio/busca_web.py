"""Busca de musicas NA WEB pelo Banco de Musicas (modo "Na web").

Direitos autorais primeiro (cifra e letra tem dono): o servidor so consulta
fontes que PERMITEM integracao e so traz METADADOS (titulo, artista, album).
A cifra nunca e baixada de site nenhum:

- Deezer API publica (api.deezer.com/search): sem login, as diretrizes do
  Deezer liberam os dados por API e so restringem o AUDIO -- e o audio nao e
  usado aqui. Traz titulo/artista/album; nao traz tom nem cifra.
- Cifra Club / YouTube: SO LINK EXTERNO ("ver cifra no site"), aberto no
  navegador da pessoa. Nao ha API publica do Cifra Club e os termos de uso
  proibem copia automatica (o site ainda bloqueia robos com 403) -- o
  servidor nunca le essas paginas.
- A cifra entra no banco pelo que a pessoa tem direito de trazer: "Colar
  cifra" ou PDF/Word (ministerio/importar_cifras.py), com a fonte registrada
  em Musica.fonte/link_origem.

Sempre no backend, com cache, tempo maximo e erro tratado -- busca externa
fora do ar nunca derruba a tela (a rota devolve {"erro": ...}).
"""
import threading
import time
from urllib.parse import quote_plus, urlparse

import requests
from flask import current_app

FONTE_DEEZER = "Deezer (só dados: título e artista)"
URL_DEEZER = "https://api.deezer.com/search"
TIMEOUT_SEGUNDOS = 6
MAX_RESULTADOS = 12
TERMO_MIN, TERMO_MAX = 2, 100
CACHE_SEGUNDOS = 6 * 3600
CACHE_MAX_ITENS = 500

_cache = {}
_trava_cache = threading.Lock()


class BuscaWebIndisponivel(Exception):
    """A fonte externa nao respondeu ou respondeu errado -- mensagem pra tela."""


def link_seguro(link):
    """So http(s) e ate 500 caracteres (nada de javascript: num href); senao None."""
    link = str(link or "").strip()
    if not link or len(link) > 500:
        return None
    partes = urlparse(link)
    return link if partes.scheme in ("http", "https") and partes.netloc else None


def links_externos(titulo, artista=""):
    """Onde a PESSOA abre a cifra/video no site original (o servidor nao le)."""
    consulta = quote_plus(f"{titulo} {artista}".strip())
    return {
        "cifraclub": f"https://www.cifraclub.com.br/?q={consulta}",
        "youtube": f"https://www.youtube.com/results?search_query={consulta}",
    }


def _do_cache(chave):
    with _trava_cache:
        item = _cache.get(chave)
        if item and item[0] > time.monotonic():
            return item[1]
        _cache.pop(chave, None)
        return None


def _guardar_no_cache(chave, resultados):
    with _trava_cache:
        if len(_cache) >= CACHE_MAX_ITENS:
            # Tira o que vence primeiro (mais antigo).
            for velha in sorted(_cache, key=lambda c: _cache[c][0])[: CACHE_MAX_ITENS // 5]:
                _cache.pop(velha, None)
        _cache[chave] = (time.monotonic() + CACHE_SEGUNDOS, resultados)


def limpar_cache():
    with _trava_cache:
        _cache.clear()


def buscar_na_web(termo):
    """[{titulo, artista, album, fonte, link_origem, links: {cifraclub, youtube}}].
    Levanta ValueError (termo invalido) ou BuscaWebIndisponivel."""
    termo = " ".join(str(termo or "").split())
    if not TERMO_MIN <= len(termo) <= TERMO_MAX:
        raise ValueError(f"Digite de {TERMO_MIN} a {TERMO_MAX} caracteres.")
    chave = termo.lower()
    em_cache = _do_cache(chave)
    if em_cache is not None:
        return em_cache

    try:
        resposta = requests.get(URL_DEEZER, params={"q": termo, "limit": MAX_RESULTADOS}, timeout=TIMEOUT_SEGUNDOS)
        dados = resposta.json() if resposta.status_code == 200 else None
    except (requests.RequestException, ValueError) as erro:
        current_app.logger.warning("Busca na web (Deezer) falhou: %s", erro)
        raise BuscaWebIndisponivel("A busca na web nao respondeu agora. Tente de novo em instantes.") from erro
    if not isinstance(dados, dict) or "error" in dados or not isinstance(dados.get("data"), list):
        current_app.logger.warning("Busca na web (Deezer) respondeu inesperado: %s", str(dados)[:300])
        raise BuscaWebIndisponivel("A busca na web nao respondeu agora. Tente de novo em instantes.")

    resultados, vistos = [], set()
    for faixa in dados["data"]:
        if not isinstance(faixa, dict):
            continue
        titulo = str(faixa.get("title") or "").strip()[:150]
        artista = str((faixa.get("artist") or {}).get("name") or "").strip()[:120]
        if not titulo or (titulo.lower(), artista.lower()) in vistos:
            continue  # a mesma musica em varios albuns aparece uma vez so
        vistos.add((titulo.lower(), artista.lower()))
        resultados.append({
            "titulo": titulo,
            "artista": artista,
            "album": str((faixa.get("album") or {}).get("title") or "").strip()[:150],
            "fonte": FONTE_DEEZER,
            "link_origem": link_seguro(faixa.get("link")),
            "links": links_externos(titulo, artista),
        })
    _guardar_no_cache(chave, resultados)
    return resultados
