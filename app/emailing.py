"""Envio de e-mail via SMTP (sem dependencia extra alem da stdlib)."""
import concurrent.futures
import smtplib
import ssl
from email.message import EmailMessage

from flask import current_app

# Prazo total pro envio (conexao + STARTTLS + login + send). Rodamos o envio numa
# thread a parte e aplicamos esse timeout no future.result(), porque o timeout do
# proprio smtplib.SMTP() nao cobre a resolucao de DNS do MAIL_SERVER (getaddrinfo
# nao tem timeout na stdlib) - um host mal configurado pode travar a chamada
# indefinidamente e derrubar o worker do servidor (gunicorn manda SIGKILL num
# worker travado), virando um 500 pro usuario em vez de um EmailNaoEnviadoError.
_TIMEOUT_SEGUNDOS = 15


class EmailNaoEnviadoError(Exception):
    """Levantada quando o e-mail nao pode ser enviado (config ausente, SMTP recusou, etc.)."""


def _enviar_via_smtp(servidor, porta, usar_tls, usuario, senha, mensagem):
    with smtplib.SMTP(servidor, porta, timeout=10) as smtp:
        if usar_tls:
            smtp.starttls(context=ssl.create_default_context())
        smtp.login(usuario, senha)
        smtp.send_message(mensagem)


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

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    futuro = executor.submit(
        _enviar_via_smtp, servidor, porta, usar_tls, usuario, senha, mensagem
    )
    try:
        futuro.result(timeout=_TIMEOUT_SEGUNDOS)
    except concurrent.futures.TimeoutError as erro:
        raise EmailNaoEnviadoError(
            f"Envio de e-mail para {destinatario} excedeu o tempo limite "
            f"(servidor {servidor}:{porta} nao respondeu em {_TIMEOUT_SEGUNDOS}s)."
        ) from erro
    except (smtplib.SMTPException, OSError) as erro:
        raise EmailNaoEnviadoError(f"Falha ao enviar e-mail para {destinatario}: {erro}") from erro
    finally:
        # wait=False: se a thread ainda estiver presa em getaddrinfo/connect, nao
        # bloqueamos a resposta da request esperando ela terminar - ela morre
        # sozinha (ou fica presa em segundo plano) sem afetar o worker principal.
        executor.shutdown(wait=False)
