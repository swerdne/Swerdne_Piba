"""Testes do modulo whatsapp (app/whatsapp.py, Meta Cloud API)."""
import pytest

from app.whatsapp import enviar_whatsapp, enviar_whatsapp_template, WhatsappNaoEnviadoError


def test_enviar_whatsapp_sem_config_levanta_erro(app):
    with app.app_context():
        with pytest.raises(WhatsappNaoEnviadoError):
            enviar_whatsapp(destinatario="11999998888", corpo="Ola")


def test_enviar_whatsapp_template_sem_config_levanta_erro(app):
    with app.app_context():
        with pytest.raises(WhatsappNaoEnviadoError):
            enviar_whatsapp_template(destinatario="11999998888", nome_template="pibachurch_escalado", parametros=["Joao"])


def test_enviar_whatsapp_com_config_mas_telefone_invalido_levanta_erro(app):
    app.config["META_WHATSAPP_TOKEN"] = "TOKENFAKE"
    app.config["META_WHATSAPP_PHONE_ID"] = "1234567890"
    with app.app_context():
        with pytest.raises(WhatsappNaoEnviadoError):
            enviar_whatsapp(destinatario="", corpo="Ola")
