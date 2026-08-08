"""Testes do modulo plantao (rodizio dinamico que alimenta a Escala real).

O rodizio (TurnoPlantao: fila+offset+recorrencia+departamento) e materializado
em Escala/Funcao reais por app/plantao/sincronizacao.py -- os testes aqui
cobrem o motor de recorrencia estilo Google Agenda (app/plantao/models.py),
o motor de sincronizacao (criacao, idempotencia, respeito a plantao_fixado,
imutabilidade do passado) e a formula de rotacao por EQUIPES (grupos de 1+
pessoas que atuam juntas na mesma ocorrencia -- rotacao individual e so o
caso particular de equipes com 1 integrante).
"""
from datetime import date, datetime, time, timedelta

import pytest

from app.extensions import db
from app.escala.models import Escala, Funcao, Membro
from app.plantao.models import (
    TurnoPlantao,
    EquipeTurno,
    EquipeMembro,
    data_do_periodo,
    periodo_da_data,
    equipe_do_periodo,
    opcoes_modo_mensal,
    opcoes_modo_mensal_completas,
)
from app.plantao.sincronizacao import (
    sincronizar_turno,
    preparar_para_renumeracao,
    JANELA_GERACAO_DIAS,
)
from tests.conftest import sessao_isolada
from tests.test_escala import (
    _criar_comunidade,
    _criar_ministerio,
    _criar_escala,
    _criar_membro,
    _escalar,
    _funcao_por_nome,
)


def _criar_turno_teste(ministerio_id, nome="Turno Teste", data_inicio=date(2026, 1, 1),
                        unidade_recorrencia="dia", intervalo_recorrencia=1, dias_semana=None,
                        modo_mensal=None, termino_tipo="nunca", termino_data=None, termino_ocorrencias=None,
                        horario=None, offset=0, departamento="Louvor", nome_funcao="Responsavel"):
    turno = TurnoPlantao(
        ministerio_id=ministerio_id, nome=nome, data_inicio=data_inicio,
        unidade_recorrencia=unidade_recorrencia, intervalo_recorrencia=intervalo_recorrencia,
        dias_semana=dias_semana, modo_mensal=modo_mensal,
        termino_tipo=termino_tipo, termino_data=termino_data, termino_ocorrencias=termino_ocorrencias,
        horario=horario, offset=offset, departamento=departamento, nome_funcao=nome_funcao,
    )
    db.session.add(turno)
    db.session.commit()
    return turno


def _payload_turno(**overrides):
    """POST body valido pras rotas nova/editar -- WTForms exige todos os
    campos presentes mesmo os condicionais (o form so IGNORA os que nao se
    aplicam a unidade/termino escolhidos)."""
    payload = {
        "nome": "Turno Teste", "departamento": "Louvor", "nome_funcao": "Responsavel",
        "data_inicio": date(2026, 1, 1).isoformat(), "horario": "",
        "intervalo_recorrencia": "1", "unidade_recorrencia": "dia",
        "termino_tipo": "nunca",
    }
    payload.update(overrides)
    return payload


def _criar_membro_teste(comunidade_id, nome):
    membro = Membro(comunidade_id=comunidade_id, nome=nome)
    db.session.add(membro)
    db.session.commit()
    return membro


def _adicionar_a_fila(turno, membros):
    """Adiciona cada membro como uma equipe (posicao) de 1 pessoa -- equivale
    ao rodizio puramente individual de sempre: e so o caso particular onde
    toda equipe da fila tem 1 integrante. Continua uma posicao por chamada
    (recalcula o proximo `posicao` a cada chamada, entao pode ser chamada
    mais de uma vez pra ir incrementando a fila aos poucos)."""
    posicao = max([e.posicao for e in turno.fila], default=-1) + 1
    for membro in membros:
        equipe = EquipeTurno(turno_id=turno.id, posicao=posicao)
        db.session.add(equipe)
        db.session.flush()
        db.session.add(EquipeMembro(equipe_turno_id=equipe.id, membro_id=membro.id))
        posicao += 1
    db.session.commit()


def _adicionar_equipe(turno, membros):
    """Adiciona TODOS os membros como uma UNICA equipe (mesma posicao) --
    pra testar o rodizio revezando GRUPOS inteiros, nao pessoas isoladas."""
    posicao = max([e.posicao for e in turno.fila], default=-1) + 1
    equipe = EquipeTurno(turno_id=turno.id, posicao=posicao)
    db.session.add(equipe)
    db.session.flush()
    for membro in membros:
        db.session.add(EquipeMembro(equipe_turno_id=equipe.id, membro_id=membro.id))
    db.session.commit()
    return equipe


def _escala_do_periodo(turno, periodo):
    return Escala.query.filter_by(plantao_turno_id=turno.id, plantao_periodo=periodo).first()


def _membro_materializado(turno, periodo):
    """Nome do 1o (e normalmente unico, pra equipes de 1 pessoa) escalado no
    periodo. Pra periodos com equipes de varias pessoas, use
    _membros_materializados."""
    escala = _escala_do_periodo(turno, periodo)
    if escala is None or not escala.funcoes:
        return None
    return escala.funcoes[0].membro


def _membros_materializados(turno, periodo):
    """Nomes (ordenados) de todo mundo escalado no periodo -- usado pra
    testar ocorrencias geradas por equipes com mais de 1 integrante."""
    escala = _escala_do_periodo(turno, periodo)
    if escala is None:
        return []
    return sorted(f.membro.nome for f in escala.funcoes if f.membro_id)


# --- Motor de recorrencia (matematica pura, estilo Google Agenda) --------------

