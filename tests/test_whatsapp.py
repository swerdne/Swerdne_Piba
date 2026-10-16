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


def test_recusa_da_meta_vai_pro_log_com_o_motivo(app, monkeypatch, caplog):
    """Botao Notificar so conta "falharam" -- o motivo tem que ficar no log."""
    app.config.update(META_WHATSAPP_TOKEN="TOKENFAKE", META_WHATSAPP_PHONE_ID="1234567890")

    class Recusa:
        status_code = 404
        text = '{"error":{"code":132001,"message":"Template name does not exist in the translation"}}'

    monkeypatch.setattr("app.whatsapp.requests.post", lambda *a, **kw: Recusa())
    with app.app_context(), caplog.at_level("WARNING"):
        with pytest.raises(WhatsappNaoEnviadoError):
            enviar_whatsapp_template(destinatario="(28) 99987-2102", nome_template="pibachurch_escalado",
                                     parametros=["Joao", "Vocal", "Culto", "20/10/2026"])

    log = caplog.text
    assert "template pibachurch_escalado" in log and "132001" in log
    assert "5528*****2102" in log and "28999872102" not in log  # numero mascarado


def test_enviar_whatsapp_com_config_mas_telefone_invalido_levanta_erro(app):
    app.config["META_WHATSAPP_TOKEN"] = "TOKENFAKE"
    app.config["META_WHATSAPP_PHONE_ID"] = "1234567890"
    with app.app_context():
        with pytest.raises(WhatsappNaoEnviadoError):
            enviar_whatsapp(destinatario="", corpo="Ola")
