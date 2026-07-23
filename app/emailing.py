"""Envio de e-mail via SMTP (sem dependencia extra alem da stdlib)."""
import smtplib
import ssl
from email.message import EmailMessage

from flask import current_app


class EmailNaoEnviadoError(Exception):
    """Levantada quando o e-mail nao pode ser enviado (config ausente, SMTP recusou, etc.)."""


def enviar_email(destinatario, assunto, corpo):
    """Envia um e-mail simples em texto puro.

    Levanta EmailNaoEnviadoError em qualquer falha, para o chamador decidir
    como reportar isso ao usuario (nunca deixar subir como 500).
    """
    servidor = current_app.config.get("MAIL_SERVER")
    remetente = current_app.config.get("MAIL_DEFAULT_SENDER")
    usuario = current_app.config.get("MAIL_USERNAME")
    senha = current_app.config.get("MAIL_PASSWORD")
    porta = current_app.config.get("MAIL_PORT", 587)
    usar_tls = current_app.config.get("MAIL_USE_TLS", True)

    if not servidor or not remetente or not usuario or not senha:
        raise EmailNaoEnviadoError(
            "Envio de e-mail nao configurado (defina MAIL_SERVER, MAIL_USERNAME, "
            "MAIL_PASSWORD e MAIL_DEFAULT_SENDER no .env)."
        )

    mensagem = EmailMessage()
    mensagem["Subject"] = assunto
    mensagem["From"] = remetente
    mensagem["To"] = destinatario
    mensagem.set_content(corpo)

    try:
        with smtplib.SMTP(servidor, porta, timeout=10) as smtp:
            if usar_tls:
                smtp.starttls(context=ssl.create_default_context())
            smtp.login(usuario, senha)
            smtp.send_message(mensagem)
    except (smtplib.SMTPException, OSError) as erro:
        raise EmailNaoEnviadoError(f"Falha ao enviar e-mail para {destinatario}: {erro}") from erro
