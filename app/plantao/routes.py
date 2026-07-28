"""Controller (C do MVC): rotas do modulo plantao.

O plantao nao tem mais tela de calendario propria -- as ocorrencias geradas
por rodizio sao Escala de verdade (ver app/plantao/sincronizacao.py) e
aparecem no calendario/lista do proprio Ministerio e em escala/detalhe.html.
Este modulo cuida so da CONFIGURACAO da regra (fila, offset, recorrencia).
"""
from datetime import date, datetime

from flask import render_template, redirect, url_for, flash, request, abort
from flask_login import login_required, current_user

from app.extensions import db
from app.escala.models import Escala, Membro
from app.plantao import bp
from app.plantao.forms import TurnoPlantaoForm, AdicionarMembroFilaForm, AcaoForm
from app.plantao.models import TurnoPlantao, MembroTurno, opcoes_modo_mensal_completas, periodo_exato_da_data
from app.plantao.sincronizacao import (
    sincronizar_turno,
    preparar_para_renumeracao,
    marcar_ausencia as marcar_ausencia_no_periodo,
)

OCORRENCIAS_EXIBIDAS = 20

# Campos do turno que, ao mudar, invalidam a numeracao de periodo ja usada
# nas Escala geradas (ver preparar_para_renumeracao) -- qualquer um deles
# muda o que "periodo N" significa, nao so data_inicio/unidade.
CAMPOS_QUE_AFETAM_NUMERACAO = (
    "data_inicio", "intervalo_recorrencia", "unidade_recorrencia", "dias_semana",
    "modo_mensal", "termino_tipo", "termino_data", "termino_ocorrencias",
)


def _turno_do_usuario_ou_404(turno_id):
    """Busca o turno garantindo que pertence ao dono da comunidade do ministerio dele."""
    turno = TurnoPlantao.query.get_or_404(turno_id)
    if turno.ministerio.comunidade.usuario_id != current_user.id:
        abort(404)
    return turno


def _aplicar_campos_do_form(turno, form):
    """Copia os campos do TurnoPlantaoForm pro model, tratando as conversoes
    que o WTForms nao faz sozinho (CSV<->lista de dias_semana; campos de
    modo_mensal/termino_data/termino_ocorrencias so valem pra unidade/tipo
    correspondente)."""
    turno.nome = form.nome.data.strip()
    turno.departamento = form.departamento.data
    turno.nome_funcao = form.nome_funcao.data.strip() or "Responsavel"
    turno.data_inicio = form.data_inicio.data
    turno.horario = form.horario.data
    turno.intervalo_recorrencia = form.intervalo_recorrencia.data
    turno.unidade_recorrencia = form.unidade_recorrencia.data
    turno.dias_semana = (
        ",".join(str(d) for d in sorted(form.dias_semana.data)) if form.dias_semana.data else None
    )
    turno.modo_mensal = form.modo_mensal.data if form.unidade_recorrencia.data == "mes" else None
    turno.termino_tipo = form.termino_tipo.data
    turno.termino_data = form.termino_data.data if form.termino_tipo.data == "data" else None
    turno.termino_ocorrencias = (
        form.termino_ocorrencias.data if form.termino_tipo.data == "ocorrencias" else None
    )


def _semear_fila_a_partir_da_escala(turno, escala):
    """Pre-popula a fila do turno com os membros ja escalados nas funcoes da
    escala de origem (na ordem em que aparecem na grade, sem repetir a mesma
    pessoa) -- poupa o passo manual de re-selecionar cada pessoa, um a um, na
    tela de fila do turno."""
    vistos = set()
    posicao = 0
    for funcao in sorted(escala.funcoes, key=lambda f: f.ordem):
        if funcao.membro_id is None or funcao.membro_id in vistos:
            continue
        vistos.add(funcao.membro_id)
        db.session.add(MembroTurno(turno_id=turno.id, membro_id=funcao.membro_id, posicao=posicao))
        posicao += 1
    db.session.commit()


@bp.route("/ministerio/<int:ministerio_id>/nova", methods=["GET", "POST"])
@login_required
def nova(ministerio_id):
    from app.ministerio.routes import _ministerio_do_usuario_ou_404
    from app.escala.routes import _escala_do_usuario_ou_404

    ministerio = _ministerio_do_usuario_ou_404(ministerio_id)

    # Turno "nascido" a partir de uma Escala (ver escala/detalhe.html): a
    # fila do rodizio reaproveita quem ja esta escalado nela, em vez do
    # usuario ter que recadastrar cada pessoa manualmente.
    escala_origem = None
    escala_id = request.args.get("escala_id", type=int)
    if escala_id:
        escala_origem = _escala_do_usuario_ou_404(escala_id)
        if escala_origem.ministerio_id != ministerio.id:
            abort(404)

    form = TurnoPlantaoForm()
    if request.method == "GET" and escala_origem:
        form.nome.data = escala_origem.nome
        form.departamento.data = escala_origem.departamento
        form.data_inicio.data = escala_origem.data
        form.horario.data = escala_origem.horario

    data_referencia = form.data_inicio.data or date.today()
    form.modo_mensal.choices = opcoes_modo_mensal_completas(data_referencia)

    if form.validate_on_submit():
        turno = TurnoPlantao(ministerio_id=ministerio.id)
        _aplicar_campos_do_form(turno, form)
        db.session.add(turno)
        db.session.commit()

        if escala_origem:
            _semear_fila_a_partir_da_escala(turno, escala_origem)

        sincronizar_turno(turno)
        flash(f'Turno de rodizio "{turno.nome}" criado! Agora monte a fila de rodizio.', "success")
        return redirect(url_for("plantao.detalhe", turno_id=turno.id))

    return render_template("plantao/nova.html", form=form, ministerio=ministerio, escala_origem=escala_origem)


