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
from app.escala.models import Escala, Funcao, STATUS_PADRAO
from app.plantao.models import TurnoPlantao, data_do_periodo, periodo_da_data, equipe_do_periodo

JANELA_GERACAO_DIAS = 90


def _materializar_periodo(turno, periodo, data_periodo):
    """Cria a Escala+Funcao(oes) de um periodo que ainda nao existe -- 1
    Funcao por integrante da equipe sorteada (ver equipe_do_periodo), todas
    na mesma Escala, pra equipe inteira aparecer agrupada na mesma data.

    Recebe `data_periodo` ja calculado pelo chamador (nunca recalcula via
    data_do_periodo aqui) -- sincronizar_turno ja percorre os periodos via
    data_do_periodo pra decidir ate onde materializar; recalcular de novo
    aqui dentro do loop viraria O(n^2) pra recorrencias sem formula fechada."""
    equipe = equipe_do_periodo(turno, periodo)
    membros = equipe.membros_ordenados if equipe else []

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
    db.session.flush()  # garante escala.id antes de criar as funcoes

    if membros:
        for ordem, membro in enumerate(membros):
            db.session.add(Funcao(
                escala_id=escala.id, nome=turno.nome_funcao, ordem=ordem,
                membro_id=membro.id, status=STATUS_PADRAO,
            ))
    else:
        db.session.add(Funcao(escala_id=escala.id, nome=turno.nome_funcao, ordem=0))
    db.session.flush()
    return escala


def _atualizar_periodo_existente(turno, escala, data_periodo):
    """Recalcula uma Escala nao-fixada e ainda nao ocorrida a partir da config
    atual do turno -- so escreve/reseta notificacao se algo realmente mudou
    (idempotencia e obrigatoria aqui: essa funcao roda a cada 15 min pelo
    agendador; sem a checagem, resetaria notificado_24h_em/16h_em a cada tick
    e causaria renotificacao em loop). Recebe `data_periodo` ja calculado
    pelo chamador, mesmo motivo de _materializar_periodo.

    So chega aqui uma Escala nunca tocada manualmente (a 1a edicao manual --
    remover/adicionar alguem, editar nome/data -- marca plantao_fixado=True
    e o sync para de considerar essa Escala pra sempre, ver sincronizar_turno
    abaixo) -- entao, se a composicao da equipe mudou, e seguro recriar as
    Funcao do zero a partir dela: nao ha status/atribuicao anterior que valha
    a pena preservar num slot que ainda era so-formula."""
    from app.escala.routes import enviar_notificacao_de_alteracao

    periodo = escala.plantao_periodo
    equipe = equipe_do_periodo(turno, periodo)
    membros_novos = equipe.membros_ordenados if equipe else []
    ids_novos = [m.id for m in membros_novos]

    funcoes_atuais = list(escala.funcoes)
    ids_atuais = [f.membro_id for f in funcoes_atuais if f.membro_id is not None]

    mudou_data_horario = escala.data != data_periodo or escala.horario != turno.horario
    mudou_nome = escala.nome != turno.nome
    mudou_departamento = escala.departamento != turno.departamento
    mudou_nome_funcao = any(f.nome != turno.nome_funcao for f in funcoes_atuais)
    mudou_equipe = ids_novos != ids_atuais

    if not (mudou_data_horario or mudou_nome or mudou_departamento or mudou_nome_funcao or mudou_equipe):
        return

    data_antiga, horario_antigo = escala.data, escala.horario

    escala.nome = turno.nome
    escala.departamento = turno.departamento
    escala.data = data_periodo
    escala.horario = turno.horario

    if mudou_equipe:
        for funcao in funcoes_atuais:
            db.session.delete(funcao)
        db.session.flush()
        if membros_novos:
            for ordem, membro in enumerate(membros_novos):
                db.session.add(Funcao(
                    escala_id=escala.id, nome=turno.nome_funcao, ordem=ordem,
                    membro_id=membro.id, status=STATUS_PADRAO,
                ))
        else:
            db.session.add(Funcao(escala_id=escala.id, nome=turno.nome_funcao, ordem=0))
    elif mudou_nome_funcao:
        for funcao in funcoes_atuais:
            funcao.nome = turno.nome_funcao

    if mudou_data_horario or mudou_equipe:
        escala.notificado_24h_em = None
        escala.notificado_16h_em = None

    if mudou_data_horario:
        enviar_notificacao_de_alteracao(escala, data_antiga, horario_antigo)


def sincronizar_turno(turno, ate_data=None):
    """Garante uma Escala real para cada periodo do turno entre hoje e
    ate_data (padrao: hoje + JANELA_GERACAO_DIAS). Cria as que faltam,
    atualiza (idempotentemente) as nao-fixadas ainda nao ocorridas, nunca
    mexe nas ja ocorridas nem nas fixadas (excecao pontual de ausencia ou
    edicao manual).

    Caminha periodo a periodo via data_do_periodo (nao usa mais range() com
    limites pre-calculados) -- necessario porque, com a recorrencia flexivel
    (semana com varios dias, mes com modo enesimo-dia-da-semana), nao da mais
    pra garantir que uma data de corte arbitraria como `ate_data` caia
    exatamente numa ocorrencia. Para no primeiro ValueError (a recorrencia
    terminou, por data ou por numero de ocorrencias) ou ao ultrapassar
    ate_data. `periodo_da_data` aqui e so uma estimativa conservadora (nunca
    overestima) do ponto de partida -- comecar um pouco antes do real custa
    so algumas iteracoes descartadas, nunca incorretude.
    """
    agora = datetime.now()
    hoje = agora.date()
    ate_data = ate_data or hoje + timedelta(days=JANELA_GERACAO_DIAS)

    data_inicial = max(turno.data_inicio, hoje)
    if data_inicial > ate_data:
        db.session.commit()
        return

    existentes = {
        escala.plantao_periodo: escala
        for escala in Escala.query.filter(
            Escala.plantao_turno_id == turno.id, Escala.plantao_periodo.isnot(None)
        ).all()
    }

    periodo = periodo_da_data(turno, data_inicial)
    while True:
        try:
            data_periodo = data_do_periodo(turno, periodo)
        except ValueError:
            break  # recorrencia terminou (por data ou por numero de ocorrencias)

        if data_periodo > ate_data:
            break

        if data_periodo >= data_inicial:
            escala = existentes.get(periodo)

            if escala is None:
                _materializar_periodo(turno, periodo, data_periodo)
            elif escala.data_hora and escala.data_hora <= agora:
                pass  # ja ocorreu -- historico intocavel
            elif escala.plantao_fixado:
                pass  # excecao pontual preservada
            else:
                _atualizar_periodo_existente(turno, escala, data_periodo)

        periodo += 1

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
