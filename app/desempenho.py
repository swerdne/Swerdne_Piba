"""Carregamento rapido das paginas (principalmente no celular, em 4G).

1. Arquivos estaticos versionados: url_for('static', ...) ganha ?v=<hash do
   conteudo>. Com a versao no endereco, o navegador (e o service worker)
   guardam o arquivo por 1 ano sem perguntar nada ao servidor; um deploy
   que muda o arquivo muda o hash, e o endereco novo e baixado na hora. Sem
   isso, toda troca de pagina revalidava style.css/main.js/logo na rede
   (Cache-Control: no-cache), ~300 ms cada no celular.
2. Compressao gzip de HTML/CSS/JS/JSON (o Azure App Service nao comprime
   sozinho): o CSS cai de ~52 KB pra ~10 KB, uma pagina de ~40 KB pra ~8 KB.
"""
import gzip
import hashlib
import os

_TIPOS_COMPRIMIVEIS = (
    "text/html", "text/css", "text/plain", "text/javascript", "application/javascript",
    "application/json", "application/manifest+json", "image/svg+xml",
)
_MINIMO_BYTES = 1024
_UM_ANO = "public, max-age=31536000, immutable"


def registrar_desempenho(app):
    versoes = {}  # caminho -> (mtime, hash): recalcula so se o arquivo mudar
    gzip_estaticos = {}  # (caminho, hash) -> bytes comprimidos

    def versao_do_arquivo(nome):
        caminho = os.path.join(app.static_folder, nome)
        try:
            mtime = os.path.getmtime(caminho)
        except OSError:
            return None
        guardado = versoes.get(caminho)
        if guardado and guardado[0] == mtime:
            return guardado[1]
        with open(caminho, "rb") as arquivo:
            resumo = hashlib.sha1(arquivo.read()).hexdigest()[:10]
        versoes[caminho] = (mtime, resumo)
        return resumo

    @app.url_defaults
    def versionar_estaticos(endpoint, valores):
        if endpoint == "static" and "v" not in valores and valores.get("filename"):
            versao = versao_do_arquivo(valores["filename"])
            if versao:
                valores["v"] = versao

    @app.after_request
    def cache_e_compressao(resposta):
        from flask import request

        estatico_versionado = request.endpoint == "static" and request.args.get("v")
        if estatico_versionado and resposta.status_code in (200, 304):
            resposta.headers["Cache-Control"] = _UM_ANO

        if (
            resposta.status_code != 200
            or resposta.mimetype not in _TIPOS_COMPRIMIVEIS
            or "Content-Encoding" in resposta.headers
            or "gzip" not in (request.headers.get("Accept-Encoding") or "").lower()
            or resposta.is_streamed and not resposta.direct_passthrough
        ):
            return resposta

        resposta.direct_passthrough = False  # arquivo do send_file: le pra memoria
        dados = resposta.get_data()
        if len(dados) < _MINIMO_BYTES:
            return resposta
        chave = (request.path, request.args.get("v")) if estatico_versionado else None
        comprimido = gzip_estaticos.get(chave) if chave else None
        if comprimido is None:
            comprimido = gzip.compress(dados, compresslevel=6)
            if chave:
                gzip_estaticos[chave] = comprimido
        resposta.set_data(comprimido)
        resposta.headers["Content-Encoding"] = "gzip"
        resposta.headers["Content-Length"] = str(len(comprimido))
        resposta.vary.add("Accept-Encoding")
        return resposta