@bp.route("/<int:turno_id>", methods=["GET"])
@login_required
def detalhe(turno_id):
    turno = _turno_do_usuario_ou_404(turno_id)

    diretorio = Membro.query.filter_by(comunidade_id=turno.ministerio.comunidade_id).order_by(Membro.nome).all()
    ids_na_fila = {item.membro_id for item in turno.fila}
    diretorio_disponivel = [m for m in diretorio if m.id not in ids_na_fila]

    form_adicionar = AdicionarMembroFilaForm()
    form_adicionar.membro_id.choices = [(m.id, m.nome) for m in diretorio_disponivel]

    hoje = date.today()
    # Mostra passado e futuro (nao so "proximas") -- essa e a tela pra onde
    # a capa do turno na lista de Escalas do Ministerio leva, entao precisa
    # dar pra ver o historico completo daquele turno, nao so o que vem
    # depois de hoje. Mais recente/proximo primeiro; limitado pra nao pesar
    # em turnos recorrentes de longa duracao.
    ocorrencias = (
        Escala.query.filter(
            Escala.plantao_turno_id == turno.id,
            Escala.data.isnot(None),
        )
        .order_by(Escala.data.desc())
        .limit(OCORRENCIAS_EXIBIDAS)
        .all()
    )

    return render_template(
        "plantao/detalhe.html",
        turno=turno,
        diretorio_vazio=not diretorio,
        form_adicionar=form_adicionar,
        acao_form=AcaoForm(),
        ocorrencias=ocorrencias,
        hoje=hoje,
    )


@bp.route("/<int:turno_id>/editar", methods=["GET", "POST"])
@login_required
def editar(turno_id):
    turno = _turno_do_usuario_ou_404(turno_id)
    form = TurnoPlantaoForm(obj=turno)

    if request.method == "GET":
        # SelectMultipleField nao entende a coluna CSV crua via obj= --
        # sobrescreve com a lista ja convertida (so no GET: no POST o
        # formdata submetido sempre tem prioridade sobre obj=).
        form.dias_semana.data = turno.dias_semana_efetivos

    data_referencia = form.data_inicio.data or turno.data_inicio
    form.modo_mensal.choices = opcoes_modo_mensal_completas(data_referencia)

    if form.validate_on_submit():
        valores_antigos = {campo: getattr(turno, campo) for campo in CAMPOS_QUE_AFETAM_NUMERACAO}

        _aplicar_campos_do_form(turno, form)

        muda_numeracao = any(
            valores_antigos[campo] != getattr(turno, campo) for campo in CAMPOS_QUE_AFETAM_NUMERACAO
        )

        db.session.commit()

        if muda_numeracao:
            # a numeracao de periodo passou a significar outra data -- solta o
            # vinculo das escalas ja geradas antes de recriar com a nova regra
            preparar_para_renumeracao(turno)

        sincronizar_turno(turno)

        flash(f'Turno de rodizio "{turno.nome}" atualizado!', "success")
        return redirect(url_for("plantao.detalhe", turno_id=turno.id))

    return render_template("plantao/editar.html", form=form, turno=turno)


@bp.route("/<int:turno_id>/excluir", methods=["POST"])
@login_required
def excluir_turno(turno_id):
    turno = _turno_do_usuario_ou_404(turno_id)
    form = AcaoForm()

    if not form.validate_on_submit():
        flash("Acao invalida.", "danger")
        return redirect(url_for("plantao.detalhe", turno_id=turno.id))

    # Escalas ja ocorridas ou fixadas (excecao pontual/edicao manual) viram
    # historico solto -- nao podem ser apagadas junto com a regra. As futuras
    # nao-fixadas eram so previsao calculada, sao removidas.
    agora = datetime.now()
    for escala in list(turno.escalas_geradas):
        ja_ocorreu = escala.data_hora and escala.data_hora <= agora
        if escala.plantao_fixado or ja_ocorreu:
            escala.plantao_turno_id = None
            escala.plantao_periodo = None
        else:
            db.session.delete(escala)
    db.session.flush()

    ministerio_id = turno.ministerio_id
    nome = turno.nome
    db.session.delete(turno)
    db.session.commit()

    flash(f'Turno de rodizio "{nome}" excluido.', "success")
    return redirect(url_for("ministerio.detalhe", ministerio_id=ministerio_id))


