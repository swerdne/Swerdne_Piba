"""Envio de e-mail via API HTTP da Resend (nao SMTP).

SMTP (portas 25/465/587) e bloqueado por padrao na rede de saida do Render
(e da maioria dos PaaS gratuitos, por seguranca antiabuso) -- toda tentativa
de conexao falhava com OSError(101, "Network is unreachable") antes mesmo
de chegar no Gmail, mesmo com host/porta/credenciais corretos. A API da
Resend usa HTTPS (porta 443, sempre liberada), resolvendo isso na raiz em
vez de tentar contornar um bloqueio de rede que nao depende do nosso codigo.
"""
import re
from html import escape

import requests
from flask import current_app

_URL_RESEND = "https://api.resend.com/emails"
_TIMEOUT_SEGUNDOS = 12


class EmailNaoEnviadoError(Exception):
    """Levantada quando o e-mail nao pode ser enviado (config ausente, API recusou, etc.)."""


_URL_NO_TEXTO = re.compile(r"https?://[^\s<]+")


def montar_html(assunto, corpo):
    """Versao HTML do e-mail: cabecalho com a logo e o nome TyBenson (mesma
    marca do login) e o texto da mensagem embaixo. Estilos inline e layout
    em tabela -- e o que os clientes de e-mail (Gmail, Outlook) respeitam.
    O texto vem escapado; links viram clicaveis e quebras de linha, <br>."""
    url_site = current_app.config.get("URL_PUBLICA") or "https://pibaswerdne.me"
    logo = f"{url_site}/static/img/logo-icone.png"
    texto = escape(corpo)
    texto = _URL_NO_TEXTO.sub(lambda m: f'<a href="{m.group(0)}" style="color:#4f46e5;">{m.group(0)}</a>', texto)
    texto = texto.replace("\n", "<br>")
    return f"""<!doctype html>
<html lang="pt-br"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f3f4f6;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f3f4f6;padding:24px 12px;">
<tr><td align="center">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;background:#ffffff;border-radius:16px;overflow:hidden;font-family:Arial,Helvetica,sans-serif;">
<tr><td align="center" style="background:#030917;padding:28px 24px 22px;">
<img src="{logo}" width="84" alt="TyBenson" style="display:block;border:0;width:84px;height:auto;margin:0 auto 10px;">
<div style="font-size:26px;font-weight:800;letter-spacing:-0.5px;color:#ffffff;">Ty<span style="color:#3fa0ee;">Benson</span></div>
<div style="font-size:10px;letter-spacing:3px;color:#9ca3af;margin-top:6px;">PESSOAS &bull; EQUIPES &bull; PROP&Oacute;SITO</div>
</td></tr>
<tr><td style="padding:28px 28px 8px;">
<h1 style="margin:0 0 12px;font-size:19px;line-height:1.3;color:#111827;">{escape(assunto)}</h1>
<p style="margin:0;font-size:15px;line-height:1.6;color:#374151;">{texto}</p>
</td></tr>
<tr><td style="padding:20px 28px 28px;font-size:12px;color:#9ca3af;">
Mensagem autom&aacute;tica do TyBenson &middot; <a href="{url_site}" style="color:#4f46e5;">{url_site.split("//", 1)[-1]}</a>
</td></tr>
</table>
</td></tr>
</table>
</body></html>"""


def enviar_email(destinatario, assunto, corpo):
    """Envia o e-mail via API da Resend: versao HTML com a marca (ver
    montar_html) + o mesmo conteudo em texto puro, pra clientes sem HTML.

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
                "html": montar_html(assunto, corpo),
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
