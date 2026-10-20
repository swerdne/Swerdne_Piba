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


@pytest.mark.parametrize("texto,esperado", [
    # Confirmacao, inclusive texto livre
    ("Confirmo", "confirmar"), ("pode contar comigo!", "confirmar"), ("Beleza", "confirmar"),
    ("ok, valeu", "confirmar"), ("Sim, obrigada pastor", "confirmar"), ("tô dentro", "confirmar"),
    ("vou sim", "confirmar"), ("Com certeza, estarei lá", "confirmar"), ("tá bom", "confirmar"), ("✅", "confirmar"),
    # Recusa
    ("não vou conseguir ir", "recusar"), ("Não dá", "recusar"), ("infelizmente não", "recusar"),
    ("Estou doente", "recusar"), ("vou estar viajando", "recusar"), ("não, obrigado", "recusar"),
    ("nao vai rolar", "recusar"),
    # Troca
    ("preciso trocar", "troca"), ("Quem pode me substituir?", "troca"),
    ("alguém pode ir no meu lugar?", "troca"), ("não posso, pode trocar com alguém?", "troca"),
    # Perguntas
    ("qual minha próxima escala?", "consulta_escala"), ("Quando é meu culto?", "consulta_escala"),
    ("estou escalado pra quando?", "consulta_escala"), ("que dia eu toco?", "consulta_escala"),
    ("Qual o endereço da igreja?", "endereco"), ("onde fica?", "endereco"), ("Local da igreja.", "endereco"),
    ("que horas é o culto?", "horarios"), ("qual o horário da igreja", "horarios"),
    ("quais as músicas do culto?", "repertorio"), ("repertório de domingo", "repertorio"),
    ("me manda a cifra", "repertorio"), ("qual a música de domingo?", "repertorio"),
    ("quais os louvores?", "repertorio"),
    ("vou estudar as músicas, pode contar comigo", "confirmar"),
    ("não vou conseguir tocar as músicas", "recusar"),
    # Ambiguas: na duvida, caixa de entrada (None) -- nunca confirma/recusa por engano
    ("não confirmo ainda", None), ("acho que vou", None), ("talvez eu não consiga", None),
    ("confirmo depois", None), ("vou ver e te aviso", None), ("não vou faltar!", None),
    ("não posso perder esse culto", None), ("ok, mas que horas?", None), ("posso confirmar amanhã?", None),
    ("Amém 🙏", None), ("que horas?", None),
    # Menu de comandos
    ("menu", "ajuda"), ("Ajuda", "ajuda"), ("bom dia", "ajuda"), ("oi, tudo bem?", "ajuda"), ("?", "ajuda"),
    ("o que você faz?", "ajuda"), ("quais são os comandos?", "ajuda"),
    ("ajuda, preciso trocar", "troca"), ("bom dia, confirmo", "confirmar"),
    ("3", "consulta_escala"), ("4", "repertorio"), ("5", "endereco"), ("6", "horarios"),
    ("1", "confirmar"), ("2", "recusar"),
    ("vou levar meu violão", None), ("sim mas preciso falar com o pastor", None),
])
def test_interpretar_mensagem(texto, esperado):
    from app.whatsapp_recebidas import interpretar_mensagem

    assert interpretar_mensagem(texto) == esperado


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
        assert "Presença confirmada" in enviados[0][1] and "Vocal, Violao" in enviados[0][1]
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
        assert "avisamos a liderança" in enviados[0][1]


def test_escala_cancelada_e_presente_nao_mudam(logged_in_client, enviados, app, db):
    with app.app_context():
        _, ministerio, membro = _igreja(logged_in_client)
        _escala(ministerio, membro, dias=1, nome="Cancelada", cancelada=True)
        escala = _escala(ministerio, membro, dias=2)
        Funcao.objects(escala_id=escala.id).update(set__status="presente")
        _postar(logged_in_client, _payload("confirmo"))
        assert Funcao.objects(escala_id=escala.id).first().status == "presente"
        assert "já está registrada" in enviados[0][1]