@bp.route("/<int:turno_id>/fila/adicionar", methods=["POST"])
@login_required
def adicionar_membro_fila(turno_id):
    turno = _turno_do_usuario_ou_404(turno_id)

    diretorio = Membro.query.filter_by(comunidade_id=turno.ministerio.comunidade_id).order_by(Membro.nome).all()
    ids_na_fila = {item.membro_id for item in turno.fila}
    diretorio_disponivel = [m for m in diretorio if m.id not in ids_na_fila]

    form = AdicionarMembroFilaForm()
    form.membro_id.choices = [(m.id, m.nome) for m in diretorio_disponivel]

    if not form.validate_on_submit():
        erros = [erro for lista in form.errors.values() for erro in lista]
        flash(erros[0] if erros else "Nao foi possivel adicionar a fila.", "danger")
        return redirect(url_for("plantao.detalhe", turno_id=turno.id))

    membro = Membro.query.filter_by(id=form.membro_id.data, comunidade_id=turno.ministerio.comunidade_id).first()
    if membro is None:
        flash("Pessoa invalida para esta comunidade.", "danger")
        return redirect(url_for("plantao.detalhe", turno_id=turno.id))

    maior_posicao = max([item.posicao for item in turno.fila], default=-1)
    db.session.add(MembroTurno(turno_id=turno.id, membro_id=membro.id, posicao=maior_posicao + 1))
    db.session.commit()

    sincronizar_turno(turno)

    flash(f"{membro.nome} adicionado(a) a fila do rodizio.", "success")
    return redirect(url_for("plantao.detalhe", turno_id=turno.id))


@bp.route("/<int:turno_id>/fila/<int:membro_turno_id>/remover", methods=["POST"])
@login_required
def remover_membro_fila(turno_id, membro_turno_id):
    turno = _turno_do_usuario_ou_404(turno_id)
    form = AcaoForm()

    if not form.validate_on_submit():
        flash("Acao invalida.", "danger")
        return redirect(url_for("plantao.detalhe", turno_id=turno.id))

    item = MembroTurno.query.filter_by(id=membro_turno_id, turno_id=turno.id).first_or_404()
    nome = item.membro.nome
    db.session.delete(item)
    db.session.flush()

    # renumera as posicoes restantes pra ficarem contiguas (0..N-1)
    restante = MembroTurno.query.filter_by(turno_id=turno.id).order_by(MembroTurno.posicao).all()
    for indice, item_restante in enumerate(restante):
        item_restante.posicao = indice
    db.session.commit()

    sincronizar_turno(turno)

    flash(f"{nome} removido(a) da fila do rodizio.", "success")
    return redirect(url_for("plantao.detalhe", turno_id=turno.id))


@bp.route("/<int:turno_id>/ausencia", methods=["POST"])
@login_required
def registrar_ausencia(turno_id):
    """Registra ausencia a partir da data (usado pela tela de configuracao do
    turno). Ver tambem registrar_ausencia_na_escala, acionada direto da tela
    da Escala gerada."""
    turno = _turno_do_usuario_ou_404(turno_id)
    form = AcaoForm()

    data_str = request.form.get("data", "")
    redirecionamento = request.form.get("voltar_para") or url_for("plantao.detalhe", turno_id=turno.id)

    if not form.validate_on_submit():
        flash("Acao invalida.", "danger")
        return redirect(redirecionamento)

    try:
        data_ausencia = datetime.strptime(data_str, "%Y-%m-%d").date()
    except ValueError:
        flash("Data invalida.", "danger")
        return redirect(redirecionamento)

    try:
        periodo = periodo_exato_da_data(turno, data_ausencia)
        marcar_ausencia_no_periodo(turno, periodo)
    except ValueError as erro:
        flash(str(erro), "danger")
        return redirect(redirecionamento)

    flash(f"Falta em {data_ausencia.strftime('%d/%m/%Y')} remanejada -- fila reorganizada a partir dai.", "success")
    return redirect(redirecionamento)


@bp.route("/escala/<int:escala_id>/ausencia", methods=["POST"])
@login_required
def registrar_ausencia_na_escala(escala_id):
    """Registra ausencia a partir da propria tela da Escala gerada por
    rodizio (escala/detalhe.html) -- equivalente a registrar_ausencia, so que
    resolvendo turno/periodo a partir da Escala em vez de uma data digitada."""
    escala = Escala.query.get_or_404(escala_id)
    if escala.ministerio.comunidade.usuario_id != current_user.id:
        abort(404)
    if escala.plantao_turno_id is None or escala.plantao_periodo is None:
        abort(404)

    form = AcaoForm()
    if not form.validate_on_submit():
        flash("Acao invalida.", "danger")
        return redirect(url_for("escala.detalhe", escala_id=escala.id))

    turno = _turno_do_usuario_ou_404(escala.plantao_turno_id)

    try:
        marcar_ausencia_no_periodo(turno, escala.plantao_periodo)
    except ValueError as erro:
        flash(str(erro), "danger")
        return redirect(url_for("escala.detalhe", escala_id=escala.id))

    flash("Ausencia remanejada -- fila reorganizada a partir dai.", "success")
    return redirect(url_for("escala.detalhe", escala_id=escala.id))
