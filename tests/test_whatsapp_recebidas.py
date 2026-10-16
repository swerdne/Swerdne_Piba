"""Webhook do WhatsApp: verificacao, assinatura, confirmar/recusar escala
pela resposta e caixa de entrada da comunidade."""
import hashlib
import hmac
import json
from datetime import date, timedelta

import pytest

from app.comunidade.models import Comunidade
from app.escala.models import Escala, Funcao, Membro, RegistroTroca
from app.ministerio.models import Ministerio
from app.notificacoes import Notificacao
from app.whatsapp_recebidas import MensagemWhatsapp, chave_do_telefone, interpretar_resposta
from tests.conftest import sessao_isolada

SEGREDO = "segredo-de-teste"


@pytest.fixture
def enviados(app, monkeypatch):
    """Troca o envio real por uma lista (telefone, texto)."""
    lista = []
    app.config.update(META_APP_SECRET=SEGREDO, META_WHATSAPP_VERIFY_TOKEN="token-verif")
    monkeypatch.setattr("app.whatsapp.enviar_whatsapp", lambda destino, corpo: lista.append((destino, corpo)))
    return lista


def _igreja(cliente, telefone="(11) 98765-4321"):
    cliente.post("/comunidade/nova", data={"nome": "Igreja", "descricao": ""})
    comunidade = Comunidade.objects(nome="Igreja").order_by("-id").first()
    cliente.post(f"/ministerio/comunidade/{comunidade.id}/nova", data={"nome": "Louvor", "descricao": ""})
    ministerio = Ministerio.objects(nome="Louvor", comunidade_id=comunidade.id).first()
    membro = Membro(comunidade_id=comunidade.id, nome="Ana", telefone=telefone).save()
    return comunidade, ministerio, membro


def _escala(ministerio, membro, dias=2, nome="Culto", funcoes=("Vocal",), **campos):
    escala = Escala(ministerio_id=ministerio.id, nome=nome, departamento="Louvor",
                    data=date.today() + timedelta(days=dias), **campos).save()
    for i, f in enumerate(funcoes):
        Funcao(escala_id=escala.id, nome=f, ordem=i, membro_id=membro.id, status="nao_notificado").save()
    return escala


def _payload(texto, de="5511987654321", wamid="wamid.1", nome="Ana WhatsApp"):
    return {"entry": [{"changes": [{"value": {
        "contacts": [{"wa_id": de, "profile": {"name": nome}}],
        "messages": [{"from": de, "id": wamid, "type": "text", "text": {"body": texto}}],
    }}]}]}


def _postar(cliente, payload, segredo=SEGREDO):
    corpo = json.dumps(payload).encode()
    assinatura = "sha256=" + hmac.new(segredo.encode(), corpo, hashlib.sha256).hexdigest()
    return cliente.post("/whatsapp/webhook", data=corpo, content_type="application/json",
                        headers={"X-Hub-Signature-256": assinatura})


# --- Pecas soltas -----------------------------------------------------------------------

@pytest.mark.parametrize("texto,esperado", [
    ("Confirmo", "confirmar"), ("sim", "confirmar"), ("OK!", "confirmar"), ("👍", "confirmar"),
    ("estarei la, pode contar", "confirmar"), ("Não posso", "recusar"), ("nao", "recusar"),
    ("sim, mas não vou conseguir... não posso", "recusar"), ("nao vou", "recusar"),
    ("qual o horario do ensaio?", None), ("ok, mas que horas?", None), ("", None),
])
def test_interpretar_resposta(texto, esperado):
    assert interpretar_resposta(texto) == esperado


def test_chave_do_telefone_ignora_formato_e_o_nove():
    chave = chave_do_telefone("(11) 98765-4321")
    for outro in ("+55 11 98765-4321", "11987654321", "+551187654321", "5511987654321", "011 98765-4321"):
        assert chave_do_telefone(outro) == chave
    assert chave_do_telefone("98765-4321") is None  # sem DDD
    assert chave_do_telefone("(21) 98765-4321") != chave


# --- Webhook ---------------------------------------------------------------------------------