def test_preciso_trocar_pede_troca_com_resposta_propria(logged_in_client, enviados, app, db):
    with app.app_context():
        _, ministerio, membro = _igreja(logged_in_client)
        escala = _escala(ministerio, membro)
        _postar(logged_in_client, _payload("Preciso trocar, alguém pode me substituir?"))
        funcao = Funcao.objects(escala_id=escala.id).first()
        assert funcao.status == "troca_solicitada" and "substituir" in funcao.troca_motivo
        assert Notificacao.objects(escala_id=escala.id, tipo="troca_solicitada").count() == 1
        assert "Pedido de troca registrado" in enviados[0][1]
        assert MensagemWhatsapp.objects(direcao="recebida").first().acao == "troca_solicitada"


def test_pergunta_da_proxima_escala_responde_sem_mudar_nada(logged_in_client, enviados, app, db):
    with app.app_context():
        comunidade, ministerio, membro = _igreja(logged_in_client)
        _escala(ministerio, membro, dias=3, nome="Culto de Domingo", funcoes=("Vocal",))
        _escala(ministerio, membro, dias=10, nome="Culto Jovem", funcoes=("Violao",))
        _escala(ministerio, membro, dias=5, nome="Cancelada", cancelada=True)

        _postar(logged_in_client, _payload("qual minha próxima escala?"))

        texto = enviados[0][1]
        assert "*Culto de Domingo* (Louvor)" in texto and "Culto Jovem" in texto and "Cancelada" not in texto
        assert texto.index("Culto de Domingo") < texto.index("Culto Jovem")
        assert {f.status for f in Funcao.objects(membro_id=membro.id)} == {"nao_notificado"}
        msg = MensagemWhatsapp.objects(direcao="recebida").first()
        assert (msg.acao, msg.lida) == ("consulta", True)
        conversa = logged_in_client.get(f"/comunidade/{comunidade.id}/whatsapp/5511987654321").data.decode()
        assert "Perguntou da escala (respondido)" in conversa


def test_pergunta_das_musicas_lista_o_repertorio_da_proxima_escala(logged_in_client, enviados, app, db):
    from app.escala.models import ItemRepertorio

    with app.app_context():
        _, ministerio, membro = _igreja(logged_in_client)
        sem_repertorio = _escala(ministerio, membro, dias=1, nome="Ensaio")
        _postar(logged_in_client, _payload("quais as músicas do culto?", wamid="w1"))
        assert "ainda não foi definido" in enviados[-1][1] and "Ensaio" in enviados[-1][1]

        # A proxima escala COM repertorio (pula a sem repertorio).
        culto = _escala(ministerio, membro, dias=3, nome="Culto de Domingo")
        ItemRepertorio(escala_id=culto.id, nome_musica="Bondade de Deus", tom="G", momento="Abertura", ordem=0).save()
        ItemRepertorio(escala_id=culto.id, nome_musica="Grande é o Senhor", ordem=1).save()
        _postar(logged_in_client, _payload("repertório de domingo", wamid="w2"))

        texto = enviados[-1][1]
        assert "Repertório · Culto de Domingo" in texto
        assert "1️⃣ Bondade de Deus · Tom *G* · Abertura" in texto and "2️⃣ Grande é o Senhor" in texto
        assert f"/escala/{culto.id}/repertorio/cifras" in texto and f"/escala/{culto.id}/repertorio/projecao" in texto
        assert texto.startswith("🎵") and sem_repertorio.nome not in texto
        assert MensagemWhatsapp.objects(wamid="w2").first().acao == "consulta"


