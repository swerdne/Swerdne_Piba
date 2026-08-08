"""Controller (C do MVC): rotas do modulo comunidade."""
import os
import uuid

from flask import render_template, redirect, url_for, flash, request, current_app, abort
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from app.extensions import db
from app.comunidade import bp
from app.comunidade.forms import ComunidadeForm, MembroDiretorioForm, AcaoForm
from app.comunidade.models import Comunidade, criar_comunidade
from app.ministerio.models import Ministerio
from app.escala.models import Escala, Funcao, Membro, DEPARTAMENTOS, STATUS_LABELS, STATUS_CORES


def _comunidade_do_usuario_ou_404(comunidade_id):
    """Acesso de DONO (leitura+escrita). Usado por toda rota de gestao.

    Sem essa checagem, qualquer pessoa logada poderia mexer numa comunidade de
    outra conta so adivinhando o id na URL.
    """
    comunidade = Comunidade.query.get_or_404(comunidade_id)
    if comunidade.usuario_id != current_user.id:
        abort(404)
    return comunidade


def _comunidade_visivel_ou_404(comunidade_id):
    """Acesso de LEITURA: dono OU membro do diretorio cujo email bate com a
    conta logada -- mesmo mecanismo de match por e-mail ja usado para ligar
    notificacoes in-app (ver app/escala/routes.py::enviar_notificacoes_da_escala).
    """
    comunidade = Comunidade.query.get_or_404(comunidade_id)
    eh_dono = comunidade.usuario_id == current_user.id
    eh_membro_vinculado = Membro.query.filter_by(
        comunidade_id=comunidade.id, email=current_user.email
    ).first() is not None
    if not eh_dono and not eh_membro_vinculado:
        abort(404)
    return comunidade, eh_dono


def _salvar_logo(arquivo):
    extensao = arquivo.filename.rsplit(".", 1)[1].lower()
    nome_arquivo = secure_filename(f"comunidade_{uuid.uuid4().hex}.{extensao}")

    upload_folder = current_app.config["COMUNIDADE_UPLOAD_FOLDER"]
    os.makedirs(upload_folder, exist_ok=True)
    arquivo.save(os.path.join(upload_folder, nome_arquivo))

    return f"/static/uploads/comunidades/{nome_arquivo}"


def _remover_logo_antiga(caminho):
    if caminho and caminho.startswith("/static/uploads/comunidades/"):
        caminho_absoluto = os.path.join("app", caminho.lstrip("/"))
        if os.path.isfile(caminho_absoluto):
            try:
                os.remove(caminho_absoluto)
            except OSError:
                pass


@bp.route("/")
@login_required
def index():
    comunidades_dono = Comunidade.query.filter_by(usuario_id=current_user.id).order_by(Comunidade.nome).all()

    comunidades_membro_ids = (
        db.session.query(Membro.comunidade_id)
        .filter(Membro.email == current_user.email)
        .distinct()
        .all()
    )
    ids_dono = {c.id for c in comunidades_dono}
    ids_membro = [cid for (cid,) in comunidades_membro_ids if cid not in ids_dono]
    comunidades_participa = Comunidade.query.filter(Comunidade.id.in_(ids_membro)).order_by(Comunidade.nome).all() if ids_membro else []

    return render_template(
        "comunidade/lista.html",
        comunidades_dono=comunidades_dono,
        comunidades_participa=comunidades_participa,
    )


@bp.route("/nova", methods=["GET", "POST"])
@login_required
def nova():
    form = ComunidadeForm()

    if form.validate_on_submit():
        imagem = _salvar_logo(form.imagem.data) if form.imagem.data else None
        comunidade = criar_comunidade(
            usuario_id=current_user.id,
            nome=form.nome.data.strip(),
            descricao=(form.descricao.data or "").strip() or None,
            imagem=imagem,
        )
        flash(f'Comunidade "{comunidade.nome}" criada!', "success")
        return redirect(url_for("comunidade.detalhe", comunidade_id=comunidade.id))

    return render_template("comunidade/nova.html", form=form)


@bp.route("/<int:comunidade_id>")
@login_required
def detalhe(comunidade_id):
    comunidade = _comunidade_do_usuario_ou_404(comunidade_id)
    ministerios = (
        Ministerio.query.filter_by(comunidade_id=comunidade.id).order_by(Ministerio.nome).all()
    )
    total_membros = Membro.query.filter_by(comunidade_id=comunidade.id).count()

    return render_template(
        "comunidade/detalhe.html",
        comunidade=comunidade,
        ministerios=ministerios,
        total_membros=total_membros,
        acao_form=AcaoForm(),
    )


