"""Estaticos versionados com cache longo + gzip (app/desempenho.py)."""
import gzip
import re


def test_estaticos_ganham_versao_e_cache_de_um_ano(client):
    html = client.get("/auth/login").data.decode("utf-8")
    css = re.search(r'href="(/static/css/style\.css\?v=[0-9a-f]{10})"', html)
    js = re.search(r'src="(/static/js/main\.js\?v=[0-9a-f]{10})"', html)
    assert css and js

    resposta = client.get(css.group(1))
    assert resposta.status_code == 200
    assert resposta.headers["Cache-Control"] == "public, max-age=31536000, immutable"
    # Sem versao no endereco continua revalidando (nao fica preso numa copia velha).
    assert "immutable" not in client.get("/static/css/style.css").headers.get("Cache-Control", "")


def test_respostas_de_texto_saem_comprimidas_quando_o_navegador_aceita(client):
    normal = client.get("/static/css/style.css")
    comprimida = client.get("/static/css/style.css", headers={"Accept-Encoding": "gzip, deflate, br"})
    assert comprimida.headers["Content-Encoding"] == "gzip"
    assert "Accept-Encoding" in comprimida.headers["Vary"]
    assert gzip.decompress(comprimida.data) == normal.data
    assert len(comprimida.data) < len(normal.data) / 3

    pagina = client.get("/auth/login", headers={"Accept-Encoding": "gzip"})
    assert pagina.headers["Content-Encoding"] == "gzip"
    assert b"<html" in gzip.decompress(pagina.data)


def test_imagem_nao_e_recomprimida(client):
    resposta = client.get("/static/img/logo-icone.png", headers={"Accept-Encoding": "gzip"})
    assert resposta.status_code == 200
    assert "Content-Encoding" not in resposta.headers