def test_pergunta_de_endereco_e_horario_usa_o_cadastro_ou_vai_pra_caixa(logged_in_client, enviados, app, db):
    from datetime import time

    with app.app_context():
        comunidade, ministerio, _ = _igreja(logged_in_client)

        # Sem nada cadastrado: fica na caixa de entrada e a pessoa recebe o
        # menu (so 1 vez, a 2a pergunta nao repete).
        _postar(logged_in_client, _payload("qual o endereço da igreja?", wamid="w1"))
        _postar(logged_in_client, _payload("que horas é o culto?", wamid="w2"))
        assert len(enviados) == 1 and "passei para a liderança" in enviados[0][1]
        assert MensagemWhatsapp.objects(direcao="recebida", lida=False).count() == 2
        enviados.clear()

        comunidade.endereco, comunidade.latitude, comunidade.longitude = "Rua A, 10", -20.5, -40.3
        comunidade.save()
        ministerio.dias_culto, ministerio.culto_horario = "6", time(19, 0)
        ministerio.save()

        _postar(logged_in_client, _payload("qual o endereço da igreja?", wamid="w3"))
        _postar(logged_in_client, _payload("que horas é o culto?", wamid="w4"))
        assert "Rua A, 10" in enviados[0][1] and "maps.google.com/?q=-20.500000,-40.300000" in enviados[0][1]
        assert "domingo às 19:00 (Louvor)" in enviados[1][1]


def test_texto_qualquer_vai_pra_caixa_de_entrada_e_recebe_o_menu_uma_vez(logged_in_client, enviados, app, db):
    with app.app_context():
        comunidade, ministerio, membro = _igreja(logged_in_client)
        escala = _escala(ministerio, membro)
        _postar(logged_in_client, _payload("Que horas é o ensaio?"))
        assert len(enviados) == 1
        assert "passei para a liderança" in enviados[0][1] and "4️⃣ Músicas do repertório" in enviados[0][1]
        assert Funcao.objects(escala_id=escala.id).first().status == "nao_notificado"
        msg = MensagemWhatsapp.objects(direcao="recebida").first()
        assert (msg.lida, msg.comunidade_ids, msg.membro_ids) == (False, [comunidade.id], [membro.id])
        assert "1 nova(s)" in logged_in_client.get(f"/comunidade/{comunidade.id}").data.decode()

        # Conversa seguindo com a lideranca: sem menu de novo por 12h.
        _postar(logged_in_client, _payload("E o ensaio de sábado?", wamid="wamid.2"))
        assert len(enviados) == 1


def test_menu_e_atalho_por_numero(logged_in_client, enviados, app, db):
    from app.escala.models import ItemRepertorio

    with app.app_context():
        _, ministerio, membro = _igreja(logged_in_client)
        escala = _escala(ministerio, membro)
        ItemRepertorio(escala_id=escala.id, nome_musica="Bondade de Deus", tom="G", ordem=0).save()

        _postar(logged_in_client, _payload("bom dia!", wamid="w1"))
        assert enviados[-1][1].startswith("Olá, *Ana*! 👋") and "1️⃣ Confirmar minha próxima escala" in enviados[-1][1]
        assert MensagemWhatsapp.objects(wamid="w1").first().lida  # respondida sozinha, nao pede atencao

        _postar(logged_in_client, _payload("4", wamid="w2"))
        assert "Bondade de Deus · Tom *G*" in enviados[-1][1]
        _postar(logged_in_client, _payload("1", wamid="w3"))
        assert Funcao.objects(escala_id=escala.id).first().status == "confirmado"


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


# --- Foto do perfil (flask whatsapp-foto-perfil) ------------------------------------------------