def test_verificacao_do_webhook(client, enviados):
    ok = client.get("/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=token-verif&hub.challenge=123")
    assert ok.status_code == 200 and ok.data == b"123"
    errado = client.get("/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=outro&hub.challenge=123")
    assert errado.status_code == 403


def test_post_sem_assinatura_valida_e_recusado(client, enviados, app):
    with app.app_context():
        assert _postar(client, _payload("Confirmo"), segredo="errado").status_code == 403
        assert client.post("/whatsapp/webhook", json=_payload("Confirmo")).status_code == 403
        app.config["META_APP_SECRET"] = None
        assert _postar(client, _payload("Confirmo")).status_code == 403
        assert MensagemWhatsapp.objects.count() == 0


def test_confirmo_confirma_a_proxima_escala_e_avisa_lideres(logged_in_client, enviados, app, db):
    with app.app_context():
        _, ministerio, membro = _igreja(logged_in_client)
        proxima = _escala(ministerio, membro, dias=1, funcoes=("Vocal", "Violao"))
        depois = _escala(ministerio, membro, dias=9, nome="Outro culto")
        _escala(ministerio, membro, dias=-3, nome="Passado")

        # O WhatsApp entrega sem o 9; o diretorio tem com 9 e formatado.
        assert _postar(logged_in_client, _payload("Confirmo!", de="551187654321")).status_code == 200

        assert {f.status for f in Funcao.objects(escala_id=proxima.id)} == {"confirmado"}
        assert {f.status for f in Funcao.objects(escala_id=depois.id)} == {"nao_notificado"}
        assert Notificacao.objects(escala_id=proxima.id, tipo="confirmado").count() == 2
        assert len(enviados) == 1 and enviados[0][0] == "+551187654321"
        assert "Confirmado" in enviados[0][1] and "Vocal, Violao" in enviados[0][1]
        recebida = MensagemWhatsapp.objects(direcao="recebida").first()
        assert (recebida.acao, recebida.escala_id, recebida.lida) == ("confirmado", proxima.id, True)
        assert MensagemWhatsapp.objects(direcao="enviada").count() == 1

        # Mesmo webhook reenviado pela Meta: ignorado.
        _postar(logged_in_client, _payload("Confirmo!", de="551187654321"))
        assert len(enviados) == 1 and MensagemWhatsapp.objects(direcao="recebida").count() == 1


def test_nao_posso_pede_troca_com_a_mensagem_como_motivo(logged_in_client, enviados, app, db):
    with app.app_context():
        _, ministerio, membro = _igreja(logged_in_client)
        escala = _escala(ministerio, membro)
        _postar(logged_in_client, _payload("Não posso, vou viajar"))
        funcao = Funcao.objects(escala_id=escala.id).first()
        assert funcao.status == "troca_solicitada"
        assert "vou viajar" in funcao.troca_motivo
        assert RegistroTroca.objects(escala_id=escala.id).count() == 1
        assert Notificacao.objects(escala_id=escala.id, tipo="troca_solicitada").count() == 1
        assert "não pode" in enviados[0][1]


def test_escala_cancelada_e_presente_nao_mudam(logged_in_client, enviados, app, db):
    with app.app_context():
        _, ministerio, membro = _igreja(logged_in_client)
        _escala(ministerio, membro, dias=1, nome="Cancelada", cancelada=True)
        escala = _escala(ministerio, membro, dias=2)
        Funcao.objects(escala_id=escala.id).update(set__status="presente")
        _postar(logged_in_client, _payload("confirmo"))
        assert Funcao.objects(escala_id=escala.id).first().status == "presente"
        assert "já está registrada" in enviados[0][1]


def test_texto_qualquer_vai_pra_caixa_de_entrada_sem_resposta_automatica(logged_in_client, enviados, app, db):
    with app.app_context():
        comunidade, ministerio, membro = _igreja(logged_in_client)
        escala = _escala(ministerio, membro)
        _postar(logged_in_client, _payload("Que horas é o ensaio?"))
        assert enviados == []
        assert Funcao.objects(escala_id=escala.id).first().status == "nao_notificado"
        msg = MensagemWhatsapp.objects.first()
        assert (msg.lida, msg.comunidade_ids, msg.membro_ids) == (False, [comunidade.id], [membro.id])
        assert "1 nova(s)" in logged_in_client.get(f"/comunidade/{comunidade.id}").data.decode()


