"""Fase 3, item 1: troca entre membros (A pede, B aceita, lider aprova) e
datas indisponiveis marcadas pela propria pessoa."""
from datetime import date, datetime, timedelta, timezone

from app.auth.models import User
from app.escala.models import Escala, Funcao, Indisponibilidade, RegistroTroca
from app.notificacoes import Notificacao
from app.plantao.models import TurnoPlantao
from app.plantao.sincronizacao import sincronizar_turno
from tests.conftest import _registrar, sessao_isolada
from tests.test_escala import (
    _criar_comunidade, _criar_escala, _criar_membro, _criar_ministerio, _escalar, _funcao_por_nome,
)
from tests.test_plantao import _adicionar_equipe, _payload_turno


def _hoje():
    return (datetime.now(timezone.utc) - timedelta(hours=3)).date()


def _cenario_troca(app, lider, bruno_cliente):
    """Ana (lider) escala Bruno; Carla (com conta) e a colega sugerida."""
    carla_cliente = app.test_client()
    with sessao_isolada(app):
        _registrar(carla_cliente, "carla", "carla@example.com")
    with sessao_isolada(app):
        comunidade = _criar_comunidade(lider)
        ministerio = _criar_ministerio(lider, comunidade.id)
        escala = _criar_escala(lider, ministerio.id, "Culto", data=(_hoje() + timedelta(days=5)).isoformat(), horario="19:00")
        bruno = _criar_membro(lider, comunidade.id, "Bruno", email="bruno@example.com")
        carla = _criar_membro(lider, comunidade.id, "Carla", email="carla@example.com")
        funcao = _funcao_por_nome(escala, "Baixo")
        _escalar(lider, funcao.id, bruno.id)
    with sessao_isolada(app):
        bruno_cliente.post(f"/escala/funcao/{funcao.id}/status", data={
            "status": "troca_solicitada", "troca_sugestao_membro_id": carla.id, "troca_motivo": "Viagem",
        })
    return carla_cliente, escala, funcao, bruno, carla


def test_pedido_com_colega_sugerido_fica_aguardando_aceite(logged_in_client, outro_logged_in_client, app, db):
    _, escala, funcao, _, carla = _cenario_troca(app, logged_in_client, outro_logged_in_client)
    with sessao_isolada(app):
        funcao = Funcao.objects(id=funcao.id).first()
        assert funcao.status == "troca_solicitada" and funcao.troca_aceite == "pendente"
        registro = RegistroTroca.objects(id=funcao.troca_registro_id).first()
        assert registro.situacao == "aguardando_colega" and "sugeriu Carla" in registro.etapas[0]
        conta_carla = User.objects(email="carla@example.com").first()
        aviso = Notificacao.objects(usuario_id=conta_carla.id, tipo="troca_solicitada").first()
        assert aviso and aviso.link == f"/escala/troca/{funcao.id}"
        html = logged_in_client.get(f"/escala/{escala.id}").get_data(as_text=True)
        assert 'data-troca-aceite="pendente"' in html and "aguardando aceitar" in html


def test_colega_aceita_e_lider_aprova_com_historico(logged_in_client, outro_logged_in_client, app, db):
    carla_cliente, escala, funcao, bruno, carla = _cenario_troca(app, logged_in_client, outro_logged_in_client)
    with sessao_isolada(app):
        tela = carla_cliente.get(f"/escala/troca/{funcao.id}").get_data(as_text=True)
        assert "Bruno pediu para você assumir" in tela and "Aceitar" in tela
        carla_cliente.post(f"/escala/troca/{funcao.id}", data={"resposta": "aceitar"})
    with sessao_isolada(app):
        funcao_db = Funcao.objects(id=funcao.id).first()
        assert funcao_db.troca_aceite == "aceita"
        conta_bruno = User.objects(email="bruno@example.com").first()
        assert Notificacao.objects(usuario_id=conta_bruno.id, titulo__contains="Carla aceitou").count() == 1
        conta_ana = User.objects(email="ana@example.com").first()
        assert Notificacao.objects(usuario_id=conta_ana.id, titulo__contains="Carla aceitou").count() == 1
        registro_id = funcao_db.troca_registro_id

        logged_in_client.post(f"/escala/funcao/{funcao.id}/troca/aprovar", data={"membro_id": carla.id})
        funcao_db = Funcao.objects(id=funcao.id).first()
        assert funcao_db.membro_id == carla.id and funcao_db.troca_aceite is None
        registro = RegistroTroca.objects(id=registro_id).first()
        assert registro.situacao == "aprovada" and registro.substituto_id == carla.id
        assert [e.split(" · ", 1)[1] for e in registro.etapas] == [
            'Bruno pediu troca e sugeriu Carla (motivo: "Viagem")', "Carla aceitou assumir", "Líder aprovou: Carla assume",
        ]