def test_comando_foto_perfil_sobe_imagem_e_troca_perfil(app, monkeypatch, tmp_path):
    imagem = tmp_path / "logo.png"
    imagem.write_bytes(b"\x89PNG-falso")
    app.config.update(META_WHATSAPP_TOKEN="tok", META_WHATSAPP_PHONE_ID="999")
    chamadas = []

    class Resposta:
        def __init__(self, dados):
            self.status_code, self._dados, self.text = 200, dados, ""

        def json(self):
            return self._dados

    def falso_get(url, **kw):
        chamadas.append(("GET", url))
        return Resposta({"id": "app123"})

    def falso_post(url, **kw):
        chamadas.append(("POST", url, kw))
        if url.endswith("/app123/uploads"):
            return Resposta({"id": "upload:abc"})
        if url.endswith("/upload:abc"):
            return Resposta({"h": "handle-xyz"})
        return Resposta({"success": True})

    monkeypatch.setattr("app.whatsapp.requests.get", falso_get)
    monkeypatch.setattr("app.whatsapp.requests.post", falso_post)
    resultado = app.test_cli_runner().invoke(args=["whatsapp-foto-perfil", "--arquivo", str(imagem)])

    assert resultado.exit_code == 0, resultado.output
    abrir, enviar, perfil = [c for c in chamadas if c[0] == "POST"]
    assert abrir[2]["params"]["file_type"] == "image/png" and abrir[2]["params"]["file_length"] == 10
    assert enviar[2]["data"] == b"\x89PNG-falso" and enviar[2]["headers"]["file_offset"] == "0"
    assert perfil[1].endswith("/999/whatsapp_business_profile")
    assert perfil[2]["json"]["profile_picture_handle"] == "handle-xyz"


def test_comando_foto_perfil_sem_config_falha_com_mensagem(app):
    resultado = app.test_cli_runner().invoke(args=["whatsapp-foto-perfil"])
    assert resultado.exit_code == 1 and "nao configurado" in resultado.output


# --- Audio na caixa de entrada ------------------------------------------------------------------

def _payload_audio(de="5511987654321", wamid="wamid.audio", media_id="MEDIA123"):
    return {"entry": [{"changes": [{"value": {
        "contacts": [{"wa_id": de, "profile": {"name": "Ana"}}],
        "messages": [{"from": de, "id": wamid, "type": "audio",
                      "audio": {"id": media_id, "mime_type": "audio/ogg; codecs=opus", "voice": True}}],
    }}]}]}


def test_audio_recebido_e_baixado_e_toca_na_caixa_de_entrada(logged_in_client, enviados, app, db, monkeypatch):
    from app.whatsapp_recebidas import AudioWhatsapp

    baixados = []

    def falso_baixar(media_id):
        baixados.append(media_id)
        return b"OggS-audio-falso", "audio/ogg"

    monkeypatch.setattr("app.whatsapp.baixar_midia", falso_baixar)
    with app.app_context():
        comunidade, _, _ = _igreja(logged_in_client)
        _postar(logged_in_client, _payload_audio())

        msg = MensagemWhatsapp.objects(direcao="recebida").first()
        assert (msg.media_id, msg.texto, msg.lida) == ("MEDIA123", "🎤 Mensagem de voz", False)  # fica pra lideranca
        assert baixados == ["MEDIA123"] and AudioWhatsapp.objects(mensagem_id=msg.id).count() == 1

        conversa = logged_in_client.get(f"/comunidade/{comunidade.id}/whatsapp/5511987654321").data.decode()
        url = f"/comunidade/{comunidade.id}/whatsapp/audio/{msg.id}"
        assert f'<audio controls preload="none" src="{url}"' in conversa

        resposta = logged_in_client.get(url)
        assert resposta.status_code == 200 and resposta.data == b"OggS-audio-falso"
        assert resposta.mimetype == "audio/ogg"
        assert baixados == ["MEDIA123"]  # tocou o guardado, sem baixar de novo


