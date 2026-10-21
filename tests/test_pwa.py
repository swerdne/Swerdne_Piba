"""App instalavel (PWA) no Android e no iPhone: manifest completo, icones nos
tamanhos certos, tela "sem internet" e telas de abertura do iPhone."""
import json
import re
import struct
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "app" / "static"


def _tamanho_png(caminho):
    dados = caminho.read_bytes()[:24]
    return struct.unpack(">II", dados[16:24])


def test_manifest_tem_o_que_o_android_exige(client):
    resposta = client.get("/static/manifest.webmanifest")
    assert resposta.status_code == 200 and "manifest" in resposta.content_type
    manifest = json.loads(resposta.data)
    # identidade estavel (= start_url antigo, pra nao "duplicar" quem ja instalou)
    assert manifest["id"] == manifest["start_url"] == "/dashboard"
    assert manifest["display"] == "standalone" and manifest["scope"] == "/"
    tamanhos = {(i["sizes"], i["purpose"]) for i in manifest["icons"]}
    assert {("192x192", "any"), ("512x512", "any"), ("512x512", "maskable")} <= tamanhos
    for icone in manifest["icons"]:
        largura, altura = _tamanho_png(STATIC / icone["src"].removeprefix("/static/"))
        assert f"{largura}x{altura}" == icone["sizes"]
    assert [a["url"] for a in manifest["shortcuts"]] == ["/minha-escala", "/dashboard"]


def test_pagina_tem_tags_do_iphone_e_telas_de_abertura(client):
    html = client.get("/auth/login").data.decode()
    for tag in ('name="apple-mobile-web-app-capable"', 'name="mobile-web-app-capable"', 'rel="apple-touch-icon"', 'rel="manifest"'):
        assert tag in html
    assert _tamanho_png(STATIC / "img" / "apple-touch-icon.png") == (180, 180)
    telas = re.findall(r'device-width: (\d+)px\) and \(device-height: (\d+)px\) and \(-webkit-device-pixel-ratio: (\d)\)'
                       r'[^>]*href="/static/(img/splash/[^"?]+)', html)
    assert len(telas) >= 10
    for largura, altura, escala, arquivo in telas:
        assert _tamanho_png(STATIC / arquivo) == (int(largura) * int(escala), int(altura) * int(escala))


def test_tela_sem_internet_e_guardada_pelo_service_worker(client):
    sw = client.get("/service-worker.js").data.decode()
    assert '"/static/offline.html"' in sw and 'mode === "navigate"' in sw
    offline = client.get("/static/offline.html")
    assert offline.status_code == 200 and "Sem conexão com a internet" in offline.data.decode()


def test_app_android_assetlinks_e_apk(client):
    """APK de verdade (TWA gerada pelo PWABuilder, pacote com.tybenson.app):
    o assetlinks.json prova pro Android que o app e deste site (sem ele o app
    abre com barra de endereco) e o APK sai como download do proprio site."""
    links = client.get("/.well-known/assetlinks.json")
    assert links.status_code == 200 and links.mimetype == "application/json"
    alvo = json.loads(links.data)[0]["target"]
    assert alvo["package_name"] == "com.tybenson.app" and len(alvo["sha256_cert_fingerprints"][0]) == 95

    apk = client.get("/app/TyBenson.apk")
    assert apk.status_code == 200 and apk.mimetype == "application/vnd.android.package-archive"
    assert "attachment" in apk.headers["Content-Disposition"] and apk.data[:2] == b"PK"
    apk.close()

    login = client.get("/auth/login").data.decode()
    assert "data-instalar-apk" in login and "/app/TyBenson.apk" in login
    # a chave de assinatura nunca vem pro projeto
    assert not list(STATIC.parent.rglob("*.keystore"))