def test_colega_recusa_e_lider_e_avisado(logged_in_client, outro_logged_in_client, app, db):
    carla_cliente, escala, funcao, _, _ = _cenario_troca(app, logged_in_client, outro_logged_in_client)
    with sessao_isolada(app):
        carla_cliente.post(f"/escala/troca/{funcao.id}", data={"resposta": "recusar"})
    with sessao_isolada(app):
        assert Funcao.objects(id=funcao.id).first().troca_aceite == "recusada"
        conta_ana = User.objects(email="ana@example.com").first()
        assert Notificacao.objects(usuario_id=conta_ana.id, titulo__contains="Carla recusou").count() == 1
        # Responder de novo nao muda nada.
        carla_cliente.post(f"/escala/troca/{funcao.id}", data={"resposta": "aceitar"})
        assert Funcao.objects(id=funcao.id).first().troca_aceite == "recusada"


def test_so_o_colega_sugerido_abre_a_tela_de_responder(logged_in_client, outro_logged_in_client, app, db):
    _, _, funcao, _, _ = _cenario_troca(app, logged_in_client, outro_logged_in_client)
    with sessao_isolada(app):
        assert outro_logged_in_client.get(f"/escala/troca/{funcao.id}").status_code == 404
        assert logged_in_client.get(f"/escala/troca/{funcao.id}").status_code == 404


def test_desistir_da_troca_fecha_o_historico(logged_in_client, outro_logged_in_client, app, db):
    _, _, funcao, _, _ = _cenario_troca(app, logged_in_client, outro_logged_in_client)
    with sessao_isolada(app):
        registro_id = Funcao.objects(id=funcao.id).first().troca_registro_id
        outro_logged_in_client.post(f"/escala/funcao/{funcao.id}/status", data={"status": "confirmado"})
        funcao_db = Funcao.objects(id=funcao.id).first()
        assert funcao_db.troca_aceite is None and funcao_db.troca_registro_id is None
        assert RegistroTroca.objects(id=registro_id).first().situacao == "cancelada"


