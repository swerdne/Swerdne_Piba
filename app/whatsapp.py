"""Envio de WhatsApp via Meta Cloud API (WhatsApp Business Platform).

Conta gratuita em developers.facebook.com -- camada gratuita generosa (sem
custo pro volume de uma igreja), diferente do Twilio, que so deixa criar
Templates de mensagem proativa em conta paga. Precisa de META_WHATSAPP_TOKEN
(token de acesso do app) e META_WHATSAPP_PHONE_ID (id do numero configurado
no WhatsApp Business) no .env.
"""
import requests
from flask import current_app

from app.sms import normalizar_telefone

# Mesmo raciocinio do timeout em app/emailing.py e app/sms.py.
_TIMEOUT_SEGUNDOS = 12
_API_VERSAO = "v21.0"


class WhatsappNaoEnviadoError(Exception):
    """Levantada quando a mensagem de WhatsApp nao pode ser enviada (config ausente, Meta recusou, etc.)."""


def _config_ou_erro():
    token = current_app.config.get("META_WHATSAPP_TOKEN")
    phone_id = current_app.config.get("META_WHATSAPP_PHONE_ID")
    if not token or not phone_id:
        raise WhatsappNaoEnviadoError(
            "Envio de WhatsApp nao configurado (defina META_WHATSAPP_TOKEN e "
            "META_WHATSAPP_PHONE_ID no .env)."
        )
    return token, phone_id


def _chamar_api(token, phone_id, payload):
    url = f"https://graph.facebook.com/{_API_VERSAO}/{phone_id}/messages"
    try:
        resposta = requests.post(
            url,
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
            timeout=_TIMEOUT_SEGUNDOS,
        )
    except requests.RequestException as erro:
        raise WhatsappNaoEnviadoError(f"Falha ao enviar WhatsApp: {erro}") from erro

    if resposta.status_code >= 300:
        raise WhatsappNaoEnviadoError(f"Meta recusou o envio: {resposta.status_code} {resposta.text}")


def enviar_whatsapp(destinatario, corpo):
    """Envia uma mensagem de WhatsApp de texto livre.

    So funciona dentro da janela de 24h de atendimento (a pessoa precisa ter
    mandado mensagem pro numero antes) -- pra notificacao PROATIVA (a igreja
    avisando sem a pessoa ter escrito antes, que e o caso das notificacoes de
    escala), use enviar_whatsapp_template, que usa um Template aprovado pela
    Meta (regra da propria plataforma WhatsApp, nao e limitacao nossa).

    Levanta WhatsappNaoEnviadoError em qualquer falha.
    """
    token, phone_id = _config_ou_erro()

    numero_destino = normalizar_telefone(destinatario)
    if numero_destino is None:
        raise WhatsappNaoEnviadoError(f"Telefone invalido: {destinatario!r}")

    _chamar_api(token, phone_id, {
        "messaging_product": "whatsapp",
        "to": numero_destino.lstrip("+"),
        "type": "text",
        "text": {"body": corpo},
    })


def enviar_whatsapp_template(destinatario, nome_template, parametros):
    """Envia uma mensagem via Template aprovado pela Meta -- unico jeito de
    mandar WhatsApp PROATIVO (fora da janela de 24h), ver
    app/escala/routes.py::enviar_notificacoes_da_escala e afins.

    `parametros` e uma lista de strings, na ordem das variaveis {{1}},
    {{2}}... do corpo do template cadastrado no WhatsApp Manager.
    """
    token, phone_id = _config_ou_erro()

    numero_destino = normalizar_telefone(destinatario)
    if numero_destino is None:
        raise WhatsappNaoEnviadoError(f"Telefone invalido: {destinatario!r}")

    _chamar_api(token, phone_id, {
        "messaging_product": "whatsapp",
        "to": numero_destino.lstrip("+"),
        "type": "template",
        "template": {
            "name": nome_template,
            "language": {"code": "pt_BR"},
            "components": [{
                "type": "body",
                "parameters": [{"type": "text", "text": p} for p in parametros],
            }],
        },
    })
