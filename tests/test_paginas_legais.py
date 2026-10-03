"""Paginas publicas exigidas pela Meta (app do WhatsApp): sem login."""
import pytest


@pytest.mark.parametrize("url,titulo", [
    ("/privacidade", "Política de Privacidade"),
    ("/termos", "Termos de Uso"),
    ("/exclusao-de-dados", "Exclusão de dados"),
])
def test_paginas_legais_abrem_sem_login(client, url, titulo):
    resposta = client.get(url)
    assert resposta.status_code == 200
    html = resposta.data.decode("utf-8")
    assert titulo in html and "Contato" in html


def test_privacidade_explica_localizacao_e_servicos(client):
    html = client.get("/privacidade").data.decode("utf-8")
    assert "nunca as suas coordenadas" in html
    for servico in ("Azure", "MongoDB", "Resend", "Twilio", "WhatsApp", "Google", "OpenStreetMap"):
        assert servico in html


def test_email_de_contato_configuravel(app, client):
    app.config["EMAIL_CONTATO"] = "contato@exemplo.com"
    html = client.get("/exclusao-de-dados").data.decode("utf-8")
    assert "mailto:contato@exemplo.com" in html


def test_cadastro_e_login_linkam_as_paginas(client):
    assert "/termos" in client.get("/auth/register").data.decode("utf-8")
    assert "/privacidade" in client.get("/auth/login").data.decode("utf-8")