def test_sugestao_sem_conta_vai_direto_ao_lider(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        escala = _criar_escala(logged_in_client, ministerio.id, "Culto", data=(_hoje() + timedelta(days=5)).isoformat())
        bruno = _criar_membro(logged_in_client, comunidade.id, "Bruno", email="bruno@example.com")
        dani = _criar_membro(logged_in_client, comunidade.id, "Dani")
        funcao = _funcao_por_nome(escala, "Baixo")
        _escalar(logged_in_client, funcao.id, bruno.id)
    with sessao_isolada(app):
        outro_logged_in_client.post(f"/escala/funcao/{funcao.id}/status", data={
            "status": "troca_solicitada", "troca_sugestao_membro_id": dani.id})
        funcao_db = Funcao.objects(id=funcao.id).first()
        assert funcao_db.troca_aceite is None
        registro = RegistroTroca.objects(id=funcao_db.troca_registro_id).first()
        assert registro.situacao == "pedida" and "não tem conta" in registro.etapas[-1]


# --- Datas indisponiveis ------------------------------------------------------------

def test_pessoa_marca_e_remove_datas_indisponiveis(logged_in_client, app, db):
    with app.app_context():
        assert "/perfil/indisponibilidade" in logged_in_client.get("/dashboard").get_data(as_text=True)
        dia = _hoje() + timedelta(days=10)
        logged_in_client.post("/perfil/indisponibilidade", data={
            "data_inicio": dia.isoformat(), "data_fim": (dia + timedelta(days=2)).isoformat(), "motivo": "Viagem"})
        item = Indisponibilidade.objects(email="ana@example.com").first()
        assert (item.data_inicio, item.data_fim, item.motivo) == (dia, dia + timedelta(days=2), "Viagem")
        html = logged_in_client.get("/perfil/indisponibilidade").get_data(as_text=True)
        assert "Viagem" in html and dia.strftime("%d/%m/%Y") in html

        erro = logged_in_client.post("/perfil/indisponibilidade", data={
            "data_inicio": dia.isoformat(), "data_fim": (dia - timedelta(days=1)).isoformat()}).get_data(as_text=True)
        assert "A data final não pode ser antes da inicial." in erro

        logged_in_client.post(f"/perfil/indisponibilidade/{item.id}/excluir")
        assert Indisponibilidade.objects(email="ana@example.com").count() == 0


def test_escala_avisa_quem_marcou_a_data(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        dia = _hoje() + timedelta(days=7)
        escala = _criar_escala(logged_in_client, ministerio.id, "Culto", data=dia.isoformat())
        bruno = _criar_membro(logged_in_client, comunidade.id, "Bruno", email="Bruno@Example.com")
        Indisponibilidade(email="bruno@example.com", data_inicio=dia, data_fim=dia, motivo="Plantão no hospital").save()
        html = logged_in_client.get(f"/escala/{escala.id}").get_data(as_text=True)
        assert "Bruno (indisponível: Plantão no hospital)" in html
        _escalar(logged_in_client, _funcao_por_nome(escala, "Baixo").id, bruno.id)
        assert "Possível conflito" in logged_in_client.get(f"/escala/{escala.id}").get_data(as_text=True)


def test_rodizio_deixa_vaga_e_avisa_o_lider_uma_vez(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        inicio = _hoje() + timedelta(days=1)
        logged_in_client.post(f"/plantao/ministerio/{ministerio.id}/nova", data=_payload_turno(
            nome="Recepção", data_inicio=inicio.isoformat(), intervalo_recorrencia="1", unidade_recorrencia="semana"))
        turno = TurnoPlantao.objects(nome="Recepção").first()
        bruno = _criar_membro(logged_in_client, comunidade.id, "Bruno", email="bruno@example.com")
        carla = _criar_membro(logged_in_client, comunidade.id, "Carla", email="carla@example.com")
        _adicionar_equipe(turno, [bruno, carla])
        Escala.objects(plantao_turno_id=turno.id).delete()
        Funcao.objects(escala_id__nin=[e.id for e in Escala.objects()]).delete()
        Indisponibilidade(email="carla@example.com", data_inicio=inicio, data_fim=inicio, motivo="Viagem").save()

        sincronizar_turno(turno, ate_data=inicio + timedelta(days=8))
        escala = Escala.objects(plantao_turno_id=turno.id, data=inicio).first()
        funcoes = list(Funcao.objects(escala_id=escala.id))
        assert sorted(f.membro_id or 0 for f in funcoes) == [0, bruno.id]
        # Na semana seguinte a Carla volta.
        seguinte = Escala.objects(plantao_turno_id=turno.id, data=inicio + timedelta(days=7)).first()
        assert sorted(f.membro_id for f in Funcao.objects(escala_id=seguinte.id)) == sorted([bruno.id, carla.id])

        ana = User.objects(email="ana@example.com").first()
        avisos = Notificacao.objects(usuario_id=ana.id, titulo__contains="Carla indisponível")
        assert avisos.count() == 1
        sincronizar_turno(turno, ate_data=inicio + timedelta(days=8))  # proximo tick: nada muda nem repete
        assert Notificacao.objects(usuario_id=ana.id, titulo__contains="Carla indisponível").count() == 1
        assert sorted(f.membro_id or 0 for f in Funcao.objects(escala_id=escala.id)) == [0, bruno.id]

        # Desmarcou a data: no proximo tick ela volta pra escala.
        Indisponibilidade.objects(email="carla@example.com").delete()
        sincronizar_turno(turno, ate_data=inicio + timedelta(days=8))
        assert sorted(f.membro_id for f in Funcao.objects(escala_id=escala.id)) == sorted([bruno.id, carla.id])
