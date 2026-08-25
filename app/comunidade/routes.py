"""Controller (C do MVC): rotas do modulo comunidade."""
import os
import uuid

from flask import render_template, redirect, url_for, flash, request, current_app, abort
from flask_login import login_required, current_user
from flask_wtf.csrf import generate_csrf
from werkzeug.utils import secure_filename

from app.extensions import db
from app.comunidade import bp
from app.comunidade.forms import ComunidadeForm, MembroDiretorioForm, AcaoForm
from app.comunidade.models import Comunidade, UsuarioComunidade, PAPEIS_COMUNIDADE, criar_comunidade
from app.ministerio.models import Ministerio
from app.escala.models import Escala, Funcao, Membro, DEPARTAMENTOS, STATUS_LABELS, STATUS_CORES
from app.convites.forms import ConvidarForm
from app.convites.models import Convite, criar_ou_reenviar_convite
from app.convites.routes import _enviar_email_de_convite


def _eh_admin_da_comunidade(comunidade, usuario):
    """Admin: Super Admin da plataforma (acesso total, bypassa qualquer
    checagem) OU dono original (Comunidade.usuario_id -- metadado historico,
    ver models.py) OU papel=admin em UsuarioComunidade (concedido por convite
    aceito, ver app/convites/CLAUDE.md)."""
    if usuario.eh_super_admin:
        return True
    if comunidade.usuario_id == usuario.id:
        return True
    return UsuarioComunidade.query.filter_by(
        comunidade_id=comunidade.id, usuario_id=usuario.id, papel="admin"
    ).first() is not None


def _eh_membro_da_comunidade(comunidade, usuario):
    """Papel=membro em UsuarioComunidade -- visibilidade de leitura, mesmo
    nivel do vinculo por e-mail com o diretorio (ver _comunidade_visivel_ou_404)."""
    return UsuarioComunidade.query.filter_by(
        comunidade_id=comunidade.id, usuario_id=usuario.id, papel="membro"
    ).first() is not None


def _comunidade_do_usuario_ou_404(comunidade_id):
    """Acesso de ADMIN (leitura+escrita). Usado por toda rota de gestao.

    Sem essa checagem, qualquer pessoa logada poderia mexer numa comunidade de
    outra conta so adivinhando o id na URL.
    """
    comunidade = Comunidade.query.get_or_404(comunidade_id)
    if not _eh_admin_da_comunidade(comunidade, current_user):
        abort(404)
    return comunidade


