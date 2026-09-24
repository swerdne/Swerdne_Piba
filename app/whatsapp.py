"""Envio de WhatsApp via Twilio.

Mesma conta/credenciais do SMS (app/sms.py) -- o Twilio manda WhatsApp com a
mesma API de mensagens, so que com o remetente e o destinatario prefixados
com "whatsapp:". Precisa habilitar o canal WhatsApp no Twilio (sandbox pra
testar, numero de WhatsApp Business verificado pra producao) e configurar
TWILIO_WHATSAPP_FROM no .env.
"""
from flask import current_app
from twilio.base.exceptions import TwilioException
from twilio.http.http_client import TwilioHttpClient
from twilio.rest import Client

from app.sms import normalizar_telefone

# Mesmo raciocinio do timeout em app/emailing.py e app/sms.py -- sem isso, o
# cliente HTTP do Twilio nao tem timeout nenhum por padrao.
_TIMEOUT_SEGUNDOS = 12


class WhatsappNaoEnviadoError(Exception):
    """Levantada quando a mensagem de WhatsApp nao pode ser enviada (config ausente, Twilio recusou, etc.)."""


def enviar_whatsapp(destinatario, corpo):
    """Envia uma mensagem de WhatsApp via Twilio.

    Levanta WhatsappNaoEnviadoError em qualquer falha, para o chamador
    decidir como reportar isso ao usuario (nunca deixar subir como 500).
    """
    account_sid = current_app.config.get("TWILIO_ACCOUNT_SID")
    auth_token = current_app.config.get("TWILIO_AUTH_TOKEN")
    numero_remetente = current_app.config.get("TWILIO_WHATSAPP_FROM")

    if not account_sid or not auth_token or not numero_remetente:
        raise WhatsappNaoEnviadoError(
            "Envio de WhatsApp nao configurado (defina TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN "
            "e TWILIO_WHATSAPP_FROM no .env)."
        )

    numero_destino = normalizar_telefone(destinatario)
    if numero_destino is None:
        raise WhatsappNaoEnviadoError(f"Telefone invalido: {destinatario!r}")

    try:
        client = Client(account_sid, auth_token, http_client=TwilioHttpClient(timeout=_TIMEOUT_SEGUNDOS))
        client.messages.create(
            to=f"whatsapp:{numero_destino}",
            from_=f"whatsapp:{numero_remetente}",
            body=corpo,
        )
    except (TwilioException, OSError) as erro:
        # OSError cobre timeout/erro de conexao do requests (usado por baixo do
        # cliente HTTP do Twilio) -- mesmo motivo do try/except em app/sms.py.
        raise WhatsappNaoEnviadoError(f"Falha ao enviar WhatsApp para {numero_destino}: {erro}") from erro
