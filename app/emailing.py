"""Envio de e-mail via API HTTP da Resend (nao SMTP).

SMTP (portas 25/465/587) e bloqueado por padrao na rede de saida do Render
(e da maioria dos PaaS gratuitos, por seguranca antiabuso) -- toda tentativa
de conexao falhava com OSError(101, "Network is unreachable") antes mesmo
de chegar no Gmail, mesmo com host/porta/credenciais corretos. A API da
Resend usa HTTPS (porta 443, sempre liberada), resolvendo isso na raiz em
vez de tentar contornar um bloqueio de rede que nao depende do nosso codigo.
"""
import requests
from flask import current_app

_URL_RESEND = "https://api.resend.com/emails"
_TIMEOUT_SEGUNDOS = 12


class EmailNaoEnviadoError(Exception):
    """Levantada quando o e-mail nao pode ser enviado (config ausente, API recusou, etc.)."""


def enviar_email(destinatario, assunto, corpo):
    """Envia um e-mail simples em texto puro via API da Resend.

    Levanta EmailNaoEnviadoError em qualquer falha, para o chamador decidir
    como reportar isso ao usuario (nunca deixar subir como 500).
    """
    api_key = current_app.config.get("RESEND_API_KEY")
    remetente = current_app.config.get("RESEND_FROM_EMAIL")

    if not api_key or not remetente:
        raise EmailNaoEnviadoError(
            "Envio de e-mail nao configurado (defina RESEND_API_KEY e "
            "RESEND_FROM_EMAIL no .env)."
        )

    try:
        resposta = requests.post(
            _URL_RESEND,
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "from": remetente,
                "to": [destinatario],
                "subject": assunto,
                "text": corpo,
            },
            timeout=_TIMEOUT_SEGUNDOS,
        )
    except requests.RequestException as erro:
        raise EmailNaoEnviadoError(f"Falha ao enviar e-mail para {destinatario}: {erro}") from erro

    if resposta.status_code >= 400:
        # A Resend devolve o motivo em JSON (ex.: dominio do remetente nao
        # verificado, destinatario invalido) -- repassa isso na mensagem pra
        # nao virar so um "falhou" sem pista nenhuma de causa.
        raise EmailNaoEnviadoError(
            f"Falha ao enviar e-mail para {destinatario}: {resposta.status_code} {resposta.text}"
        )
