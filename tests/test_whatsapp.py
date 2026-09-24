"""Testes do modulo whatsapp (app/whatsapp.py)."""
import pytest

from app.whatsapp import enviar_whatsapp, WhatsappNaoEnviadoError


def test_enviar_whatsapp_sem_config_levanta_erro(app):
    with app.app_context():
        with pytest.raises(WhatsappNaoEnviadoError):
            enviar_whatsapp(destinatario="11999998888", corpo="Ola")


def test_enviar_whatsapp_com_config_mas_telefone_invalido_levanta_erro(app):
    app.config["TWILIO_ACCOUNT_SID"] = "SIDFAKE"
    app.config["TWILIO_AUTH_TOKEN"] = "TOKENFAKE"
    app.config["TWILIO_WHATSAPP_FROM"] = "+14155238886"
    with app.app_context():
        with pytest.raises(WhatsappNaoEnviadoError):
            enviar_whatsapp(destinatario="", corpo="Ola")
