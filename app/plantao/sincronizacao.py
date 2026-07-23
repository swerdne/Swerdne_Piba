"""Motor de sincronizacao do rodizio.

Materializa a REGRA de um TurnoPlantao (fila, offset, recorrencia,
departamento) em Escala/Funcao reais (app/escala/models.py), pra cada
ocorrencia aparecer no calendario/lista do Ministerio (mesma cor por
departamento) e ser notificada pelo agendador 24h/16h ja existente
(app/escala/agendador.py) -- nao existe mais um scheduler nem uma tabela de
controle de notificacao proprios do plantao.

Chamado em 3 situacoes: ao criar/editar o turno ou a fila (app/plantao/routes.py),
e a cada tick do agendador unico (rola a janela de geracao pra frente com o
tempo -- ver sincronizar_todos_os_turnos_ativos).
"""
from datetime import datetime, timedelta

from app.extensions import db
from app.escala.models import Escala, Funcao, STATUS_PADRAO, trocar_atribuicao
from app.plantao.models import TurnoPlantao, data_do_periodo, periodo_da_data, membro_do_periodo

JANELA_GERACAO_DIAS = 90


def _materializar_periodo(turno, periodo):
    """Cria a Escala+Funcao de um periodo que ainda nao existe."""
    data_periodo = data_do_periodo(turno, periodo)
    membro = membro_do_periodo(turno, periodo)

    escala = Escala(
        ministerio_id=turno.ministerio_id,
        nome=turno.nome,
        departamento=turno.departamento,
        data=data_periodo,
        horario=turno.horario,
        plantao_turno_id=turno.id,
        plantao_periodo=periodo,
    )
    db.session.add(escala)
    db.session.flush()  # garante escala.id antes de criar a funcao

    funcao = Funcao(
        escala_id=escala.id,
        nome=turno.nome_funcao,
        ordem=0,
        membro_id=membro.id if membro else None,
        status=STATUS_PADRAO if membro else None,
    )
    db.session.add(funcao)
    db.session.flush()
    return escala


def _atualizar_periodo_existente(turno, escala):
    """Recalcula uma Escala nao-fixada e ainda nao ocorrida a partir da config
    atual do turno -- so escreve/reseta notificacao se algo realmente mudou
    (idempotencia e obrigatoria aqui: essa funcao roda a cada 15 min pelo
    agendador; sem a checagem, resetaria notificado_24h_em/16h_em a cada tick
    e causaria renotificacao em loop)."""
    from app.escala.routes import enviar_notificacao_de_alteracao

    periodo = escala.plantao_periodo
    data_periodo = data_do_periodo(turno, periodo)
    membro = membro_do_periodo(turno, periodo)
    funcao = escala.funcoes[0]
    membro_id_novo = membro.id if membro else None

    mudou_data_horario = escala.data != data_periodo or escala.horario != turno.horario
    mudou_nome = escala.nome != turno.nome
    mudou_departamento = escala.departamento != turno.departamento
    mudou_nome_funcao = funcao.nome != turno.nome_funcao
    mudou_membro = funcao.membro_id != membro_id_novo

    if not (mudou_data_horario or mudou_nome or mudou_departamento or mudou_nome_funcao or mudou_membro):
        return

    data_antiga, horario_antigo = escala.data, escala.horario

    escala.nome = turno.nome
    escala.departamento = turno.departamento
    escala.data = data_periodo
    escala.horario = turno.horario
    funcao.nome = turno.nome_funcao

    if mudou_membro:
        funcao.membro_id = membro_id_novo
        funcao.status = STATUS_PADRAO if membro else None
        funcao.notificado_em = None

    if mudou_data_horario or mudou_membro:
        escala.notificado_24h_em = None
        escala.notificado_16h_em = None

    if mudou_data_horario:
        enviar_notificacao_de_alteracao(escala, data_antiga, horario_antigo)