def test_data_do_periodo_diaria(app, db):
    with app.app_context():
        turno = _criar_turno_teste(1, data_inicio=date(2026, 1, 1), unidade_recorrencia="dia")
        assert data_do_periodo(turno, 0) == date(2026, 1, 1)
        assert data_do_periodo(turno, 4) == date(2026, 1, 5)


def test_data_do_periodo_diaria_com_intervalo(app, db):
    with app.app_context():
        turno = _criar_turno_teste(1, data_inicio=date(2026, 1, 1), unidade_recorrencia="dia", intervalo_recorrencia=2)
        assert [data_do_periodo(turno, i) for i in range(3)] == [date(2026, 1, 1), date(2026, 1, 3), date(2026, 1, 5)]


def test_data_do_periodo_semanal_um_dia_cai_no_weekday_de_inicio(app, db):
    with app.app_context():
        # 2026-01-01 e quinta-feira; sem dias_semana definido, cai no weekday de inicio.
        turno = _criar_turno_teste(1, data_inicio=date(2026, 1, 1), unidade_recorrencia="semana")
        assert [data_do_periodo(turno, i) for i in range(3)] == [date(2026, 1, 1), date(2026, 1, 8), date(2026, 1, 15)]


def test_data_do_periodo_semanal_multiplos_dias(app, db):
    with app.app_context():
        # segunda(0) e quinta(3), a partir de quinta 2026-01-01 -- a 1a segunda
        # (antes do inicio) e descartada, so entra a partir da propria quinta.
        turno = _criar_turno_teste(1, data_inicio=date(2026, 1, 1), unidade_recorrencia="semana", dias_semana="0,3")
        esperado = [date(2026, 1, 1), date(2026, 1, 5), date(2026, 1, 8), date(2026, 1, 12), date(2026, 1, 15), date(2026, 1, 19)]
        assert [data_do_periodo(turno, i) for i in range(6)] == esperado


def test_data_do_periodo_semanal_cruzando_fim_de_semana(app, db):
    with app.app_context():
        # sabado(5) e domingo(6), a partir de sabado 2026-01-03.
        turno = _criar_turno_teste(1, data_inicio=date(2026, 1, 3), unidade_recorrencia="semana", dias_semana="5,6")
        esperado = [date(2026, 1, 3), date(2026, 1, 4), date(2026, 1, 10), date(2026, 1, 11), date(2026, 1, 17)]
        assert [data_do_periodo(turno, i) for i in range(5)] == esperado


def test_data_do_periodo_semanal_com_intervalo(app, db):
    with app.app_context():
        turno = _criar_turno_teste(
            1, data_inicio=date(2026, 1, 1), unidade_recorrencia="semana", dias_semana="3", intervalo_recorrencia=2
        )
        esperado = [date(2026, 1, 1), date(2026, 1, 15), date(2026, 1, 29), date(2026, 2, 12)]
        assert [data_do_periodo(turno, i) for i in range(4)] == esperado


def test_data_do_periodo_mensal_dia_fixo_com_virada_de_ano(app, db):
    with app.app_context():
        turno = _criar_turno_teste(1, data_inicio=date(2026, 1, 31), unidade_recorrencia="mes", modo_mensal="dia_fixo")
        # fevereiro nao tem dia 31 -- cai no dia 28 (2026 nao e bissexto)
        assert data_do_periodo(turno, 1) == date(2026, 2, 28)
        assert data_do_periodo(turno, 12) == date(2027, 1, 31)


def test_data_do_periodo_mensal_enesimo_dia_semana(app, db):
    with app.app_context():
        # 2026-01-22 e a 4a quinta-feira de janeiro.
        turno = _criar_turno_teste(
            1, data_inicio=date(2026, 1, 22), unidade_recorrencia="mes", modo_mensal="enesimo_dia_semana"
        )
        esperado = [date(2026, 1, 22), date(2026, 2, 26), date(2026, 3, 26)]
        assert [data_do_periodo(turno, i) for i in range(3)] == esperado


def test_data_do_periodo_mensal_enesimo_pula_mes_sem_essa_ocorrencia(app, db):
    with app.app_context():
        # 2026-01-29 e a 5a quinta-feira de janeiro -- nem todo mes tem uma.
        turno = _criar_turno_teste(
            1, data_inicio=date(2026, 1, 29), unidade_recorrencia="mes", modo_mensal="enesimo_dia_semana"
        )
        # fev e mar/2026 nao tem 5a quinta -- pulados, sem deixar buraco no indice
        esperado = [date(2026, 1, 29), date(2026, 4, 30), date(2026, 7, 30), date(2026, 10, 29)]
        assert [data_do_periodo(turno, i) for i in range(4)] == esperado


def test_data_do_periodo_mensal_ultimo_dia_semana(app, db):
    with app.app_context():
        turno = _criar_turno_teste(
            1, data_inicio=date(2026, 1, 1), unidade_recorrencia="mes", modo_mensal="ultimo_dia_semana"
        )
        esperado = [date(2026, 1, 29), date(2026, 2, 26), date(2026, 3, 26), date(2026, 4, 30)]
        assert [data_do_periodo(turno, i) for i in range(4)] == esperado


def test_data_do_periodo_anual_com_bissexto(app, db):
    with app.app_context():
        turno = _criar_turno_teste(1, data_inicio=date(2024, 2, 29), unidade_recorrencia="ano")
        # 2025/2026/2027 nao sao bissextos -- clampa pro dia 28
        assert data_do_periodo(turno, 1) == date(2025, 2, 28)
        # 2028 e bissexto de novo -- volta pro dia 29
        assert data_do_periodo(turno, 4) == date(2028, 2, 29)


# --- Termino da recorrencia ------------------------------------------------------

