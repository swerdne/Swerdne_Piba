"""Testes do agendador de notificacoes automaticas (24h/16h antes do evento).

Nao usar `with app.app_context():` aqui -- o fixture `app` ja mantem um
contexto aberto, e `_verificar_e_notificar` empurra o seu proprio por dentro.

Apos chamar `_verificar_e_notificar`, sempre `db.session.expire_all()` antes
de reconsultar: como o objeto `escala` ja esta no identity map da sessao de
teste (foi criado nela), `db.session.get()` devolveria a copia em cache sem
refletir o commit feito pela sessao aninhada do agendador.
"""
from datetime import datetime, timedelta

from app.comunidade.models import criar_comunidade
from app.ministerio.models import criar_ministerio
from app.escala.agendador import _verificar_e_notificar
from app.escala.models import Escala, Funcao, Membro, criar_escala_com_funcoes_padrao


def _criar_ministerio_teste(usuario_id):
    comunidade = criar_comunidade(usuario_id=usuario_id, nome="Comunidade Teste")
    return criar_ministerio(comunidade_id=comunidade.id, nome="Ministerio Teste")


def _escalar_membro(escala, nome_funcao, nome_membro="Fulano", email="fulano@example.com"):
    from app.extensions import db

    funcao = Funcao.query.filter_by(escala_id=escala.id, nome=nome_funcao).first()
    membro = Membro(comunidade_id=escala.ministerio.comunidade_id, nome=nome_membro, telefone="", email=email)
    db.session.add(membro)
    db.session.flush()
    funcao.membro_id = membro.id
    funcao.status = "nao_notificado"
    db.session.commit()
    return funcao


def test_notifica_automaticamente_dentro_da_janela_de_24h(logged_in_client, app, db):
    from app.auth.models import User

    usuario = User.query.filter_by(username="ana").first()
    ministerio = _criar_ministerio_teste(usuario.id)
    daqui_24h = datetime.now() + timedelta(hours=24, minutes=2)

    escala = criar_escala_com_funcoes_padrao(
        ministerio_id=ministerio.id, nome="Culto Teste", departamento="Louvor",
        data=daqui_24h.date(), horario=daqui_24h.time(),
    )
    _escalar_membro(escala, "Baixo")
    assert escala.notificado_24h_em is None

    _verificar_e_notificar(app)
    db.session.expire_all()

    escala_atualizada = db.session.get(Escala, escala.id)
    assert escala_atualizada.notificado_24h_em is not None
    assert escala_atualizada.notificado_16h_em is None


def test_nao_notifica_fora_da_janela(logged_in_client, app, db):
    from app.auth.models import User

    usuario = User.query.filter_by(username="ana").first()
    ministerio = _criar_ministerio_teste(usuario.id)
    daqui_3_dias = datetime.now() + timedelta(days=3)

    escala = criar_escala_com_funcoes_padrao(
        ministerio_id=ministerio.id, nome="Culto Distante", departamento="Louvor",
        data=daqui_3_dias.date(), horario=daqui_3_dias.time(),
    )
    _escalar_membro(escala, "Baixo")

    _verificar_e_notificar(app)
    db.session.expire_all()

    escala_atualizada = db.session.get(Escala, escala.id)
    assert escala_atualizada.notificado_24h_em is None
    assert escala_atualizada.notificado_16h_em is None


def test_nao_notifica_duas_vezes_para_a_mesma_janela(logged_in_client, app, db):
    from app.auth.models import User

    usuario = User.query.filter_by(username="ana").first()
    ministerio = _criar_ministerio_teste(usuario.id)
    daqui_16h = datetime.now() + timedelta(hours=16)

    escala = criar_escala_com_funcoes_padrao(
        ministerio_id=ministerio.id, nome="Culto Teste 16h", departamento="Louvor",
        data=daqui_16h.date(), horario=daqui_16h.time(),
    )
    _escalar_membro(escala, "Baixo")

    _verificar_e_notificar(app)
    db.session.expire_all()
    primeira_marcacao = db.session.get(Escala, escala.id).notificado_16h_em
    assert primeira_marcacao is not None

    _verificar_e_notificar(app)
    db.session.expire_all()
    segunda_marcacao = db.session.get(Escala, escala.id).notificado_16h_em
    assert segunda_marcacao == primeira_marcacao