def test_audio_nao_baixado_tenta_na_hora_e_avisa_se_falhar(logged_in_client, enviados, app, db, monkeypatch):
    from app.whatsapp import WhatsappNaoEnviadoError

    def falha(media_id):
        raise WhatsappNaoEnviadoError("expirou")

    monkeypatch.setattr("app.whatsapp.baixar_midia", falha)
    with app.app_context():
        comunidade, _, _ = _igreja(logged_in_client)
        _postar(logged_in_client, _payload_audio())
        msg = MensagemWhatsapp.objects(direcao="recebida").first()

        resposta = logged_in_client.get(f"/comunidade/{comunidade.id}/whatsapp/audio/{msg.id}")
        assert resposta.status_code == 404 and "Ouça direto no WhatsApp" in resposta.data.decode()

        # Na hora de tocar a Meta ja responde: baixa, guarda e toca.
        monkeypatch.setattr("app.whatsapp.baixar_midia", lambda media_id: (b"agora-vai", "audio/ogg"))
        assert logged_in_client.get(f"/comunidade/{comunidade.id}/whatsapp/audio/{msg.id}").data == b"agora-vai"


def test_audio_so_para_admin_e_numero_desconhecido_nao_baixa(logged_in_client, outro_logged_in_client, enviados,
                                                            app, db, monkeypatch):
    baixados = []
    monkeypatch.setattr("app.whatsapp.baixar_midia", lambda media_id: baixados.append(media_id) or (b"x", "audio/ogg"))
    with sessao_isolada(app):
        comunidade, _, _ = _igreja(logged_in_client)
        cid = comunidade.id
        _postar(logged_in_client, _payload_audio())
        _postar(logged_in_client, _payload_audio(de="5521999990000", wamid="wamid.outro", media_id="DESCONHECIDO"))
        msg_id = MensagemWhatsapp.objects(wamid="wamid.audio").first().id
        assert baixados == ["MEDIA123"]  # de fora de qualquer diretorio nao guarda audio
    with sessao_isolada(app):
        assert outro_logged_in_client.get(f"/comunidade/{cid}/whatsapp/audio/{msg_id}").status_code == 404


# --- Audio entendido (transcricao Azure Speech) ------------------------------------------------

@pytest.fixture
def fala(app, monkeypatch):
    """Liga a transcricao e troca o Azure por um texto controlado."""
    app.config.update(AZURE_SPEECH_KEY="chave", AZURE_SPEECH_REGION="brazilsouth")
    monkeypatch.setattr("app.whatsapp.baixar_midia", lambda media_id: (b"OggS-voz", "audio/ogg"))
    estado = {"texto": "Confirmo, pode contar comigo", "erro": None}

    def falso_transcrever(conteudo, mime="audio/ogg"):
        from app.transcricao import TranscricaoIndisponivel

        if estado["erro"]:
            raise TranscricaoIndisponivel(estado["erro"])
        return estado["texto"]

    monkeypatch.setattr("app.transcricao.transcrever", falso_transcrever)
    return estado


def test_audio_transcrito_confirma_a_escala_e_responde_com_o_que_entendeu(logged_in_client, enviados, app, db, fala):
    with app.app_context():
        comunidade, ministerio, membro = _igreja(logged_in_client)
        escala = _escala(ministerio, membro)
        _postar(logged_in_client, _payload_audio())

        assert Funcao.objects(escala_id=escala.id).first().status == "confirmado"
        assert enviados[-1][1].startswith("🎤 Entendi: “Confirmo, pode contar comigo”")
        assert "✅ *Presença confirmada!*" in enviados[-1][1]
        msg = MensagemWhatsapp.objects(direcao="recebida").first()
        assert (msg.transcricao, msg.acao, msg.lida) == ("Confirmo, pode contar comigo", "confirmado", True)
        conversa = logged_in_client.get(f"/comunidade/{comunidade.id}/whatsapp/5511987654321").data.decode()
        assert "Transcrição:" in conversa and "pode contar comigo" in conversa


