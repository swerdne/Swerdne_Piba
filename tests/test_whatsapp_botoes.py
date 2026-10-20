"""WhatsApp com botoes de tocar: menu como lista de opcoes, "Confirmo"/"Nao
posso" nas mensagens e no template do aviso de escala, e o toque voltando
pelo webhook (interactive.*_reply e button.payload)."""
from datetime import date, timedelta

import pytest

from app.escala.models import Escala, Funcao
from tests.test_whatsapp_recebidas import _escala, _igreja, _payload, _postar, enviados  # noqa: F401


@pytest.fixture
def interativos(monkeypatch):
    """Troca o envio de mensagem com botoes/lista por uma lista."""
    lista = []

    def falso(destino, corpo, botoes=None, lista_opcoes=None, rodape=None, **kwargs):
        lista.append({"corpo": corpo, "botoes": botoes, "lista": kwargs.get("lista", lista_opcoes)})

    monkeypatch.setattr("app.whatsapp.enviar_whatsapp_interativo", falso)
    return lista


def _payload_toque(id_botao, titulo, de="5511987654321", wamid="wamid.toque", tipo="button_reply"):
    return {"entry": [{"changes": [{"value": {
        "contacts": [{"wa_id": de, "profile": {"name": "Ana"}}],
        "messages": [{"from": de, "id": wamid, "type": "interactive",
                      "interactive": {"type": tipo, tipo: {"id": id_botao, "title": titulo}}}],
    }}]}]}


def _payload_template(texto, payload, de="5511987654321", wamid="wamid.tpl"):
    return {"entry": [{"changes": [{"value": {
        "contacts": [{"wa_id": de, "profile": {"name": "Ana"}}],
        "messages": [{"from": de, "id": wamid, "type": "button", "button": {"text": texto, "payload": payload}}],
    }}]}]}


def test_menu_vai_como_lista_de_tocar_e_escalas_com_botoes(logged_in_client, enviados, interativos, app, db):
    with app.app_context():
        _, ministerio, membro = _igreja(logged_in_client)
        escala = _escala(ministerio, membro)
        _postar(logged_in_client, _payload("oi", wamid="w-oi"))
        menu = interativos[-1]
        assert menu["corpo"].startswith("Olá, *Ana*! 👋") and menu["lista"][0] == "Ver opções"
        assert [linha[0] for linha in menu["lista"][1]] == [f"menu:{n}" for n in range(1, 7)]

        _postar(logged_in_client, _payload("qual minha próxima escala?", wamid="w-esc"))
        assert interativos[-1]["botoes"] == [(f"confirmar:{escala.id}", "👍 Confirmo"),
                                             (f"recusar:{escala.id}", "❌ Não posso")]
        assert "*Culto*" in interativos[-1]["corpo"] and enviados == []  # nada caiu pro texto simples

        # opcao 3 tocada na lista = "minhas escalas"
        _postar(logged_in_client, _payload_toque("menu:3", "📅 Minhas escalas", wamid="w-l3", tipo="list_reply"))
        assert "Suas próximas escalas" in interativos[-1]["corpo"]


def test_tocar_confirmo_muda_a_escala_do_aviso_mesmo_nao_sendo_a_proxima(logged_in_client, enviados, interativos,
                                                                       app, db):
    with app.app_context():
        _, ministerio, membro = _igreja(logged_in_client)
        proxima = _escala(ministerio, membro, dias=1, nome="Ensaio")
        depois = _escala(ministerio, membro, dias=5, nome="Culto")
        _postar(logged_in_client, _payload_toque(f"confirmar:{depois.id}", "👍 Confirmo"))
        assert Funcao.objects(escala_id=depois.id).first().status == "confirmado"
        assert Funcao.objects(escala_id=proxima.id).first().status == "nao_notificado"
        assert "Presença confirmada" in enviados[-1][1] and "*Culto*" in enviados[-1][1]


def test_botao_do_template_nao_posso_pede_troca(logged_in_client, enviados, interativos, app, db):
    with app.app_context():
        _, ministerio, membro = _igreja(logged_in_client)
        escala = _escala(ministerio, membro)
        _postar(logged_in_client, _payload_template("❌ Não posso", f"recusar:{escala.id}"))
        funcao = Funcao.objects(escala_id=escala.id).first()
        assert funcao.status == "troca_solicitada" and "Não posso" in funcao.troca_motivo
        assert "avisamos a liderança" in enviados[-1][1]


