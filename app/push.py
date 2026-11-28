"""Aviso no celular com o app fechado (Web Push).

Tudo o que cai no sino (Notificacao) vira tambem uma notificacao do
celular/computador de quem ativou em Perfil > "Ativar avisos no celular".
- Android: Chrome ou o app instalado. iPhone: so com o app instalado na
  tela de inicio (iOS 16.4+), regra da Apple.
- Chaves VAPID nas configuracoes do servidor (VAPID_PUBLIC_KEY,
  VAPID_PRIVATE_KEY, VAPID_EMAIL). Sem elas o recurso fica desligado: o
  botao nem aparece e nada e enviado.
- O envio roda numa thread (nao atrasa quem criou a notificacao).
  Inscricao que o servico do navegador diz que morreu (404/410) e apagada.
"""
import json
import logging
import threading
from datetime import datetime, timezone

import mongoengine

from app.db_utils import SequentialIdDocument

logger = logging.getLogger(__name__)


class InscricaoPush(SequentialIdDocument):
    """Um aparelho (navegador) que aceitou receber avisos."""

    meta = {"collection": "inscricoes_push", "indexes": ["usuario_id"]}
    _nome_sequencia = "inscricoes_push"

    usuario_id = mongoengine.IntField(required=True)
    endpoint = mongoengine.StringField(required=True, unique=True, max_length=1000)
    p256dh = mongoengine.StringField(required=True, max_length=200)
    auth = mongoengine.StringField(required=True, max_length=100)
    criada_em = mongoengine.DateTimeField(default=lambda: datetime.now(timezone.utc))


def chave_publica(app):
    return app.config.get("VAPID_PUBLIC_KEY") or None


def ativo(app):
    return bool(app.config.get("VAPID_PUBLIC_KEY") and app.config.get("VAPID_PRIVATE_KEY"))


def inscrever(usuario_id, dados):
    """Guarda (ou move pra esta conta) a inscricao do navegador. Devolve True se valida."""
    try:
        endpoint = dados["endpoint"]
        chaves = dados["keys"]
        p256dh, auth = chaves["p256dh"], chaves["auth"]
    except (KeyError, TypeError):
        return False
    if not (isinstance(endpoint, str) and endpoint.startswith("https://") and len(endpoint) <= 1000):
        return False
    existente = InscricaoPush.objects(endpoint=endpoint).first()
    if existente:
        existente.usuario_id, existente.p256dh, existente.auth = usuario_id, p256dh, auth
        existente.save()
    else:
        InscricaoPush(usuario_id=usuario_id, endpoint=endpoint, p256dh=p256dh, auth=auth).save()
    return True


def cancelar(usuario_id, endpoint):
    InscricaoPush.objects(usuario_id=usuario_id, endpoint=endpoint).delete()


def _enviar_agora(app, inscricoes, carga):
    from pywebpush import WebPushException, webpush

    chave = app.config.get("VAPID_PRIVATE_KEY")
    contato = app.config.get("VAPID_EMAIL") or "mailto:notificacoes@pibaswerdne.me"
    for inscricao in inscricoes:
        try:
            webpush(
                subscription_info={"endpoint": inscricao.endpoint,
                                   "keys": {"p256dh": inscricao.p256dh, "auth": inscricao.auth}},
                data=json.dumps(carga, ensure_ascii=False),
                vapid_private_key=chave,
                vapid_claims={"sub": contato},
                ttl=24 * 3600,
                timeout=10,
            )
        except WebPushException as erro:
            status = getattr(getattr(erro, "response", None), "status_code", None)
            if status in (404, 410):
                inscricao.delete()  # aparelho desinstalou/negou: nao tenta mais
            else:
                logger.warning("Push nao saiu (%s): %s", status, erro)
        except Exception:
            logger.exception("Push falhou")


def enviar_para_usuario(app, usuario_id, titulo, corpo, url="/dashboard"):
    """Manda pra todos os aparelhos da conta, em segundo plano."""
    if not ativo(app):
        return 0
    inscricoes = list(InscricaoPush.objects(usuario_id=usuario_id))
    if not inscricoes:
        return 0
    carga = {"titulo": (titulo or "TyBenson")[:120], "corpo": (corpo or "")[:240], "url": url or "/dashboard"}
    if app.testing:
        _enviar_agora(app, inscricoes, carga)
    else:
        threading.Thread(target=_enviar_agora, args=(app, inscricoes, carga), daemon=True).start()
    return len(inscricoes)


def _apos_salvar_notificacao(sender, document, created=False, **kwargs):
    """Notificacao nova no sino -> push (se a conta ativou)."""
    if not created:
        return
    from flask import current_app

    try:
        app = current_app._get_current_object()
    except RuntimeError:
        return  # fora de app context (script solto): sem push
    if not ativo(app):
        return
    url = document.link or (f"/escala/{document.escala_id}" if document.escala_id else "/dashboard#avisos")
    try:
        enviar_para_usuario(app, document.usuario_id, document.titulo, document.mensagem, url)
    except Exception:
        logger.exception("Push da notificacao %s falhou", document.id)


def registrar():
    """Liga o push nas notificacoes (chamado uma vez pela Application Factory)."""
    from app.notificacoes import Notificacao

    mongoengine.signals.post_save.connect(_apos_salvar_notificacao, sender=Notificacao)