def test_telefone_desconhecido_recebe_aviso_uma_vez_e_nao_aparece_em_comunidade(logged_in_client, enviados, app, db):
    with app.app_context():
        comunidade, _, _ = _igreja(logged_in_client)
        _postar(logged_in_client, _payload("confirmo", de="5521999990000"))
        assert len(enviados) == 1 and enviados[0][0] == "+5521999990000"
        assert "não está cadastrado" in enviados[0][1]
        assert MensagemWhatsapp.objects(direcao="recebida").first().comunidade_ids == []
        assert "nova(s)" not in logged_in_client.get(f"/comunidade/{comunidade.id}").data.decode()

        # Segunda mensagem no mesmo dia: sem aviso repetido.
        _postar(logged_in_client, _payload("teste", de="5521999990000", wamid="wamid.2"))
        assert len(enviados) == 1


def test_webhook_so_com_status_de_entrega_nao_grava_nada(logged_in_client, enviados, app, db):
    with app.app_context():
        payload = {"entry": [{"changes": [{"field": "messages", "value": {"statuses": [
            {"id": "wamid.x", "status": "failed", "recipient_id": "5511987654321",
             "errors": [{"code": 131030, "title": "Recipient phone number not in allowed list"}]},
        ]}}]}]}
        assert _postar(logged_in_client, payload).status_code == 200
        assert MensagemWhatsapp.objects.count() == 0 and enviados == []


# --- Caixa de entrada -------------------------------------------------------------------------------

def test_caixa_de_entrada_lista_abre_e_responde(logged_in_client, enviados, app, db):
    with app.app_context():
        comunidade, ministerio, membro = _igreja(logged_in_client)
        _postar(logged_in_client, _payload("Que horas é o ensaio?"))
        lista = logged_in_client.get(f"/comunidade/{comunidade.id}/whatsapp").data.decode()
        assert "Ana" in lista and "Que horas" in lista

        url = f"/comunidade/{comunidade.id}/whatsapp/5511987654321"
        assert "Enviar pelo WhatsApp" in logged_in_client.get(url).data.decode()
        assert MensagemWhatsapp.objects(lida=False).count() == 0  # abriu = lida

        logged_in_client.post(url, data={"texto": "As 19h!"})
        assert enviados == [("+5511987654321", "As 19h!")]
        enviada = MensagemWhatsapp.objects(direcao="enviada").first()
        assert (enviada.texto, enviada.comunidade_ids) == ("As 19h!", [comunidade.id])


def test_resposta_fora_da_janela_de_24h_e_bloqueada(logged_in_client, enviados, app, db):
    from datetime import datetime, timezone

    with app.app_context():
        comunidade, _, _ = _igreja(logged_in_client)
        _postar(logged_in_client, _payload("Oi"))
        MensagemWhatsapp.objects.update(set__criada_em=datetime.now(timezone.utc) - timedelta(hours=25))
        url = f"/comunidade/{comunidade.id}/whatsapp/5511987654321"
        assert "Já passaram 24h" in logged_in_client.get(url).data.decode()
        logged_in_client.post(url, data={"texto": "Oi!"})
        assert enviados == []


def test_caixa_de_entrada_so_para_admin_da_comunidade(logged_in_client, outro_logged_in_client, enviados, app, db):
    with sessao_isolada(app):
        comunidade, _, _ = _igreja(logged_in_client)
        cid = comunidade.id
        _postar(logged_in_client, _payload("Oi"))
    with sessao_isolada(app):
        assert outro_logged_in_client.get(f"/comunidade/{cid}/whatsapp").status_code == 404
        assert outro_logged_in_client.post(f"/comunidade/{cid}/whatsapp/5511987654321",
                                           data={"texto": "x"}).status_code == 404
        assert enviados == []