def test_botao_sem_payload_usa_o_texto_do_botao(logged_in_client, enviados, interativos, app, db):
    """Template com botoes enviado sem payload: a Meta manda o proprio texto
    do botao -- vale como se a pessoa tivesse escrito."""
    with app.app_context():
        _, ministerio, membro = _igreja(logged_in_client)
        escala = _escala(ministerio, membro)
        _postar(logged_in_client, _payload_template("👍 Confirmo", "👍 Confirmo"))
        assert Funcao.objects(escala_id=escala.id).first().status == "confirmado"


def test_tocar_em_escala_cancelada_ou_passada_nao_muda_nada(logged_in_client, enviados, interativos, app, db):
    with app.app_context():
        _, ministerio, membro = _igreja(logged_in_client)
        cancelada = _escala(ministerio, membro, nome="Cancelada", cancelada=True)
        passada = _escala(ministerio, membro, dias=-3, nome="Passada")
        _postar(logged_in_client, _payload_toque(f"confirmar:{cancelada.id}", "👍 Confirmo", wamid="w-c"))
        assert "foi cancelada" in enviados[-1][1]
        _postar(logged_in_client, _payload_toque(f"confirmar:{passada.id}", "👍 Confirmo", wamid="w-p"))
        assert "já passou" in enviados[-1][1]
        assert {f.status for f in Funcao.objects(escala_id__in=[cancelada.id, passada.id])} == {"nao_notificado"}


def test_botao_com_falha_cai_pro_texto_simples(logged_in_client, enviados, app, db):
    """Sem o fixture `interativos`, o envio com botoes falha (sem token) e a
    resposta sai em texto, com o jeito de responder escrevendo."""
    with app.app_context():
        _, ministerio, membro = _igreja(logged_in_client)
        _escala(ministerio, membro)
        _postar(logged_in_client, _payload("minha escala", wamid="w-txt"))
        assert "Suas próximas escalas" in enviados[-1][1] and "Responda *confirmo* ou *não posso*" in enviados[-1][1]


def test_template_de_escala_leva_os_botoes_quando_configurado(logged_in_client, app, db, monkeypatch):
    chamadas = []
    monkeypatch.setattr("app.escala.routes.enviar_whatsapp_template",
                        lambda destinatario, nome_template, parametros, **extra:
                        chamadas.append((nome_template, extra)))
    with app.app_context():
        app.config.update(WHATSAPP_TEMPLATE_ESCALADO="pibachurch_escalado_v2", WHATSAPP_TEMPLATE_ESCALADO_BOTOES=True)
        _, ministerio, membro = _igreja(logged_in_client)
        escala = Escala(ministerio_id=ministerio.id, nome="Culto", departamento="Louvor",
                        data=date.today() + timedelta(days=2)).save()
        funcao = Funcao(escala_id=escala.id, nome="Vocal", ordem=0).save()
        logged_in_client.post(f"/escala/funcao/{funcao.id}/adicionar", data={"membro_id": membro.id})
        assert chamadas == [("pibachurch_escalado_v2",
                             {"botoes_payload": [f"confirmar:{escala.id}", f"recusar:{escala.id}"]})]


def test_payload_do_template_e_da_mensagem_com_botoes(app, monkeypatch):
    from app import whatsapp

    enviados_api = []
    monkeypatch.setattr(whatsapp, "_chamar_api", lambda token, phone, payload: enviados_api.append(payload))
    with app.app_context():
        app.config.update(META_WHATSAPP_TOKEN="t", META_WHATSAPP_PHONE_ID="p", WHATSAPP_LIMITE_TEMPLATES_DIA=0)
        whatsapp.enviar_whatsapp_template("(11) 98765-4321", "pibachurch_escalado_v2",
                                          ["Ana", "Vocal", "Culto", "26/10"], botoes_payload=["confirmar:7", "recusar:7"])
        whatsapp.enviar_whatsapp_interativo("(11) 98765-4321", "Oi", botoes=[("confirmar:7", "👍 Confirmo")])
        whatsapp.enviar_whatsapp_interativo("(11) 98765-4321", "Menu",
                                            lista=("Ver opções", [("menu:1", "👍 Confirmar presença", "desc")]))
    componentes = enviados_api[0]["template"]["components"]
    assert componentes[1] == {"type": "button", "sub_type": "quick_reply", "index": "0",
                              "parameters": [{"type": "payload", "payload": "confirmar:7"}]}
    assert componentes[2]["index"] == "1"
    assert enviados_api[1]["interactive"]["action"]["buttons"][0]["reply"] == {"id": "confirmar:7",
                                                                               "title": "👍 Confirmo"}
    linha = enviados_api[2]["interactive"]["action"]["sections"][0]["rows"][0]
    assert linha == {"id": "menu:1", "title": "👍 Confirmar presença", "description": "desc"}