@bp.route("/<int:comunidade_id>/editar", methods=["GET", "POST"])
@login_required
def editar(comunidade_id):
    comunidade = _comunidade_do_usuario_ou_404(comunidade_id)
    form = ComunidadeForm(nome=comunidade.nome, descricao=comunidade.descricao)

    if form.validate_on_submit():
        comunidade.nome = form.nome.data.strip()
        comunidade.descricao = (form.descricao.data or "").strip() or None

        if form.imagem.data:
            logo_antiga = comunidade.imagem
            comunidade.imagem = _salvar_logo(form.imagem.data)
            _remover_logo_antiga(logo_antiga)

        db.session.commit()
        flash("Comunidade atualizada!", "success")
        return redirect(url_for("comunidade.detalhe", comunidade_id=comunidade.id))

    return render_template("comunidade/editar.html", form=form, comunidade=comunidade)


@bp.route("/<int:comunidade_id>/excluir", methods=["POST"])
@login_required
def excluir_comunidade(comunidade_id):
    comunidade = _comunidade_do_usuario_ou_404(comunidade_id)
    form = AcaoForm()

    if not form.validate_on_submit():
        flash("Acao invalida.", "danger")
        return redirect(url_for("comunidade.detalhe", comunidade_id=comunidade.id))

    # Cascade (cascade="all, delete-orphan" em Comunidade.ministerios e
    # Comunidade.membros) apaga junto todos os Ministerios (e as Escalas e
    # Turnos de Rodizio deles, mesmo mecanismo de ministerio.excluir_ministerio)
    # e todo o diretorio de Membros da comunidade.
    _remover_logo_antiga(comunidade.imagem)

    nome = comunidade.nome
    db.session.delete(comunidade)
    db.session.commit()

    flash(f'Comunidade "{nome}" excluida.', "success")
    return redirect(url_for("comunidade.index"))


@bp.route("/<int:comunidade_id>/membros", methods=["GET", "POST"])
@login_required
def membros(comunidade_id):
    comunidade = _comunidade_do_usuario_ou_404(comunidade_id)
    form = MembroDiretorioForm()

    if form.validate_on_submit():
        membro = Membro(
            comunidade_id=comunidade.id,
            nome=form.nome.data.strip(),
            telefone=(form.telefone.data or "").strip() or None,
            email=(form.email.data or "").strip() or None,
        )
        db.session.add(membro)
        db.session.commit()
        flash(f"{membro.nome} adicionado(a) ao diretorio.", "success")
        return redirect(url_for("comunidade.membros", comunidade_id=comunidade.id))

    diretorio = Membro.query.filter_by(comunidade_id=comunidade.id).order_by(Membro.nome).all()

    return render_template(
        "comunidade/membros.html",
        comunidade=comunidade,
        diretorio=diretorio,
        form=form,
        acao_form=AcaoForm(),
    )


@bp.route("/<int:comunidade_id>/membros/<int:membro_id>/excluir", methods=["POST"])
@login_required
def excluir_membro(comunidade_id, membro_id):
    comunidade = _comunidade_do_usuario_ou_404(comunidade_id)
    membro = Membro.query.filter_by(id=membro_id, comunidade_id=comunidade.id).first_or_404()
    form = AcaoForm()

    if not form.validate_on_submit():
        flash("Acao invalida.", "danger")
        return redirect(url_for("comunidade.membros", comunidade_id=comunidade.id))

    if Funcao.query.filter_by(membro_id=membro.id).count() > 0:
        flash(f"Remova {membro.nome} das escalas antes de excluir do diretorio.", "danger")
        return redirect(url_for("comunidade.membros", comunidade_id=comunidade.id))

    db.session.delete(membro)
    db.session.commit()
    flash(f"{membro.nome} removido(a) do diretorio.", "success")
    return redirect(url_for("comunidade.membros", comunidade_id=comunidade.id))


@bp.route("/<int:comunidade_id>/escalados")
@login_required
def escalados(comunidade_id):
    comunidade, eh_dono = _comunidade_visivel_ou_404(comunidade_id)

    data_de = request.args.get("data_de", "").strip()
    data_ate = request.args.get("data_ate", "").strip()
    departamento = request.args.get("departamento", "").strip()
    funcao_nome = request.args.get("funcao", "").strip()

    consulta = (
        Funcao.query.join(Escala)
        .join(Ministerio, Escala.ministerio_id == Ministerio.id)
        .filter(Ministerio.comunidade_id == comunidade.id, Funcao.membro_id.isnot(None))
    )

    if data_de:
        consulta = consulta.filter(Escala.data >= data_de)
    if data_ate:
        consulta = consulta.filter(Escala.data <= data_ate)
    if departamento:
        consulta = consulta.filter(Escala.departamento == departamento)
    if funcao_nome:
        consulta = consulta.filter(Funcao.nome.ilike(f"%{funcao_nome}%"))

    funcoes = consulta.order_by(Escala.data.is_(None), Escala.data, Escala.horario).all()

    return render_template(
        "comunidade/escalados.html",
        comunidade=comunidade,
        eh_dono=eh_dono,
        funcoes=funcoes,
        departamentos=DEPARTAMENTOS.keys(),
        status_labels=STATUS_LABELS,
        status_cores=STATUS_CORES,
        filtros={
            "data_de": data_de,
            "data_ate": data_ate,
            "departamento": departamento,
            "funcao": funcao_nome,
        },
    )