def sincronizar_turno(turno, ate_data=None):
    """Garante uma Escala real para cada periodo do turno entre hoje e
    ate_data (padrao: hoje + JANELA_GERACAO_DIAS). Cria as que faltam,
    atualiza (idempotentemente) as nao-fixadas ainda nao ocorridas, nunca
    mexe nas ja ocorridas nem nas fixadas (excecao pontual de ausencia ou
    edicao manual)."""
    agora = datetime.now()
    hoje = agora.date()
    ate_data = ate_data or hoje + timedelta(days=JANELA_GERACAO_DIAS)

    data_inicial = max(turno.data_inicio, hoje)
    if data_inicial > ate_data:
        db.session.commit()
        return

    periodo_inicial = periodo_da_data(turno, data_inicial)
    periodo_final = periodo_da_data(turno, ate_data)

    existentes = {
        escala.plantao_periodo: escala
        for escala in Escala.query.filter(
            Escala.plantao_turno_id == turno.id, Escala.plantao_periodo.isnot(None)
        ).all()
    }

    for periodo in range(periodo_inicial, periodo_final + 1):
        escala = existentes.get(periodo)

        if escala is None:
            _materializar_periodo(turno, periodo)
            continue

        if escala.data_hora and escala.data_hora <= agora:
            continue  # ja ocorreu -- historico intocavel

        if escala.plantao_fixado:
            continue  # excecao pontual preservada

        _atualizar_periodo_existente(turno, escala)

    db.session.commit()


def sincronizar_todos_os_turnos_ativos():
    """Chamada a cada tick do agendador unico (app/escala/agendador.py) --
    rola a janela de geracao de todo turno pra frente com o tempo."""
    for turno in TurnoPlantao.query.all():
        sincronizar_turno(turno)


def preparar_para_renumeracao(turno):
    """Chamada ANTES de sincronizar_turno quando data_inicio/recorrencia do
    turno mudam: a numeracao de periodo passa a significar outra data, entao
    as Escala ja geradas precisam ser desvinculadas da contagem antiga.

    Fixadas ou ja ocorridas -- viram historico solto (plantao_periodo=NULL,
    mantendo plantao_turno_id como proveniencia); nao colidem mais com a
    UniqueConstraint da nova numeracao e o sync nunca mais as reconsidera.
    Futuras nao-fixadas -- eram so previsao, sao apagadas e recriadas do
    zero pelo sync com a nova numeracao.
    """
    agora = datetime.now()
    for escala in list(turno.escalas_geradas):
        if escala.plantao_periodo is None:
            continue
        ja_ocorreu = escala.data_hora and escala.data_hora <= agora
        if escala.plantao_fixado or ja_ocorreu:
            escala.plantao_periodo = None
        else:
            db.session.delete(escala)
    db.session.commit()


def _escala_do_periodo(turno, periodo):
    escala = Escala.query.filter_by(plantao_turno_id=turno.id, plantao_periodo=periodo).first()
    if escala is None:
        escala = _materializar_periodo(turno, periodo)
    return escala


def marcar_ausencia(turno, periodo):
    """Remanejamento por falta: troca a atribuicao do periodo informado com a
    do periodo seguinte (quem cobriria o seguinte cobre este no lugar; quem
    faltou passa a cobrir o seguinte). Le o estado ATUAL materializado (nunca
    a formula pura -- o periodo pode ja ter sido remanejado antes por uma
    ausencia anterior) e marca as duas Escala como fixadas, preservando a
    regra base (fila/offset) intocada."""
    agora = datetime.now()

    escala_atual = _escala_do_periodo(turno, periodo)
    if escala_atual.data_hora and escala_atual.data_hora <= agora:
        raise ValueError("Esse periodo ja ocorreu, nao e possivel remanejar.")

    escala_seguinte = _escala_do_periodo(turno, periodo + 1)

    funcao_atual = escala_atual.funcoes[0]
    funcao_seguinte = escala_seguinte.funcoes[0]

    if funcao_atual.membro_id is None or funcao_seguinte.membro_id is None:
        raise ValueError("Turno sem membros suficientes na fila para remanejar.")

    trocar_atribuicao(funcao_atual, funcao_seguinte)

    for escala in (escala_atual, escala_seguinte):
        escala.plantao_fixado = True
        escala.notificado_24h_em = None
        escala.notificado_16h_em = None

    db.session.commit()