def test_termino_por_ocorrencias_interrompe_geracao(app, db):
    with app.app_context():
        turno = _criar_turno_teste(
            1, data_inicio=date(2026, 1, 1), unidade_recorrencia="dia",
            termino_tipo="ocorrencias", termino_ocorrencias=3,
        )
        assert [data_do_periodo(turno, i) for i in range(3)] == [date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)]
        with pytest.raises(ValueError):
            data_do_periodo(turno, 3)


def test_termino_por_data_interrompe_geracao(app, db):
    with app.app_context():
        turno = _criar_turno_teste(
            1, data_inicio=date(2026, 1, 1), unidade_recorrencia="dia",
            termino_tipo="data", termino_data=date(2026, 1, 3),
        )
        assert data_do_periodo(turno, 2) == date(2026, 1, 3)
        with pytest.raises(ValueError):
            data_do_periodo(turno, 3)


def test_termino_ocorrencias_nao_conta_mes_pulado(app, db):
    with app.app_context():
        # mesmo cenario "pula mes" do teste acima, mas com termino_ocorrencias=2:
        # fev/mar sao pulados (sem 5a quinta) e NAO contam como ocorrencia --
        # a 2a ocorrencia real e abril, nao um mes pulado contado errado.
        turno = _criar_turno_teste(
            1, data_inicio=date(2026, 1, 29), unidade_recorrencia="mes", modo_mensal="enesimo_dia_semana",
            termino_tipo="ocorrencias", termino_ocorrencias=2,
        )
        assert data_do_periodo(turno, 0) == date(2026, 1, 29)
        assert data_do_periodo(turno, 1) == date(2026, 4, 30)
        with pytest.raises(ValueError):
            data_do_periodo(turno, 2)


def test_periodo_da_data_estimativa_nunca_overestima(app, db):
    """periodo_da_data e so uma ESTIMATIVA conservadora agora (nao mais um
    mapeamento exato) -- garante que nunca aponta pra um periodo cuja data
    calculada seja POSTERIOR a data pedida (senao sincronizar_turno pularia
    ocorrencias reais)."""
    with app.app_context():
        turno = _criar_turno_teste(1, data_inicio=date(2026, 1, 1), unidade_recorrencia="semana", dias_semana="0,3")
        for offset_dias in range(0, 60, 7):
            data_alvo = date(2026, 1, 1) + timedelta(days=offset_dias)
            estimativa = periodo_da_data(turno, data_alvo)
            assert data_do_periodo(turno, estimativa) <= data_alvo


# --- dias_semana_efetivos e opcoes_modo_mensal (helpers de UI/defesa) ----------

def test_dias_semana_efetivos_cai_no_weekday_de_inicio_quando_vazio(app, db):
    with app.app_context():
        turno = _criar_turno_teste(1, data_inicio=date(2026, 1, 1), unidade_recorrencia="semana", dias_semana=None)
        assert turno.dias_semana_efetivos == [3]  # 2026-01-01 e quinta (indice 3)


def test_opcoes_modo_mensal_omite_enesimo_quando_ordinal_e_5(app, db):
    with app.app_context():
        opcoes_ordinal_5 = opcoes_modo_mensal(date(2026, 1, 29))  # 5a quinta-feira
        assert [chave for chave, _ in opcoes_ordinal_5] == ["dia_fixo", "ultimo_dia_semana"]

        opcoes_ordinal_4 = opcoes_modo_mensal(date(2026, 1, 22))  # 4a quinta-feira
        assert [chave for chave, _ in opcoes_ordinal_4] == ["dia_fixo", "enesimo_dia_semana", "ultimo_dia_semana"]


def test_opcoes_modo_mensal_completas_sempre_tem_as_3_mesmo_no_ordinal_5(app, db):
    with app.app_context():
        # 2026-01-29 e quinta-feira, 5a ocorrencia do mes -- opcoes_modo_mensal
        # omite "enesimo_dia_semana" aqui (ver teste acima), mas a versao
        # "completas" (usada pelas rotas, pro JS controlar visibilidade sem
        # precisar criar elemento no DOM) sempre traz as 3 chaves.
        opcoes = opcoes_modo_mensal_completas(date(2026, 1, 29))
        assert [chave for chave, _ in opcoes] == ["dia_fixo", "enesimo_dia_semana", "ultimo_dia_semana"]
        rotulo_enesimo = dict(opcoes)["enesimo_dia_semana"]
        assert "5a" in rotulo_enesimo and "quinta" in rotulo_enesimo


def test_opcoes_modo_mensal_completas_bate_com_a_versao_normal_fora_do_ordinal_5(app, db):
    with app.app_context():
        # 4a terca-feira de julho/2026 -- exemplo citado pelo usuario.
        data_referencia = date(2026, 7, 28)
        assert data_referencia.weekday() == 1  # terca
        completas = dict(opcoes_modo_mensal_completas(data_referencia))
        normais = dict(opcoes_modo_mensal(data_referencia))
        assert completas["dia_fixo"] == normais["dia_fixo"] == "Mensalmente no dia 28"
        assert completas["enesimo_dia_semana"] == normais["enesimo_dia_semana"] == "Mensalmente na 4a terca-feira"
        assert completas["ultimo_dia_semana"] == normais["ultimo_dia_semana"] == "Mensalmente na ultima terca-feira"


# --- Formula pura do rodizio -----------------------------------------------------