def test_audio_com_pergunta_responde_e_sem_fala_vai_pra_caixa(logged_in_client, enviados, app, db, fala):
    from app.escala.models import ItemRepertorio

    with app.app_context():
        comunidade, ministerio, membro = _igreja(logged_in_client)
        comunidade_id = comunidade.id
        escala = _escala(ministerio, membro)
        ItemRepertorio(escala_id=escala.id, nome_musica="Bondade de Deus", tom="G", ordem=0).save()

        fala["texto"] = "Quais são as músicas do culto?"
        _postar(logged_in_client, _payload_audio(wamid="w1", media_id="M1"))
        assert "Bondade de Deus · Tom *G*" in enviados[-1][1]

        # Sem fala reconhecivel: aviso curto + caixa de entrada, escala intacta.
        fala["texto"] = None
        _postar(logged_in_client, _payload_audio(wamid="w2", media_id="M2"))
        assert "não consegui entender" in enviados[-1][1]
        msg = MensagemWhatsapp.objects(wamid="w2").first()
        assert (msg.lida, msg.status_transcricao) == (False, "sem_fala")
        assert Funcao.objects(escala_id=escala.id).first().status == "nao_notificado"

        # Azure recusou: o motivo fica guardado (diagnostico) e aparece pro admin;
        # o aviso nao se repete dentro de 30 min.
        total = len(enviados)
        fala["erro"] = "Azure Speech recusou: 401 chave invalida"
        _postar(logged_in_client, _payload_audio(wamid="w3", media_id="M3"))
        assert MensagemWhatsapp.objects(wamid="w3").first().status_transcricao.startswith("erro: Azure Speech recusou: 401")
        assert len(enviados) == total
        conversa = logged_in_client.get(f"/comunidade/{comunidade_id}/whatsapp/5511987654321").data.decode()
        assert "Transcrição falhou: Azure Speech recusou: 401" in conversa


def test_saudacao_usa_o_cadastro_principal_quando_o_telefone_se_repete(logged_in_client, enviados, app, db):
    """Regressao: o mesmo telefone em cadastros de teste de outra comunidade
    ("Emily") fazia o Ruan ser saudado como Emily. Vale quem tem escala futura."""
    with app.app_context():
        comunidade, ministerio, _ = _igreja(logged_in_client, telefone="(21) 90000-0000")
        Membro(comunidade_id=comunidade.id + 1000, nome="Emily Teste", telefone="21999123998").save()
        ruan = Membro(comunidade_id=comunidade.id, nome="Ruan Cardozo", telefone="(21) 99912-3998").save()
        _escala(ministerio, ruan)
        _postar(logged_in_client, _payload("Oi", de="552199123998"))
        assert enviados[-1][1].startswith("Olá, *Ruan*! 👋")


def test_audio_transcrito_que_nao_e_comando_responde_mesmo_depois_do_menu(logged_in_client, enviados, app, db, fala):
    """Regressao: "Oi" (menu) e logo depois um audio que o Azure ouviu como
    "Sul da igreja." ficava sem resposta (limite de 12h do menu)."""
    with app.app_context():
        _igreja(logged_in_client)
        _postar(logged_in_client, _payload("Oi", wamid="w-oi"))
        fala["texto"] = "Sul da igreja."
        _postar(logged_in_client, _payload_audio(wamid="w-audio"))
        assert enviados[-1][1].startswith("🎤 Entendi: “Sul da igreja.”")
        assert "Não reconheci um pedido" in enviados[-1][1] and "5️⃣ Endereço da igreja" in enviados[-1][1]
        assert MensagemWhatsapp.objects(wamid="w-audio").first().lida is False  # fica pra lideranca


def test_segundo_plano_monta_links_mesmo_fora_de_um_request(app):
    """Regressao: audio "musicas do repertorio" era transcrito e ficava sem
    resposta -- o link das folhas (url_for) quebrava na thread, fora de um
    request. O contexto do segundo plano precisa montar URL."""
    from flask import url_for

    from app.whatsapp_recebidas import _em_segundo_plano

    links = []
    with app.app_context():  # sem request, como na thread de producao
        _em_segundo_plano(lambda: links.append(url_for("escala.folha_repertorio", escala_id=7, tipo="cifras")))
    assert links == ["/escala/7/repertorio/cifras"]