def _comunidade_visivel_ou_404(comunidade_id):
    """Acesso de LEITURA: admin OU papel=membro OU membro do diretorio cujo
    email bate com a conta logada -- mesmo mecanismo de match por e-mail ja
    usado para ligar notificacoes in-app (ver
    app/escala/routes.py::enviar_notificacoes_da_escala).
    """
    comunidade = Comunidade.query.get_or_404(comunidade_id)
    eh_dono = _eh_admin_da_comunidade(comunidade, current_user)
    eh_membro_vinculado = eh_dono or _eh_membro_da_comunidade(comunidade, current_user) or Membro.query.filter_by(
        comunidade_id=comunidade.id, email=current_user.email
    ).first() is not None
    if not eh_membro_vinculado:
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
    if current_user.eh_super_admin:
        comunidades_dono = Comunidade.query.order_by(Comunidade.nome).all()
    else:
        ids_admin = [
            row.comunidade_id for row in
            UsuarioComunidade.query.filter_by(usuario_id=current_user.id, papel="admin").all()
        ]
        comunidades_dono = (
            Comunidade.query.filter(Comunidade.id.in_(ids_admin)).order_by(Comunidade.nome).all()
            if ids_admin else []
        )

    comunidades_membro_ids = {
        cid for (cid,) in
        db.session.query(Membro.comunidade_id).filter(Membro.email == current_user.email).distinct().all()
    }
    ids_papel_membro = {
        row.comunidade_id for row in
        UsuarioComunidade.query.filter_by(usuario_id=current_user.id, papel="membro").all()
    }
    ids_dono = {c.id for c in comunidades_dono}
    ids_membro = (comunidades_membro_ids | ids_papel_membro) - ids_dono
    comunidades_participa = Comunidade.query.filter(Comunidade.id.in_(ids_membro)).order_by(Comunidade.nome).all() if ids_membro else []

    return render_template(
        "comunidade/lista.html",
        comunidades_dono=comunidades_dono,
        comunidades_participa=comunidades_participa,
        acao_form=AcaoForm(),
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


# Passos do tutorial guiado (spotlight, ver app/static/js/main.js) mostrado
# na primeira vez que a conta abre uma Comunidade -- "seletor" bate com os
# atributos data-tutorial="..." em comunidade/detalhe.html. None = passo
# centralizado, sem destacar elemento nenhum (boas-vindas/conclusao).
PASSOS_TUTORIAL_COMUNIDADE = [
    {
        "seletor": None,
        "titulo": "Bem-vindo a sua comunidade!",
        "texto": "Vamos te mostrar rapidinho como tudo funciona por aqui -- leva menos de um minuto.",
    },
    {
        "seletor": "[data-tutorial='convites']",
        "titulo": "Convide sua equipe",
        "texto": "Aqui voce convida outras pessoas por e-mail e define quem e admin ou apenas membro da comunidade.",
    },
    {
        "seletor": "[data-tutorial='membros']",
        "titulo": "Diretorio de membros",
        "texto": "A lista de todo mundo que pode ser escalado -- nome, telefone e e-mail, sem precisar ter conta no sistema.",
    },
    {
        "seletor": "[data-tutorial='escalados']",
        "titulo": "Veja quem esta escalado",
        "texto": "Um relatorio com todo mundo escalado em qualquer ministerio da comunidade, com filtros por data e departamento.",
    },
    {
        "seletor": "[data-tutorial='novo-ministerio']",
        "titulo": "Organize por ministerios",
        "texto": "Cada area da sua comunidade (Louvor, Midia, Kids...) e um Ministerio -- e la que as escalas de verdade sao criadas.",
    },
    {
        "seletor": None,
        "titulo": "Pronto!",
        "texto": "Voce ja sabe o essencial. Pode explorar a vontade -- da pra rever isso depois se precisar.",
    },
]


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
        mostrar_tutorial=not current_user.tutorial_comunidade_visto,
        passos_tutorial=PASSOS_TUTORIAL_COMUNIDADE,
        # generate_csrf() direto (nao o global csrf_token() do Jinja, que so
        # existe se CSRFProtect(app) for registrado globalmente -- nao e o
        # caso aqui) -- funciona com WTF_CSRF_ENABLED ligado ou desligado.
        csrf_token_tutorial=generate_csrf(),
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


@bp.route("/excluir-varias", methods=["POST"])
@login_required
def excluir_varias():
    """Exclusao em lote (ver comunidade/lista.html) -- so mexe nas
    comunidades onde o usuario e admin, mesmo que o form tenha sido
    adulterado pra incluir id de outra conta (_eh_admin_da_comunidade
    filtra, nunca confia cegamente na lista recebida)."""
    form = AcaoForm()
    if not form.validate_on_submit():
        flash("Acao invalida.", "danger")
        return redirect(url_for("comunidade.index"))

    ids = request.form.getlist("comunidade_ids", type=int)
    comunidades = Comunidade.query.filter(Comunidade.id.in_(ids)).all() if ids else []

    excluidas = 0
    for comunidade in comunidades:
        if not _eh_admin_da_comunidade(comunidade, current_user):
            continue
        _remover_logo_antiga(comunidade.imagem)
        db.session.delete(comunidade)
        excluidas += 1

    if excluidas:
        db.session.commit()
        plural = "s" if excluidas != 1 else ""
        flash(f"{excluidas} comunidade{plural} excluida{plural}.", "success")
    else:
        flash("Nenhuma comunidade valida foi selecionada.", "danger")

    return redirect(url_for("comunidade.index"))


@bp.route("/<int:comunidade_id>/membros", methods=["GET", "POST"])
@login_required
def membros(comunidade_id):
    comunidade = _comunidade_do_usuario_ou_404(comunidade_id)
    form = MembroDiretorioForm()

    # Link "de volta" opcional (ex: veio da tela de uma Escala pra cadastrar
    # alguem que faltava no diretorio, ver escala/detalhe.html) -- so aceita
    # caminho relativo interno (comeca com "/" e nao "//") pra nao virar um
    # open redirect se alguem forjar o parametro. request.values cobre tanto
    # a querystring (GET, e o form nao tem action= explicito entao ela e
    # preservada no POST) quanto o campo oculto abaixo, entao funciona nos
    # dois metodos sem duplicar logica.
    proximo = request.values.get("proximo")
    if not proximo or not proximo.startswith("/") or proximo.startswith("//"):
        proximo = None

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
        return redirect(proximo or url_for("comunidade.membros", comunidade_id=comunidade.id))

    diretorio = Membro.query.filter_by(comunidade_id=comunidade.id).order_by(Membro.nome).all()

    return render_template(
        "comunidade/membros.html",
        comunidade=comunidade,
        diretorio=diretorio,
        form=form,
        acao_form=AcaoForm(),
        proximo=proximo,
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


# --- Papeis e convites -------------------------------------------------------
#
# So admin da comunidade chega aqui (_comunidade_do_usuario_ou_404). Um admin
# pode conceder papel "admin" ou "membro" nesta comunidade -- nunca
# "super_admin" (nem e uma opcao: PAPEIS_COMUNIDADE so tem admin/membro, ver
# app/comunidade/models.py). Ver app/convites/CLAUDE.md pro fluxo completo.

@bp.route("/<int:comunidade_id>/papeis", methods=["GET", "POST"])
@login_required
def papeis(comunidade_id):
    comunidade = _comunidade_do_usuario_ou_404(comunidade_id)
    form = ConvidarForm()
    form.papel.choices = [(p, p.capitalize()) for p in PAPEIS_COMUNIDADE]

    if form.validate_on_submit():
        convite = criar_ou_reenviar_convite(
            escopo_tipo="comunidade", escopo_id=comunidade.id,
            papel=form.papel.data, email=form.email.data,
            convidado_por_id=current_user.id,
        )
        _enviar_email_de_convite(convite)
        flash(f"Convite enviado para {convite.email}.", "success")
        return redirect(url_for("comunidade.papeis", comunidade_id=comunidade.id))

    papeis_atuais = (
        UsuarioComunidade.query.filter_by(comunidade_id=comunidade.id)
        .order_by(UsuarioComunidade.papel)
        .all()
    )
    convites_pendentes = (
        Convite.query.filter_by(escopo_tipo="comunidade", escopo_id=comunidade.id, status="pendente")
        .order_by(Convite.criado_em.desc())
        .all()
    )

    return render_template(
        "comunidade/papeis.html",
        comunidade=comunidade,
        form=form,
        papeis_atuais=papeis_atuais,
        convites_pendentes=convites_pendentes,
        acao_form=AcaoForm(),
    )


@bp.route("/<int:comunidade_id>/papeis/<int:usuario_comunidade_id>/remover", methods=["POST"])
@login_required
def remover_papel(comunidade_id, usuario_comunidade_id):
    comunidade = _comunidade_do_usuario_ou_404(comunidade_id)
    papel = UsuarioComunidade.query.filter_by(id=usuario_comunidade_id, comunidade_id=comunidade.id).first_or_404()
    form = AcaoForm()

    if not form.validate_on_submit():
        flash("Acao invalida.", "danger")
        return redirect(url_for("comunidade.papeis", comunidade_id=comunidade.id))

    nome = papel.usuario.name or papel.usuario.username or papel.usuario.email
    db.session.delete(papel)
    db.session.commit()
    flash(f"{nome} removido(a) dos administradores/membros da comunidade.", "success")
    return redirect(url_for("comunidade.papeis", comunidade_id=comunidade.id))


@bp.route("/<int:comunidade_id>/papeis/convite/<int:convite_id>/cancelar", methods=["POST"])
@login_required
def cancelar_convite(comunidade_id, convite_id):
    comunidade = _comunidade_do_usuario_ou_404(comunidade_id)
    convite = Convite.query.filter_by(
        id=convite_id, escopo_tipo="comunidade", escopo_id=comunidade.id, status="pendente"
    ).first_or_404()
    form = AcaoForm()

    if not form.validate_on_submit():
        flash("Acao invalida.", "danger")
        return redirect(url_for("comunidade.papeis", comunidade_id=comunidade.id))

    db.session.delete(convite)
    db.session.commit()
    flash("Convite cancelado.", "success")
    return redirect(url_for("comunidade.papeis", comunidade_id=comunidade.id))