def test_equipe_do_periodo_rodizio_individual_simples(logged_in_client, app, db):
    """Equipes de 1 pessoa cada -- comportamento identico ao rodizio
    individual de sempre."""
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        turno = _criar_turno_teste(ministerio.id)

        a = _criar_membro_teste(comunidade.id, "Ana")
        b = _criar_membro_teste(comunidade.id, "Bruno")
        c = _criar_membro_teste(comunidade.id, "Carlos")
        _adicionar_a_fila(turno, [a, b, c])

        assert [m.nome for m in equipe_do_periodo(turno, 0).membros_ordenados] == ["Ana"]
        assert [m.nome for m in equipe_do_periodo(turno, 1).membros_ordenados] == ["Bruno"]
        assert [m.nome for m in equipe_do_periodo(turno, 2).membros_ordenados] == ["Carlos"]
        # wraparound do modulo
        assert [m.nome for m in equipe_do_periodo(turno, 3).membros_ordenados] == ["Ana"]
        assert [m.nome for m in equipe_do_periodo(turno, 5).membros_ordenados] == ["Carlos"]


def test_equipe_do_periodo_com_offset(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        turno = _criar_turno_teste(ministerio.id, offset=1)

        a = _criar_membro_teste(comunidade.id, "Ana")
        b = _criar_membro_teste(comunidade.id, "Bruno")
        _adicionar_a_fila(turno, [a, b])

        assert [m.nome for m in equipe_do_periodo(turno, 0).membros_ordenados] == ["Bruno"]
        assert [m.nome for m in equipe_do_periodo(turno, 1).membros_ordenados] == ["Ana"]


def test_equipe_do_periodo_fila_vazia(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        turno = _criar_turno_teste(ministerio.id)

        assert equipe_do_periodo(turno, 0) is None


def test_equipe_do_periodo_rotaciona_grupos_inteiros(logged_in_client, app, db):
    """O caso central deste modulo: uma equipe com varias pessoas revezando
    como GRUPO contra outra equipe -- nao pessoa por pessoa."""
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        turno = _criar_turno_teste(ministerio.id)

        cima = _criar_membro_teste(comunidade.id, "Cima")
        emilly = _criar_membro_teste(comunidade.id, "Emilly")
        outra = _criar_membro_teste(comunidade.id, "Outra")
        _adicionar_equipe(turno, [cima, emilly])  # posicao 0: equipe de 2
        _adicionar_equipe(turno, [outra])  # posicao 1: equipe de 1

        assert sorted(m.nome for m in equipe_do_periodo(turno, 0).membros_ordenados) == ["Cima", "Emilly"]
        assert [m.nome for m in equipe_do_periodo(turno, 1).membros_ordenados] == ["Outra"]
        # wraparound: volta pra equipe {Cima, Emilly}, os dois juntos de novo
        assert sorted(m.nome for m in equipe_do_periodo(turno, 2).membros_ordenados) == ["Cima", "Emilly"]


# --- Motor de sincronizacao (materializacao em Escala/Funcao reais) ------------

def test_sincronizar_turno_cria_ocorrencias(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        turno = _criar_turno_teste(
            ministerio.id, data_inicio=date.today(), unidade_recorrencia="dia", departamento="Midia", nome_funcao="Plantonista"
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


def test_sincronizar_turno_materializa_equipe_inteira_na_mesma_ocorrencia(logged_in_client, app, db):
    """Regressao do bug relatado: uma equipe com 2+ pessoas deve aparecer
    JUNTA, na mesma data/Escala -- nunca uma pessoa por ocorrencia separada
    (que era o comportamento antigo, tratando cada pessoa como uma posicao
    isolada da fila)."""
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        turno = _criar_turno_teste(
            ministerio.id, data_inicio=date.today(), unidade_recorrencia="dia", nome_funcao="Responsavel"
        )
        cima = _criar_membro_teste(comunidade.id, "Cima")
        emilly = _criar_membro_teste(comunidade.id, "Emilly")
        outra = _criar_membro_teste(comunidade.id, "Outra")
        _adicionar_equipe(turno, [cima, emilly])
        _adicionar_equipe(turno, [outra])

        sincronizar_turno(turno, ate_data=date.today() + timedelta(days=3))

        # periodo 0: Cima e Emilly na MESMA Escala (mesma data)
        escala_0 = _escala_do_periodo(turno, 0)
        assert len(escala_0.funcoes) == 2
        assert sorted(f.nome for f in escala_0.funcoes) == ["Responsavel", "Responsavel"]
        assert _membros_materializados(turno, 0) == ["Cima", "Emilly"]

        # periodo 1: so a equipe da Outra
        assert _membros_materializados(turno, 1) == ["Outra"]

        # periodo 2: equipe {Cima, Emilly} de volta, ainda juntos
        assert _membros_materializados(turno, 2) == ["Cima", "Emilly"]


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
            ministerio.id, data_inicio=ha_pouco.date(), unidade_recorrencia="dia", horario=ha_pouco.time()
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


def test_sincronizar_turno_funciona_quando_ate_data_nao_e_ocorrencia_exata_semanal(logged_in_client, app, db):
    """Regressao do bug critico do design inicial: `ate_data` (data de corte
    arbitraria, ex. hoje+90 dias) quase nunca cai exatamente numa ocorrencia
    real pra recorrencias nao-diarias -- sincronizar_turno nao pode depender
    de encontrar o periodo exato dessas datas de corte."""
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        amanha = date.today() + timedelta(days=1)
        turno = _criar_turno_teste(
            ministerio.id, data_inicio=amanha, unidade_recorrencia="semana", dias_semana="0,3"
        )
        a = _criar_membro_teste(comunidade.id, "Ana")
        _adicionar_a_fila(turno, [a])

        ate_data = date.today() + timedelta(days=47)  # dificilmente cai numa ocorrencia seg/qui
        sincronizar_turno(turno, ate_data=ate_data)  # nao pode levantar excecao

        escalas = Escala.query.filter_by(plantao_turno_id=turno.id).all()
        assert len(escalas) > 0
        assert all(e.data <= ate_data for e in escalas)


def test_sincronizar_turno_funciona_quando_ate_data_nao_e_ocorrencia_exata_mensal(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        amanha = date.today() + timedelta(days=1)
        turno = _criar_turno_teste(
            ministerio.id, data_inicio=amanha, unidade_recorrencia="mes", modo_mensal="enesimo_dia_semana"
        )
        a = _criar_membro_teste(comunidade.id, "Ana")
        _adicionar_a_fila(turno, [a])

        ate_data = date.today() + timedelta(days=200)
        sincronizar_turno(turno, ate_data=ate_data)  # nao pode levantar excecao

        escalas = Escala.query.filter_by(plantao_turno_id=turno.id).all()
        assert all(e.data <= ate_data for e in escalas)


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
        a = _criar_membro_teste(comunidade.id, "Ana")
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
            ministerio.id, data_inicio=ha_pouco.date(), unidade_recorrencia="dia", horario=ha_pouco.time()
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


def test_editar_termino_dispara_renumeracao_e_remove_ocorrencias_alem_do_novo_limite(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        turno = _criar_turno_teste(ministerio.id, data_inicio=date.today() + timedelta(days=1))
        a = _criar_membro_teste(comunidade.id, "Ana")
        _adicionar_a_fila(turno, [a])
        sincronizar_turno(turno, ate_data=date.today() + timedelta(days=20))
        assert Escala.query.filter_by(plantao_turno_id=turno.id).count() == 20

        # encurta o termino de "sem fim" pra "apos 5 ocorrencias"
        turno.termino_tipo = "ocorrencias"
        turno.termino_ocorrencias = 5
        db.session.commit()
        preparar_para_renumeracao(turno)
        sincronizar_turno(turno, ate_data=date.today() + timedelta(days=20))

        restantes = Escala.query.filter_by(plantao_turno_id=turno.id).order_by(Escala.plantao_periodo).all()
        assert len(restantes) == 5
        assert all(e.plantao_periodo < 5 for e in restantes)


def test_adicionar_membro_na_fila_reajusta_so_o_futuro(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        agora = datetime.now()
        ha_pouco = agora - timedelta(minutes=5)

        turno = _criar_turno_teste(
            ministerio.id, data_inicio=ha_pouco.date(), unidade_recorrencia="dia", horario=ha_pouco.time()
        )
        a = _criar_membro_teste(comunidade.id, "Ana")
        _adicionar_a_fila(turno, [a])
        sincronizar_turno(turno, ate_data=date.today() + timedelta(days=2))
        assert _escala_do_periodo(turno, 0).funcoes[0].membro.nome == "Ana"  # ja ocorrido

        b = _criar_membro_teste(comunidade.id, "Bruno")
        _adicionar_a_fila(turno, [b])
        sincronizar_turno(turno, ate_data=date.today() + timedelta(days=2))
        db.session.expire_all()

        assert _escala_do_periodo(turno, 0).funcoes[0].membro.nome == "Ana"  # passado intocado
        assert _escala_do_periodo(turno, 1).funcoes[0].membro.nome == "Bruno"  # futuro reajustado


# --- Ausencia numa ocorrencia gerada (fluxo generico de escala) -----------------
#
# Nao ha mais remanejamento automatico (trocar com o periodo seguinte): a
# ausencia de uma pessoa numa ocorrencia gerada por rodizio usa o MESMO
# fluxo generico de qualquer escala manual (escala.routes.remover_membro) --
# so aquela pessoa sai (vaga fica aberta), o resto da equipe (se houver)
# continua normalmente, e a Escala e fixada pra o proximo sync nao restaurar
# a pessoa removida.

def test_remover_pessoa_de_ocorrencia_gerada_deixa_vaga_aberta_e_fixa(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        turno = _criar_turno_teste(ministerio.id, data_inicio=date.today() + timedelta(days=1))
        a = _criar_membro_teste(comunidade.id, "Ana")
        _adicionar_a_fila(turno, [a])
        sincronizar_turno(turno, ate_data=date.today() + timedelta(days=2))

        escala = _escala_do_periodo(turno, 0)
        funcao = escala.funcoes[0]
        assert escala.plantao_fixado is False

        response = logged_in_client.post(
            f"/escala/funcao/{funcao.id}/remover", data={}, follow_redirects=True
        )
        assert response.status_code == 200

        db.session.expire_all()
        escala_atualizada = _escala_do_periodo(turno, 0)
        assert escala_atualizada.funcoes[0].membro_id is None  # vaga aberta
        assert escala_atualizada.plantao_fixado is True  # sync nao restaura Ana


def test_remover_uma_pessoa_de_equipe_multipla_mantem_resto_do_grupo(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        turno = _criar_turno_teste(ministerio.id, data_inicio=date.today() + timedelta(days=1))
        cima = _criar_membro_teste(comunidade.id, "Cima")
        emilly = _criar_membro_teste(comunidade.id, "Emilly")
        _adicionar_equipe(turno, [cima, emilly])
        sincronizar_turno(turno, ate_data=date.today() + timedelta(days=2))

        escala = _escala_do_periodo(turno, 0)
        funcao_cima = next(f for f in escala.funcoes if f.membro.nome == "Cima")

        logged_in_client.post(f"/escala/funcao/{funcao_cima.id}/remover", data={}, follow_redirects=True)

        db.session.expire_all()
        escala_atualizada = _escala_do_periodo(turno, 0)
        nomes_restantes = sorted(f.membro.nome for f in escala_atualizada.funcoes if f.membro_id)
        assert nomes_restantes == ["Emilly"]  # Cima saiu, Emilly continua
        assert escala_atualizada.plantao_fixado is True


def test_sync_nao_restaura_pessoa_removida_manualmente(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        turno = _criar_turno_teste(ministerio.id, data_inicio=date.today() + timedelta(days=1))
        a = _criar_membro_teste(comunidade.id, "Ana")
        _adicionar_a_fila(turno, [a])
        sincronizar_turno(turno, ate_data=date.today() + timedelta(days=2))

        escala = _escala_do_periodo(turno, 0)
        funcao = escala.funcoes[0]
        logged_in_client.post(f"/escala/funcao/{funcao.id}/remover", data={}, follow_redirects=True)

        # sync roda de novo (ex: tick do agendador) -- nao deve reatribuir Ana
        sincronizar_turno(turno, ate_data=date.today() + timedelta(days=2))
        db.session.expire_all()

        assert _escala_do_periodo(turno, 0).funcoes[0].membro_id is None


# --- Exclusao de turno ------------------------------------------------------------

def test_excluir_turno_via_rota_preserva_passado_remove_futuro(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        agora = datetime.now()
        ha_pouco = agora - timedelta(minutes=5)
        turno = _criar_turno_teste(
            ministerio.id, data_inicio=ha_pouco.date(), unidade_recorrencia="dia", horario=ha_pouco.time()
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

def test_criar_turno_diario_via_rota_materializa_escalas(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)

        response = logged_in_client.post(
            f"/plantao/ministerio/{ministerio.id}/nova",
            data=_payload_turno(
                nome="Plantao Manha", departamento="Midia", nome_funcao="Plantonista",
                data_inicio=date.today().isoformat(), horario="08:00",
            ),
            follow_redirects=True,
        )
        assert response.status_code == 200
        turno = TurnoPlantao.query.filter_by(nome="Plantao Manha", ministerio_id=ministerio.id).first()
        assert turno is not None
        assert turno.departamento == "Midia"
        assert turno.unidade_recorrencia == "dia"
        assert Escala.query.filter_by(plantao_turno_id=turno.id).count() > 0


def test_criar_turno_semanal_via_rota_com_dias_semana(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)

        response = logged_in_client.post(
            f"/plantao/ministerio/{ministerio.id}/nova",
            data=_payload_turno(
                nome="Plantao Semanal", unidade_recorrencia="semana",
                data_inicio=date(2026, 1, 1).isoformat(), **{"dias_semana": ["0", "3"]}
            ),
            follow_redirects=True,
        )
        assert response.status_code == 200
        turno = TurnoPlantao.query.filter_by(nome="Plantao Semanal").first()
        assert turno is not None
        assert turno.dias_semana_efetivos == [0, 3]


def test_criar_turno_mensal_via_rota_com_modo_mensal(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)

        response = logged_in_client.post(
            f"/plantao/ministerio/{ministerio.id}/nova",
            data=_payload_turno(
                nome="Plantao Mensal", unidade_recorrencia="mes", modo_mensal="ultimo_dia_semana",
                data_inicio=date(2026, 1, 1).isoformat(),
            ),
            follow_redirects=True,
        )
        assert response.status_code == 200
        turno = TurnoPlantao.query.filter_by(nome="Plantao Mensal").first()
        assert turno is not None
        assert turno.modo_mensal == "ultimo_dia_semana"


def test_criar_turno_com_termino_por_data_via_rota(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)

        response = logged_in_client.post(
            f"/plantao/ministerio/{ministerio.id}/nova",
            data=_payload_turno(
                nome="Plantao Com Fim", termino_tipo="data", termino_data=date(2026, 6, 1).isoformat(),
                data_inicio=date(2026, 1, 1).isoformat(),
            ),
            follow_redirects=True,
        )
        assert response.status_code == 200
        turno = TurnoPlantao.query.filter_by(nome="Plantao Com Fim").first()
        assert turno is not None
        assert turno.termino_tipo == "data"
        assert turno.termino_data == date(2026, 6, 1)


# --- Turno nascido de uma Escala (reaproveita a equipe ja escalada) ------------

def _criar_escala_com_dois_escalados(cliente, ministerio_id, nome="Escala Louvor"):
    """Cria uma Escala Rapida (departamento Louvor) e escala 2 pessoas em
    funcoes dela -- usada pra testar o turno de rodizio 'nascendo' a partir
    de uma escala existente."""
    escala = _criar_escala(cliente, ministerio_id, nome, departamento="Louvor")
    comunidade_id = escala.ministerio.comunidade_id
    ana = _criar_membro(cliente, comunidade_id, "Ana")
    bruno = _criar_membro(cliente, comunidade_id, "Bruno")
    _escalar(cliente, _funcao_por_nome(escala, "Baixo").id, ana.id)
    _escalar(cliente, _funcao_por_nome(escala, "Bateria").id, bruno.id)
    return escala, ana, bruno


def test_form_novo_turno_pre_preenche_a_partir_da_escala_de_origem(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        escala, ana, bruno = _criar_escala_com_dois_escalados(logged_in_client, ministerio.id)

        response = logged_in_client.get(f"/plantao/ministerio/{ministerio.id}/nova?escala_id={escala.id}")
        html = response.data.decode("utf-8")
        assert response.status_code == 200
        assert "Escala Louvor" in html
        assert "Nascendo a partir de" in html
        assert "recadastrar ninguem" in html


def test_criar_turno_a_partir_de_escala_semeia_fila_com_os_escalados(logged_in_client, app, db):
    """As pessoas ja escaladas na Escala de origem viram UMA UNICA equipe
    (nao posicoes separadas) -- e assim que "criar turno com esta equipe"
    faz elas continuarem aparecendo juntas nas ocorrencias geradas, em vez de
    o rodizio passar a alterna-las em datas separadas."""
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        escala, ana, bruno = _criar_escala_com_dois_escalados(logged_in_client, ministerio.id)

        data_inicio = date.today() + timedelta(days=30)
        response = logged_in_client.post(
            f"/plantao/ministerio/{ministerio.id}/nova?escala_id={escala.id}",
            data=_payload_turno(nome="Rodizio Louvor", departamento="Louvor", data_inicio=data_inicio.isoformat()),
            follow_redirects=True,
        )
        assert response.status_code == 200

        turno = TurnoPlantao.query.filter_by(nome="Rodizio Louvor", ministerio_id=ministerio.id).first()
        assert turno is not None
        assert len(turno.fila) == 1  # UMA equipe, nao duas posicoes
        nomes_da_equipe = [m.membro.nome for m in turno.fila[0].integrantes]
        assert nomes_da_equipe == ["Ana", "Bruno"]  # mesma ordem das funcoes (Baixo antes de Bateria)

        # ja materializou ocorrencias usando essa fila (sem precisar montar
        # a fila manualmente na tela seguinte) -- Ana e Bruno na MESMA Escala
        primeira = Escala.query.filter_by(plantao_turno_id=turno.id, plantao_periodo=0).first()
        assert sorted(f.membro.nome for f in primeira.funcoes if f.membro_id) == ["Ana", "Bruno"]


def test_criar_turno_a_partir_de_escala_ignora_funcao_repetida_e_vazia(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        escala = _criar_escala(logged_in_client, ministerio.id, "Escala Louvor", departamento="Louvor")
        ana = _criar_membro(logged_in_client, comunidade.id, "Ana")
        # Ana escalada em duas funcoes -- so deve entrar 1 vez na fila. As
        # demais funcoes ficam sem ninguem (nao entram na fila).
        _escalar(logged_in_client, _funcao_por_nome(escala, "Baixo").id, ana.id)
        _escalar(logged_in_client, _funcao_por_nome(escala, "Bateria").id, ana.id)

        logged_in_client.post(
            f"/plantao/ministerio/{ministerio.id}/nova?escala_id={escala.id}",
            data=_payload_turno(
                nome="Rodizio Ana", departamento="Louvor",
                data_inicio=(date.today() + timedelta(days=30)).isoformat(),
            ),
            follow_redirects=True,
        )

        turno = TurnoPlantao.query.filter_by(nome="Rodizio Ana").first()
        assert len(turno.fila) == 1
        assert [m.membro.nome for m in turno.fila[0].integrantes] == ["Ana"]


def test_usuario_nao_consegue_usar_escala_de_outra_conta_como_origem_do_turno(
    logged_in_client, outro_logged_in_client, app, db
):
    with sessao_isolada(app):
        comunidade = _criar_comunidade(logged_in_client, "Comunidade Ana")
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        escala, _, _ = _criar_escala_com_dois_escalados(logged_in_client, ministerio.id)
        escala_id = escala.id

    with sessao_isolada(app):
        comunidade_b = _criar_comunidade(outro_logged_in_client, "Comunidade Bruno")
        ministerio_b = _criar_ministerio(outro_logged_in_client, comunidade_b.id)
        response = outro_logged_in_client.get(
            f"/plantao/ministerio/{ministerio_b.id}/nova?escala_id={escala_id}"
        )
        assert response.status_code == 404


def test_escala_de_ministerio_diferente_nao_pode_ser_origem_do_turno(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio_a = _criar_ministerio(logged_in_client, comunidade.id, "Ministerio A")
        ministerio_b = _criar_ministerio(logged_in_client, comunidade.id, "Ministerio B")
        escala, _, _ = _criar_escala_com_dois_escalados(logged_in_client, ministerio_a.id)

        response = logged_in_client.get(f"/plantao/ministerio/{ministerio_b.id}/nova?escala_id={escala.id}")
        assert response.status_code == 404


def test_link_para_criar_turno_aparece_na_escala_com_gente_escalada(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        escala, _, _ = _criar_escala_com_dois_escalados(logged_in_client, ministerio.id)

        response = logged_in_client.get(f"/escala/{escala.id}")
        html = response.data.decode("utf-8")
        assert f"/plantao/ministerio/{ministerio.id}/nova?escala_id={escala.id}" in html
        assert "Criar turno de rodizio com esta equipe" in html


def test_link_para_criar_turno_nao_aparece_em_escala_sem_ninguem_escalado(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        escala = _criar_escala(logged_in_client, ministerio.id, "Escala Vazia", departamento="Louvor")

        response = logged_in_client.get(f"/escala/{escala.id}")
        html = response.data.decode("utf-8")
        assert "Criar turno de rodizio com esta equipe" not in html


def _equipe_membro_de(turno, membro_id):
    return (
        EquipeMembro.query.join(EquipeTurno)
        .filter(EquipeTurno.turno_id == turno.id, EquipeMembro.membro_id == membro_id)
        .first()
    )


def test_adicionar_e_remover_membro_da_fila_via_rota(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        turno = _criar_turno_teste(ministerio.id, data_inicio=date.today())
        membro = _criar_membro_teste(comunidade.id, "Ana")

        response = logged_in_client.post(
            f"/plantao/{turno.id}/fila/adicionar",
            data={"membro_id": membro.id, "equipe_turno_id": "0"},  # 0 = nova equipe
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert _equipe_membro_de(turno, membro.id) is not None
        assert Escala.query.filter_by(plantao_turno_id=turno.id).count() > 0

        item = _equipe_membro_de(turno, membro.id)
        logged_in_client.post(
            f"/plantao/{turno.id}/fila/{item.id}/remover", data={}, follow_redirects=True
        )
        assert _equipe_membro_de(turno, membro.id) is None
        assert EquipeTurno.query.filter_by(turno_id=turno.id).count() == 0  # equipe vazia tambem some


def test_adicionar_segundo_membro_na_mesma_equipe_via_rota(logged_in_client, app, db):
    """Escolher uma equipe ja existente (em vez de "+ Nova equipe") junta a
    pessoa ao MESMO grupo -- e assim que 2 pessoas passam a revezar juntas."""
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        turno = _criar_turno_teste(ministerio.id, data_inicio=date.today())
        cima = _criar_membro_teste(comunidade.id, "Cima")
        emilly = _criar_membro_teste(comunidade.id, "Emilly")

        logged_in_client.post(
            f"/plantao/{turno.id}/fila/adicionar",
            data={"membro_id": cima.id, "equipe_turno_id": "0"},
            follow_redirects=True,
        )
        equipe = EquipeTurno.query.filter_by(turno_id=turno.id).first()

        logged_in_client.post(
            f"/plantao/{turno.id}/fila/adicionar",
            data={"membro_id": emilly.id, "equipe_turno_id": str(equipe.id)},
            follow_redirects=True,
        )

        db.session.expire_all()
        assert EquipeTurno.query.filter_by(turno_id=turno.id).count() == 1  # uma unica equipe
        nomes = sorted(m.nome for m in EquipeTurno.query.get(equipe.id).membros_ordenados)
        assert nomes == ["Cima", "Emilly"]


def test_editar_turno_via_rota(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        turno = _criar_turno_teste(ministerio.id, data_inicio=date.today() + timedelta(days=1))

        response = logged_in_client.post(
            f"/plantao/{turno.id}/editar",
            data=_payload_turno(
                nome="Turno Renomeado", unidade_recorrencia="semana", **{"dias_semana": ["1", "4"]},
                data_inicio=(date.today() + timedelta(days=1)).isoformat(),
            ),
            follow_redirects=True,
        )
        assert response.status_code == 200
        turno_atualizado = db.session.get(TurnoPlantao, turno.id)
        assert turno_atualizado.nome == "Turno Renomeado"
        assert turno_atualizado.unidade_recorrencia == "semana"
        assert turno_atualizado.dias_semana_efetivos == [1, 4]


def test_detalhe_do_turno_mostra_ocorrencias_passadas_e_futuras(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        turno = _criar_turno_teste(ministerio.id, nome="Turno Historico", data_inicio=date.today())
        _adicionar_a_fila(turno, [_criar_membro_teste(comunidade.id, "Ana")])

        # sincronizar_turno nunca gera retroativo (por design -- so materializa
        # a partir de hoje) -- uma ocorrencia so vira "passado" com o tempo real
        # passando. Simula isso criando uma ocorrencia ja materializada com
        # data no passado direto, como se tivesse sido gerada ha dias atras.
        data_passada = date.today() - timedelta(days=10)
        escala_passada = Escala(
            ministerio_id=ministerio.id, nome=turno.nome, departamento=turno.departamento,
            data=data_passada, horario=turno.horario,
            plantao_turno_id=turno.id, plantao_periodo=-1,
        )
        db.session.add(escala_passada)
        db.session.flush()
        db.session.add(Funcao(escala_id=escala_passada.id, nome=turno.nome_funcao, ordem=0))
        db.session.commit()

        sincronizar_turno(turno, ate_data=date.today() + timedelta(days=3))

        response = logged_in_client.get(f"/plantao/{turno.id}")
        html = response.data.decode("utf-8")
        assert response.status_code == 200

        futura = Escala.query.filter(
            Escala.plantao_turno_id == turno.id, Escala.data >= date.today()
        ).first()
        assert futura is not None
        assert data_passada.strftime("%d/%m") in html
        assert futura.data.strftime("%d/%m") in html
        assert "ja ocorreu" in html  # marcador na ocorrencia passada


def test_usuario_nao_consegue_ver_turno_de_outra_conta(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade = _criar_comunidade(logged_in_client, "Comunidade Ana")
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        turno = _criar_turno_teste(ministerio.id)
        turno_id = turno.id

    with sessao_isolada(app):
        assert outro_logged_in_client.get(f"/plantao/{turno_id}").status_code == 404
        assert outro_logged_in_client.get(f"/plantao/{turno_id}/editar").status_code == 404


def test_usuario_nao_consegue_mexer_na_fila_de_turno_de_outra_conta(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade = _criar_comunidade(logged_in_client, "Comunidade Ana")
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        turno = _criar_turno_teste(ministerio.id, data_inicio=date.today())
        a = _criar_membro_teste(comunidade.id, "Ana")
        _adicionar_a_fila(turno, [a])
        turno_id = turno.id
        equipe_membro_id = _equipe_membro_de(turno, a.id).id

    with sessao_isolada(app):
        response = outro_logged_in_client.post(
            f"/plantao/{turno_id}/fila/adicionar",
            data={"membro_id": a.id, "equipe_turno_id": "0"},
            follow_redirects=True,
        )
        assert response.status_code == 404

        response = outro_logged_in_client.post(
            f"/plantao/{turno_id}/fila/{equipe_membro_id}/remover", data={}, follow_redirects=True
        )
        assert response.status_code == 404

    with sessao_isolada(app):
        assert _equipe_membro_de(db.session.get(TurnoPlantao, turno_id), a.id) is not None


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
