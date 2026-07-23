"""Testes do modulo plantao (rodizio dinamico que alimenta a Escala real).

O rodizio (TurnoPlantao: fila+offset+recorrencia+departamento) e materializado
em Escala/Funcao reais por app/plantao/sincronizacao.py -- os testes aqui
cobrem principalmente esse motor de sincronizacao (criacao, idempotencia,
respeito a plantao_fixado, imutabilidade do passado) e o remanejamento por
ausencia sobre o estado materializado.
"""
from datetime import date, datetime, time, timedelta

from app.extensions import db
from app.escala.models import Escala, Funcao, Membro
from app.plantao.models import (
    TurnoPlantao,
    MembroTurno,
    data_do_periodo,
    periodo_da_data,
    membro_do_periodo,
)
from app.plantao.sincronizacao import (
    sincronizar_turno,
    preparar_para_renumeracao,
    marcar_ausencia,
    JANELA_GERACAO_DIAS,
)
from tests.conftest import sessao_isolada
from tests.test_escala import _criar_comunidade, _criar_ministerio


def _criar_turno_teste(ministerio_id, nome="Turno Teste", data_inicio=date(2026, 1, 1),
                        recorrencia="diaria", horario=None, offset=0, departamento="Louvor",
                        nome_funcao="Responsavel"):
    turno = TurnoPlantao(
        ministerio_id=ministerio_id, nome=nome, data_inicio=data_inicio,
        recorrencia=recorrencia, horario=horario, offset=offset,
        departamento=departamento, nome_funcao=nome_funcao,
    )
    db.session.add(turno)
    db.session.commit()
    return turno


def _criar_membro_teste(comunidade_id, nome):
    membro = Membro(comunidade_id=comunidade_id, nome=nome)
    db.session.add(membro)
    db.session.commit()
    return membro


def _adicionar_a_fila(turno, membros):
    for posicao, membro in enumerate(membros):
        db.session.add(MembroTurno(turno_id=turno.id, membro_id=membro.id, posicao=posicao))
    db.session.commit()


def _escala_do_periodo(turno, periodo):
    return Escala.query.filter_by(plantao_turno_id=turno.id, plantao_periodo=periodo).first()


def _membro_materializado(turno, periodo):
    escala = _escala_do_periodo(turno, periodo)
    if escala is None or not escala.funcoes:
        return None
    return escala.funcoes[0].membro


# --- Conversao data <-> periodo (matematica pura, nao muda) --------------------

def test_periodo_da_data_diaria(app, db):
    with app.app_context():
        turno = TurnoPlantao(ministerio_id=1, nome="T", data_inicio=date(2026, 1, 1), recorrencia="diaria", departamento="Louvor")
        assert periodo_da_data(turno, date(2026, 1, 1)) == 0
        assert periodo_da_data(turno, date(2026, 1, 5)) == 4
        assert data_do_periodo(turno, 4) == date(2026, 1, 5)


def test_periodo_da_data_semanal(app, db):
    with app.app_context():
        turno = TurnoPlantao(ministerio_id=1, nome="T", data_inicio=date(2026, 1, 1), recorrencia="semanal", departamento="Louvor")
        assert periodo_da_data(turno, date(2026, 1, 1)) == 0
        assert periodo_da_data(turno, date(2026, 1, 7)) == 0
        assert periodo_da_data(turno, date(2026, 1, 8)) == 1
        assert data_do_periodo(turno, 2) == date(2026, 1, 15)


def test_periodo_da_data_mensal_com_virada_de_ano(app, db):
    with app.app_context():
        turno = TurnoPlantao(ministerio_id=1, nome="T", data_inicio=date(2026, 1, 31), recorrencia="mensal", departamento="Louvor")
        # fevereiro nao tem dia 31 -- deve cair no dia 28 (2026 nao e bissexto)
        assert data_do_periodo(turno, 1) == date(2026, 2, 28)
        assert periodo_da_data(turno, date(2026, 2, 28)) == 1
        # virada de ano: periodo 12 = janeiro de 2027
        assert data_do_periodo(turno, 12) == date(2027, 1, 31)
        assert periodo_da_data(turno, date(2027, 1, 31)) == 12