def test_agendador_materializa_e_notifica_turno_de_rodizio_dentro_da_janela_24h(logged_in_client, app, db):
    """O agendador unico tambem sincroniza os Turnos de Rodizio (materializa
    as proximas ocorrencias) antes de checar notificacoes -- ver
    app/plantao/sincronizacao.py::sincronizar_todos_os_turnos_ativos, chamada
    dentro de _verificar_e_notificar."""
    from app.auth.models import User
    from app.escala.models import Membro
    from app.plantao.models import TurnoPlantao, MembroTurno

    usuario = User.query.filter_by(username="ana").first()
    ministerio = _criar_ministerio_teste(usuario.id)
    daqui_24h = datetime.now() + timedelta(hours=24, minutes=2)

    turno = TurnoPlantao(
        ministerio_id=ministerio.id, nome="Plantao Recepcao", departamento="Louvor",
        nome_funcao="Responsavel", data_inicio=daqui_24h.date(), horario=daqui_24h.time(),
        recorrencia="diaria",
    )
    db.session.add(turno)
    db.session.commit()
    membro = Membro(comunidade_id=ministerio.comunidade_id, nome="Fulano", email="fulano@example.com")
    db.session.add(membro)
    db.session.flush()
    db.session.add(MembroTurno(turno_id=turno.id, membro_id=membro.id, posicao=0))
    db.session.commit()

    _verificar_e_notificar(app)
    db.session.expire_all()

    escala_gerada = Escala.query.filter_by(plantao_turno_id=turno.id, plantao_periodo=0).first()
    assert escala_gerada is not None
    assert escala_gerada.notificado_24h_em is not None


def test_agendador_nao_notifica_turno_de_rodizio_duas_vezes(logged_in_client, app, db):
    from app.auth.models import User
    from app.escala.models import Membro
    from app.plantao.models import TurnoPlantao, MembroTurno

    usuario = User.query.filter_by(username="ana").first()
    ministerio = _criar_ministerio_teste(usuario.id)
    daqui_16h = datetime.now() + timedelta(hours=16)

    turno = TurnoPlantao(
        ministerio_id=ministerio.id, nome="Plantao Recepcao", departamento="Louvor",
        nome_funcao="Responsavel", data_inicio=daqui_16h.date(), horario=daqui_16h.time(),
        recorrencia="diaria",
    )
    db.session.add(turno)
    db.session.commit()
    membro = Membro(comunidade_id=ministerio.comunidade_id, nome="Fulano", email="fulano@example.com")
    db.session.add(membro)
    db.session.flush()
    db.session.add(MembroTurno(turno_id=turno.id, membro_id=membro.id, posicao=0))
    db.session.commit()

    _verificar_e_notificar(app)
    db.session.expire_all()
    primeira = Escala.query.filter_by(plantao_turno_id=turno.id, plantao_periodo=0).first().notificado_16h_em
    assert primeira is not None

    _verificar_e_notificar(app)
    db.session.expire_all()
    segunda = Escala.query.filter_by(plantao_turno_id=turno.id, plantao_periodo=0).first().notificado_16h_em
    assert segunda == primeira


def test_escala_sem_data_e_ignorada_pelo_agendador(logged_in_client, app, db):
    from app.auth.models import User

    usuario = User.query.filter_by(username="ana").first()
    ministerio = _criar_ministerio_teste(usuario.id)
    escala = criar_escala_com_funcoes_padrao(
        ministerio_id=ministerio.id, nome="Sem Data", departamento="Louvor", data=None, horario=None,
    )
    _escalar_membro(escala, "Baixo")

    # nao deve levantar excecao mesmo com escalas sem data no banco
    _verificar_e_notificar(app)
    db.session.expire_all()

    escala_atualizada = db.session.get(Escala, escala.id)
    assert escala_atualizada.notificado_24h_em is None