def test_sem_azure_configurado_audio_so_fica_pra_ouvir(logged_in_client, enviados, app, db, monkeypatch):
    chamou = []
    monkeypatch.setattr("app.whatsapp.baixar_midia", lambda media_id: (b"x", "audio/ogg"))
    monkeypatch.setattr("app.transcricao.transcrever", lambda *a, **k: chamou.append(1) or "confirmo")
    with app.app_context():
        _, ministerio, membro = _igreja(logged_in_client)
        escala = _escala(ministerio, membro)
        _postar(logged_in_client, _payload_audio())
        assert chamou == [] and Funcao.objects(escala_id=escala.id).first().status == "nao_notificado"
        assert MensagemWhatsapp.objects(direcao="recebida").first().status_transcricao == "desligada"
        assert "escreva a mensagem" in enviados[-1][1]  # nunca silencio


def test_transcrever_chama_o_azure_com_ogg_opus(app, monkeypatch):
    from app.transcricao import TranscricaoIndisponivel, transcrever

    app.config.update(AZURE_SPEECH_KEY="chave", AZURE_SPEECH_REGION="brazilsouth", AZURE_SPEECH_ENDPOINT=None)
    pedidos = []

    class Resposta:
        def __init__(self, dados, status=200):
            self._dados, self.status_code, self.text = dados, status, str(dados)

        def json(self):
            return self._dados

    respostas = [Resposta({"RecognitionStatus": "Success", "DisplayText": "Qual minha próxima escala?"}),
                 Resposta({"RecognitionStatus": "NoMatch"}), Resposta({}, status=401)]

    def falso_post(url, params=None, data=None, timeout=None, headers=None):
        pedidos.append((url, params, headers))
        return respostas.pop(0)

    monkeypatch.setattr("app.transcricao.requests.post", falso_post)
    with app.app_context():
        assert transcrever(b"OggS") == "Qual minha próxima escala?"
        assert transcrever(b"OggS") is None
        with pytest.raises(TranscricaoIndisponivel):
            transcrever(b"OggS")
    url, params, headers = pedidos[0]
    assert url == "https://brazilsouth.stt.speech.microsoft.com/speech/recognition/conversation/cognitiveservices/v1"
    assert params["language"] == "pt-BR" and headers["Content-Type"] == "audio/ogg; codecs=opus"
    assert headers["Ocp-Apim-Subscription-Key"] == "chave"


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
        assert enviados[-1] == ("+5511987654321", "As 19h!")
        enviada = MensagemWhatsapp.objects(direcao="enviada", texto="As 19h!").first()
        assert (enviada.texto, enviada.comunidade_ids) == ("As 19h!", [comunidade.id])


def test_resposta_fora_da_janela_de_24h_e_bloqueada(logged_in_client, enviados, app, db):
    from datetime import datetime, timezone

    with app.app_context():
        comunidade, _, _ = _igreja(logged_in_client)
        _postar(logged_in_client, _payload("Oi"))
        antes = len(enviados)  # o menu automatico
        MensagemWhatsapp.objects.update(set__criada_em=datetime.now(timezone.utc) - timedelta(hours=25))
        url = f"/comunidade/{comunidade.id}/whatsapp/5511987654321"
        assert "Já passaram 24h" in logged_in_client.get(url).data.decode()
        logged_in_client.post(url, data={"texto": "Oi!"})
        assert len(enviados) == antes


def test_caixa_de_entrada_so_para_admin_da_comunidade(logged_in_client, outro_logged_in_client, enviados, app, db):
    with sessao_isolada(app):
        comunidade, _, _ = _igreja(logged_in_client)
        cid = comunidade.id
        _postar(logged_in_client, _payload("Oi"))
        antes = len(enviados)  # o menu automatico
    with sessao_isolada(app):
        assert outro_logged_in_client.get(f"/comunidade/{cid}/whatsapp").status_code == 404
        assert outro_logged_in_client.post(f"/comunidade/{cid}/whatsapp/5511987654321",
                                           data={"texto": "x"}).status_code == 404
        assert len(enviados) == antes