# --- Formula pura do rodizio -----------------------------------------------------

def test_membro_do_periodo_rodizio_simples(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        turno = _criar_turno_teste(ministerio.id)

        a = _criar_membro_teste(comunidade.id, "Ana")
        b = _criar_membro_teste(comunidade.id, "Bruno")
        c = _criar_membro_teste(comunidade.id, "Carlos")
        _adicionar_a_fila(turno, [a, b, c])

        assert membro_do_periodo(turno, 0).nome == "Ana"
        assert membro_do_periodo(turno, 1).nome == "Bruno"
        assert membro_do_periodo(turno, 2).nome == "Carlos"
        # wraparound do modulo
        assert membro_do_periodo(turno, 3).nome == "Ana"
        assert membro_do_periodo(turno, 5).nome == "Carlos"


def test_membro_do_periodo_com_offset(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        turno = _criar_turno_teste(ministerio.id, offset=1)

        a = _criar_membro_teste(comunidade.id, "Ana")
        b = _criar_membro_teste(comunidade.id, "Bruno")
        _adicionar_a_fila(turno, [a, b])

        assert membro_do_periodo(turno, 0).nome == "Bruno"
        assert membro_do_periodo(turno, 1).nome == "Ana"


def test_membro_do_periodo_fila_vazia(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        turno = _criar_turno_teste(ministerio.id)

        assert membro_do_periodo(turno, 0) is None


# --- Motor de sincronizacao (materializacao em Escala/Funcao reais) ------------

def test_sincronizar_turno_cria_ocorrencias(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        turno = _criar_turno_teste(
            ministerio.id, data_inicio=date.today(), recorrencia="diaria", departamento="Midia", nome_funcao="Plantonista"
        )
        a = _criar_membro_teste(comunidade.id, "Ana")
        b = _criar_membro_teste(comunidade.id, "Bruno")
        _adicionar_a_fila(turno, [a, b])

        sincronizar_turno(turno, ate_data=date.today() + timedelta(days=5))

        escalas = Escala.query.filter_by(plantao_turno_id=turno.id).order_by(Escala.plantao_periodo).all()
        assert len(escalas) == 6  # periodo 0..5 (hoje + 5 dias)
        assert escalas[0].departamento == "Midia"
        assert escalas[0].funcoes[0].nome == "Plantonista"
        assert [e.funcoes[0].membro.nome for e in escalas] == ["Ana", "Bruno", "Ana", "Bruno", "Ana", "Bruno"]
        assert escalas[0].plantao_fixado is False


def test_sincronizar_turno_com_fila_vazia_materializa_sem_membro(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        turno = _criar_turno_teste(ministerio.id, data_inicio=date.today())

        sincronizar_turno(turno, ate_data=date.today() + timedelta(days=2))

        escalas = Escala.query.filter_by(plantao_turno_id=turno.id).all()
        assert len(escalas) == 3
        assert all(e.funcoes[0].membro_id is None for e in escalas)


def test_sincronizar_turno_e_idempotente(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        # data_inicio amanha (nao hoje): garante que o periodo 0 e FUTURO
        # independente da hora em que o teste roda -- uma escala materializada
        # "hoje sem horario" cai a meia-noite de hoje, que ja seria "passado"
        # por qualquer horario de execucao do teste apos 00h00.
        turno = _criar_turno_teste(ministerio.id, data_inicio=date.today() + timedelta(days=1))
        a = _criar_membro_teste(comunidade.id, "Ana")
        _adicionar_a_fila(turno, [a])

        sincronizar_turno(turno, ate_data=date.today() + timedelta(days=3))
        escala = _escala_do_periodo(turno, 0)
        escala.notificado_24h_em = datetime.now()
        escala.funcoes[0].notificado_em = datetime.now()
        db.session.commit()
        marcado_em = escala.notificado_24h_em

        # roda de novo sem mudar nada na config do turno
        sincronizar_turno(turno, ate_data=date.today() + timedelta(days=2))
        db.session.expire_all()

        total = Escala.query.filter_by(plantao_turno_id=turno.id, plantao_periodo=0).count()
        assert total == 1  # nao duplicou
        escala_recarregada = _escala_do_periodo(turno, 0)
        assert escala_recarregada.notificado_24h_em == marcado_em  # nao resetou


def test_sincronizar_turno_preserva_ocorrencia_fixada(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        turno = _criar_turno_teste(ministerio.id, data_inicio=date.today() + timedelta(days=1))
        a = _criar_membro_teste(comunidade.id, "Ana")
        b = _criar_membro_teste(comunidade.id, "Bruno")
        _adicionar_a_fila(turno, [a, b])

        sincronizar_turno(turno, ate_data=date.today() + timedelta(days=3))
        escala = _escala_do_periodo(turno, 0)
        assert escala.funcoes[0].membro.nome == "Ana"

        # fixa manualmente com um membro divergente da formula
        escala.funcoes[0].membro_id = b.id
        escala.plantao_fixado = True
        db.session.commit()

        sincronizar_turno(turno, ate_data=date.today() + timedelta(days=2))
        db.session.expire_all()

        assert _escala_do_periodo(turno, 0).funcoes[0].membro.nome == "Bruno"  # nao foi sobrescrita


def test_sincronizar_turno_nunca_toca_periodo_ja_ocorrido(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        agora = datetime.now()
        ha_pouco = agora - timedelta(minutes=10)

        turno = _criar_turno_teste(
            ministerio.id, data_inicio=ha_pouco.date(), recorrencia="diaria", horario=ha_pouco.time()
        )
        a = _criar_membro_teste(comunidade.id, "Ana")
        b = _criar_membro_teste(comunidade.id, "Bruno")
        _adicionar_a_fila(turno, [a])  # so Ana na fila -> periodo 0 materializa com Ana

        sincronizar_turno(turno)
        assert _escala_do_periodo(turno, 0).funcoes[0].membro.nome == "Ana"

        # adiciona Bruno na fila (mudaria a formula do periodo 0 se fosse recalculado)
        _adicionar_a_fila(turno, [b])
        sincronizar_turno(turno)
        db.session.expire_all()

        # periodo 0 (horario ja passou) continua com Ana -- historico intocavel
        assert _escala_do_periodo(turno, 0).funcoes[0].membro.nome == "Ana"


def test_editar_turno_reflete_em_periodos_futuros_nao_fixados(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        turno = _criar_turno_teste(
            ministerio.id, data_inicio=date.today() + timedelta(days=1), departamento="Louvor", nome_funcao="Responsavel"
        )
        a = _criar_membro_teste(comunidade.id, "Ana")
        _adicionar_a_fila(turno, [a])
        sincronizar_turno(turno, ate_data=date.today() + timedelta(days=3))

        turno.departamento = "Kids"
        turno.nome_funcao = "Recepcionista"
        turno.nome = "Plantao Kids"
        db.session.commit()
        sincronizar_turno(turno, ate_data=date.today() + timedelta(days=3))
        db.session.expire_all()

        escala = _escala_do_periodo(turno, 0)
        assert escala.departamento == "Kids"
        assert escala.nome == "Plantao Kids"
        assert escala.funcoes[0].nome == "Recepcionista"


def test_editar_horario_dispara_notificacao_de_alteracao_e_reseta_timestamps(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        turno = _criar_turno_teste(ministerio.id, data_inicio=date.today() + timedelta(days=1), horario=time(8, 0))
        a = _criar_membro_teste(comunidade.id, "Ana", )
        _adicionar_a_fila(turno, [a])
        sincronizar_turno(turno, ate_data=date.today() + timedelta(days=2))

        escala = _escala_do_periodo(turno, 0)
        escala.notificado_24h_em = datetime.now()
        db.session.commit()

        turno.horario = time(20, 0)
        db.session.commit()
        sincronizar_turno(turno, ate_data=date.today() + timedelta(days=2))
        db.session.expire_all()

        escala_atualizada = _escala_do_periodo(turno, 0)
        assert escala_atualizada.horario == time(20, 0)
        assert escala_atualizada.notificado_24h_em is None  # resetado pra reconsiderar notificacao


def test_editar_data_inicio_recria_periodos_futuros_preserva_passado_fixado(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        agora = datetime.now()
        ha_pouco = agora - timedelta(minutes=5)

        turno = _criar_turno_teste(
            ministerio.id, data_inicio=ha_pouco.date(), recorrencia="diaria", horario=ha_pouco.time()
        )
        a = _criar_membro_teste(comunidade.id, "Ana")
        b = _criar_membro_teste(comunidade.id, "Bruno")
        _adicionar_a_fila(turno, [a, b])

        sincronizar_turno(turno, ate_data=date.today() + timedelta(days=3))
        escala_passada_id = _escala_do_periodo(turno, 0).id
        escala_futura_id = _escala_do_periodo(turno, 2).id

        nova_data_inicio = date.today() + timedelta(days=10)
        turno.data_inicio = nova_data_inicio
        db.session.commit()
        preparar_para_renumeracao(turno)
        db.session.expire_all()

        # a ocorrencia ja ocorrida continua existindo, so perde o vinculo de periodo
        escala_passada = db.session.get(Escala, escala_passada_id)
        assert escala_passada is not None
        assert escala_passada.plantao_turno_id == turno.id
        assert escala_passada.plantao_periodo is None

        # a futura nao-fixada foi removida (era so previsao com numeracao antiga)
        assert db.session.get(Escala, escala_futura_id) is None

        # sync com a nova config nao colide com a unique constraint
        sincronizar_turno(turno, ate_data=nova_data_inicio + timedelta(days=2))
        assert _escala_do_periodo(turno, 0).data == nova_data_inicio


def test_adicionar_membro_na_fila_reajusta_so_o_futuro(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        agora = datetime.now()
        ha_pouco = agora - timedelta(minutes=5)

        turno = _criar_turno_teste(
            ministerio.id, data_inicio=ha_pouco.date(), recorrencia="diaria", horario=ha_pouco.time()
        )
        a = _criar_membro_teste(comunidade.id, "Ana")
        _adicionar_a_fila(turno, [a])
        sincronizar_turno(turno, ate_data=date.today() + timedelta(days=2))
        assert _escala_do_periodo(turno, 0).funcoes[0].membro.nome == "Ana"  # ja ocorrido

        b = _criar_membro_teste(comunidade.id, "Bruno")
        db.session.add(MembroTurno(turno_id=turno.id, membro_id=b.id, posicao=1))
        db.session.commit()
        sincronizar_turno(turno, ate_data=date.today() + timedelta(days=2))
        db.session.expire_all()

        assert _escala_do_periodo(turno, 0).funcoes[0].membro.nome == "Ana"  # passado intocado
        assert _escala_do_periodo(turno, 1).funcoes[0].membro.nome == "Bruno"  # futuro reajustado


# --- Remanejamento por falta (sobre estado materializado) -----------------------

def test_marcar_ausencia_troca_com_o_periodo_seguinte(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        turno = _criar_turno_teste(ministerio.id, data_inicio=date.today())

        a = _criar_membro_teste(comunidade.id, "Ana")
        b = _criar_membro_teste(comunidade.id, "Bruno")
        c = _criar_membro_teste(comunidade.id, "Carlos")
        _adicionar_a_fila(turno, [a, b, c])
        sincronizar_turno(turno, ate_data=date.today() + timedelta(days=3))

        marcar_ausencia(turno, 1)  # Bruno falta no periodo 1

        assert _membro_materializado(turno, 1).nome == "Carlos"
        assert _membro_materializado(turno, 2).nome == "Bruno"
        assert _membro_materializado(turno, 0).nome == "Ana"  # resto intocado
        assert _escala_do_periodo(turno, 1).plantao_fixado is True
        assert _escala_do_periodo(turno, 2).plantao_fixado is True


def test_marcar_ausencia_em_cascata_respeita_remanejamento_anterior(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        turno = _criar_turno_teste(ministerio.id, data_inicio=date.today() + timedelta(days=1))

        a = _criar_membro_teste(comunidade.id, "Ana")
        b = _criar_membro_teste(comunidade.id, "Bruno")
        c = _criar_membro_teste(comunidade.id, "Carlos")
        _adicionar_a_fila(turno, [a, b, c])
        sincronizar_turno(turno, ate_data=date.today() + timedelta(days=3))

        marcar_ausencia(turno, 0)  # Ana falta -> Bruno cobre 0, Ana cobre 1
        assert _membro_materializado(turno, 0).nome == "Bruno"
        assert _membro_materializado(turno, 1).nome == "Ana"

        marcar_ausencia(turno, 1)  # quem estava no periodo 1 era Ana (remanejada) -- nao a formula base
        assert _membro_materializado(turno, 1).nome == "Carlos"
        assert _membro_materializado(turno, 2).nome == "Ana"


def test_marcar_ausencia_rejeita_periodo_ja_ocorrido(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        agora = datetime.now()
        ha_pouco = agora - timedelta(minutes=5)
        turno = _criar_turno_teste(
            ministerio.id, data_inicio=ha_pouco.date(), recorrencia="diaria", horario=ha_pouco.time()
        )
        a = _criar_membro_teste(comunidade.id, "Ana")
        b = _criar_membro_teste(comunidade.id, "Bruno")
        _adicionar_a_fila(turno, [a, b])
        sincronizar_turno(turno)

        import pytest
        with pytest.raises(ValueError):
            marcar_ausencia(turno, 0)


# --- Exclusao de turno ------------------------------------------------------------

def test_excluir_turno_via_rota_preserva_passado_remove_futuro(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        agora = datetime.now()
        ha_pouco = agora - timedelta(minutes=5)
        turno = _criar_turno_teste(
            ministerio.id, data_inicio=ha_pouco.date(), recorrencia="diaria", horario=ha_pouco.time()
        )
        a = _criar_membro_teste(comunidade.id, "Ana")
        _adicionar_a_fila(turno, [a])
        sincronizar_turno(turno, ate_data=date.today() + timedelta(days=3))

        escala_passada_id = _escala_do_periodo(turno, 0).id
        escala_futura_id = _escala_do_periodo(turno, 2).id

        response = logged_in_client.post(f"/plantao/{turno.id}/excluir", data={}, follow_redirects=True)
        assert response.status_code == 200

        escala_passada = db.session.get(Escala, escala_passada_id)
        assert escala_passada is not None
        assert escala_passada.plantao_turno_id is None
        assert escala_passada.plantao_periodo is None

        assert db.session.get(Escala, escala_futura_id) is None
        assert TurnoPlantao.query.get(turno.id) is None


# --- Rotas HTTP -----------------------------------------------------------------

def test_criar_turno_via_rota_materializa_escalas(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)

        response = logged_in_client.post(
            f"/plantao/ministerio/{ministerio.id}/nova",
            data={
                "nome": "Plantao Manha", "departamento": "Midia", "nome_funcao": "Plantonista",
                "data_inicio": date.today().isoformat(), "horario": "08:00", "recorrencia": "diaria",
            },
            follow_redirects=True,
        )
        assert response.status_code == 200
        turno = TurnoPlantao.query.filter_by(nome="Plantao Manha", ministerio_id=ministerio.id).first()
        assert turno is not None
        assert turno.departamento == "Midia"
        assert Escala.query.filter_by(plantao_turno_id=turno.id).count() > 0


def test_adicionar_e_remover_membro_da_fila_via_rota(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        turno = _criar_turno_teste(ministerio.id, data_inicio=date.today())
        membro = _criar_membro_teste(comunidade.id, "Ana")

        response = logged_in_client.post(
            f"/plantao/{turno.id}/fila/adicionar", data={"membro_id": membro.id}, follow_redirects=True
        )
        assert response.status_code == 200
        assert MembroTurno.query.filter_by(turno_id=turno.id, membro_id=membro.id).count() == 1
        assert Escala.query.filter_by(plantao_turno_id=turno.id).count() > 0

        item = MembroTurno.query.filter_by(turno_id=turno.id, membro_id=membro.id).first()
        logged_in_client.post(
            f"/plantao/{turno.id}/fila/{item.id}/remover", data={}, follow_redirects=True
        )
        assert MembroTurno.query.filter_by(turno_id=turno.id, membro_id=membro.id).count() == 0


def test_marcar_ausencia_via_rota(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        amanha = date.today() + timedelta(days=1)
        turno = _criar_turno_teste(ministerio.id, data_inicio=amanha)

        a = _criar_membro_teste(comunidade.id, "Ana")
        b = _criar_membro_teste(comunidade.id, "Bruno")
        _adicionar_a_fila(turno, [a, b])
        sincronizar_turno(turno, ate_data=amanha + timedelta(days=2))

        response = logged_in_client.post(
            f"/plantao/{turno.id}/ausencia", data={"data": amanha.isoformat()}, follow_redirects=True
        )
        assert response.status_code == 200
        assert "fila reorganizada a partir dai" in response.data.decode("utf-8")
        assert _membro_materializado(turno, 0).nome == "Bruno"
        assert _membro_materializado(turno, 1).nome == "Ana"


def test_marcar_ausencia_via_escala_gerada(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        amanha = date.today() + timedelta(days=1)
        turno = _criar_turno_teste(ministerio.id, data_inicio=amanha)

        a = _criar_membro_teste(comunidade.id, "Ana")
        b = _criar_membro_teste(comunidade.id, "Bruno")
        _adicionar_a_fila(turno, [a, b])
        sincronizar_turno(turno, ate_data=amanha + timedelta(days=2))
        escala = _escala_do_periodo(turno, 0)

        response = logged_in_client.post(
            f"/plantao/escala/{escala.id}/ausencia", data={}, follow_redirects=True
        )
        assert response.status_code == 200
        assert _membro_materializado(turno, 0).nome == "Bruno"


def test_usuario_nao_consegue_ver_turno_de_outra_conta(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade = _criar_comunidade(logged_in_client, "Comunidade Ana")
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        turno = _criar_turno_teste(ministerio.id)
        turno_id = turno.id

    with sessao_isolada(app):
        assert outro_logged_in_client.get(f"/plantao/{turno_id}").status_code == 404
        assert outro_logged_in_client.get(f"/plantao/{turno_id}/editar").status_code == 404


def test_usuario_nao_consegue_marcar_ausencia_em_turno_de_outra_conta(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade = _criar_comunidade(logged_in_client, "Comunidade Ana")
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        turno = _criar_turno_teste(ministerio.id, data_inicio=date.today())
        a = _criar_membro_teste(comunidade.id, "Ana")
        b = _criar_membro_teste(comunidade.id, "Bruno")
        _adicionar_a_fila(turno, [a, b])
        sincronizar_turno(turno, ate_data=date.today() + timedelta(days=2))
        turno_id = turno.id

    with sessao_isolada(app):
        response = outro_logged_in_client.post(
            f"/plantao/{turno_id}/ausencia", data={"data": date.today().isoformat()}, follow_redirects=True
        )
        assert response.status_code == 404

    with sessao_isolada(app):
        turno_recarregado = db.session.get(TurnoPlantao, turno_id)
        assert _escala_do_periodo(turno_recarregado, 0).plantao_fixado is False


# --- Integracao com calendario/relatorio do resto do sistema --------------------

def test_ocorrencia_gerada_aparece_na_lista_de_escalas_do_ministerio(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        turno = _criar_turno_teste(ministerio.id, data_inicio=date.today())
        a = _criar_membro_teste(comunidade.id, "Ana")
        _adicionar_a_fila(turno, [a])
        sincronizar_turno(turno, ate_data=date.today() + timedelta(days=1))

        response = logged_in_client.get(f"/ministerio/{ministerio.id}")
        assert response.status_code == 200
        assert turno.nome.encode() in response.data


def test_ocorrencia_gerada_aparece_no_relatorio_escalados(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        turno = _criar_turno_teste(ministerio.id, data_inicio=date.today())
        a = _criar_membro_teste(comunidade.id, "Ana")
        _adicionar_a_fila(turno, [a])
        sincronizar_turno(turno, ate_data=date.today() + timedelta(days=1))

        response = logged_in_client.get(f"/comunidade/{comunidade.id}/escalados")
        assert response.status_code == 200
        assert b"Ana" in response.data
