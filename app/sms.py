"""Envio de SMS via Twilio."""
from flask import current_app
from twilio.base.exceptions import TwilioException
from twilio.rest import Client


class SmsNaoEnviadoError(Exception):
    """Levantada quando o SMS nao pode ser enviado (config ausente, Twilio recusou, etc.)."""


def normalizar_telefone(numero):
    """Converte um telefone digitado livremente para o formato E.164 (+55...).

    Assume Brasil quando o numero nao vem com codigo de pais (sem "+").
    Retorna None se nao sobrar nenhum digito.
    """
    if not numero:
        return None

    apenas_digitos = "".join(c for c in numero if c.isdigit())
    if not apenas_digitos:
        return None

    if numero.strip().startswith("+"):
        return "+" + apenas_digitos

    return "+55" + apenas_digitos


def enviar_sms(destinatario, corpo):
    """Envia um SMS simples via Twilio.

    Levanta SmsNaoEnviadoError em qualquer falha, para o chamador decidir
    como reportar isso ao usuario (nunca deixar subir como 500).
    """
    account_sid = current_app.config.get("TWILIO_ACCOUNT_SID")
    auth_token = current_app.config.get("TWILIO_AUTH_TOKEN")
    numero_remetente = current_app.config.get("TWILIO_FROM_NUMBER")

    if not account_sid or not auth_token or not numero_remetente:
        raise SmsNaoEnviadoError(
            "Envio de SMS nao configurado (defina TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN "
            "e TWILIO_FROM_NUMBER no .env)."
        )

    numero_destino = normalizar_telefone(destinatario)
    if numero_destino is None:
        raise SmsNaoEnviadoError(f"Telefone invalido: {destinatario!r}")

    try:
        client = Client(account_sid, auth_token)
        client.messages.create(to=numero_destino, from_=numero_remetente, body=corpo)
    except TwilioException as erro:
        raise SmsNaoEnviadoError(f"Falha ao enviar SMS para {numero_destino}: {erro}") from erro
