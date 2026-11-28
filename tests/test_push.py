"""Aviso no celular com o app fechado (app/push.py)."""
import io
import json
import os
from unittest import mock

import pytest
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from py_vapid import Vapid01
from py_vapid.utils import b64urlencode

from app.auth.models import User
from app.notificacoes import Notificacao
from app.push import InscricaoPush

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSCRICAO = {"endpoint": "https://fcm.googleapis.com/fcm/send/abc123",
             "keys": {"p256dh": "BOr3-chave-publica-do-navegador", "auth": "segredo16bytes"}}


@pytest.fixture
def com_chaves(app):
    vapid = Vapid01()
    vapid.generate_keys()
    app.config["VAPID_PRIVATE_KEY"] = b64urlencode(vapid.private_key.private_numbers().private_value.to_bytes(32, "big"))
    app.config["VAPID_PUBLIC_KEY"] = b64urlencode(vapid.public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint))
    yield app
    app.config["VAPID_PRIVATE_KEY"] = app.config["VAPID_PUBLIC_KEY"] = None


def _inscrever(cliente):
    return cliente.post("/push/inscrever", data={"inscricao": json.dumps(INSCRICAO)})


def test_sem_chaves_fica_desligado(logged_in_client, app, db):
    with app.app_context():
        assert "data-push-chave" not in logged_in_client.get("/dashboard").get_data(as_text=True)
        assert _inscrever(logged_in_client).status_code == 400
        assert InscricaoPush.objects.count() == 0


def test_inscrever_e_receber_aviso_do_sino(logged_in_client, com_chaves, db):
    app = com_chaves
    with app.app_context():
        html = logged_in_client.get("/dashboard").get_data(as_text=True)
        assert f'data-push-chave="{app.config["VAPID_PUBLIC_KEY"]}"' in html
        assert _inscrever(logged_in_client).get_json()["ok"] is True
        ana = User.objects(email="ana@example.com").first()
        assert InscricaoPush.objects(usuario_id=ana.id).count() == 1
        _inscrever(logged_in_client)  # o mesmo aparelho de novo nao duplica
        assert InscricaoPush.objects.count() == 1

        with mock.patch("pywebpush.webpush") as webpush:
            Notificacao(usuario_id=ana.id, titulo="Você foi escalado(a)", mensagem="Culto de domingo", escala_id=7).save()
        webpush.assert_called_once()
        args = webpush.call_args.kwargs
        carga = json.loads(args["data"])
        assert carga == {"titulo": "Você foi escalado(a)", "corpo": "Culto de domingo", "url": "/escala/7"}
        assert args["subscription_info"]["endpoint"] == INSCRICAO["endpoint"]
        assert args["vapid_private_key"] == app.config["VAPID_PRIVATE_KEY"]


def test_aparelho_que_saiu_e_apagado(logged_in_client, com_chaves, db):
    from pywebpush import WebPushException

    with com_chaves.app_context():
        _inscrever(logged_in_client)
        ana = User.objects(email="ana@example.com").first()
        resposta = mock.Mock(status_code=410)
        with mock.patch("pywebpush.webpush", side_effect=WebPushException("gone", response=resposta)):
            Notificacao(usuario_id=ana.id, titulo="Aviso", mensagem="x").save()
        assert InscricaoPush.objects.count() == 0


def test_testar_e_cancelar(logged_in_client, com_chaves, db):
    with com_chaves.app_context():
        _inscrever(logged_in_client)
        with mock.patch("pywebpush.webpush") as webpush:
            assert logged_in_client.post("/push/testar").get_json() == {"ok": True, "aparelhos": 1}
        assert json.loads(webpush.call_args.kwargs["data"])["titulo"] == "Avisos ligados!"
        logged_in_client.post("/push/cancelar", data={"endpoint": INSCRICAO["endpoint"]})
        assert InscricaoPush.objects.count() == 0


def test_inscricao_invalida_e_recusada(logged_in_client, com_chaves, db):
    with com_chaves.app_context():
        for ruim in ("nao e json", json.dumps({"endpoint": "http://inseguro"}), json.dumps({"keys": {}})):
            resposta = logged_in_client.post("/push/inscrever", data={"inscricao": ruim})
            assert resposta.status_code == 400 or resposta.get_json()["ok"] is False
        assert InscricaoPush.objects.count() == 0


def test_service_worker_mostra_e_abre_o_aviso():
    sw = io.open(os.path.join(RAIZ, "app", "static", "js", "service-worker.js"), encoding="utf-8").read()
    assert 'addEventListener("push"' in sw and "showNotification" in sw and "notificationclick" in sw
