"""Controller (C do MVC): rotas do modulo comunidade."""
import calendar
import os
import uuid
from datetime import date, timedelta

from flask import render_template, redirect, url_for, flash, request, current_app, abort, session
from flask_login import login_required, current_user
from flask_wtf.csrf import generate_csrf
from werkzeug.utils import secure_filename

from app.extensions import db
from app.comunidade import bp
from app.comunidade.forms import ComunidadeForm, MembroDiretorioForm, CicloDisponibilidadeForm, AcaoForm
from app.comunidade.models import Comunidade, UsuarioComunidade, PAPEIS_COMUNIDADE, criar_comunidade
from app.ministerio.models import Ministerio
from app.auth.models import User
from app.notificacoes import Notificacao
from app.escala.models import (
    Escala,
    Funcao,
    Membro,
    CicloDisponibilidade,
    SegmentoCiclo,
    DEPARTAMENTOS,
    STATUS_LABELS,
    STATUS_CORES,
)
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


def _admins_da_comunidade(comunidade):
    """Todas as contas com papel=admin nesta Comunidade, incluindo o dono
    original (Comunidade.usuario_id, que nem sempre tem uma linha propria em
    UsuarioComunidade -- ver criar_comunidade). Usado pra notificar (sino
    in-app) quando algo relevante acontece, ex: alguem entra via link."""
    ids_admin = {
        row.usuario_id for row in
        UsuarioComunidade.query.filter_by(comunidade_id=comunidade.id, papel="admin").all()
    }
    if comunidade.usuario_id:
        ids_admin.add(comunidade.usuario_id)
    if not ids_admin:
        return []
    return User.query.filter(User.id.in_(ids_admin)).all()


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


def _ler_segmentos_do_form():
    """Le os segmentos de um ciclo de disponibilidade (nome/duracao/
    indisponivel, quantidade variavel -- ver nova_disponibilidade) do
    request.form, indexados segmento_nome_<i>/segmento_dias_<i>/
    segmento_indisponivel_<i> (o JS de comunidade/disponibilidade.html monta
    esses nomes ao adicionar cada linha). Para no primeiro indice ausente;
    ignora linhas com nome vazio ou duracao invalida/nao positiva (o usuario
    pode ter deixado uma linha em branco ao adicionar/remover outras)."""
    segmentos = []
    indice = 0
    while f"segmento_nome_{indice}" in request.form:
        nome = request.form.get(f"segmento_nome_{indice}", "").strip()
        duracao_bruta = request.form.get(f"segmento_dias_{indice}", "")
        indisponivel = f"segmento_indisponivel_{indice}" in request.form
        indice += 1

        if not nome:
            continue
        try:
            duracao = int(duracao_bruta)
        except (TypeError, ValueError):
            continue
        if duracao <= 0:
            continue
        segmentos.append({"nome": nome, "duracao_dias": duracao, "indisponivel": indisponivel})
    return segmentos


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
    # Membro (diretorio de escalacao) e UsuarioComunidade (conta que entrou
    # via convite/link) sao coisas diferentes -- ver models.py -- mas pra
    # quem esta contando "quantas pessoas" a comunidade tem, os dois contam.
    # Deduplicado por e-mail (mesmo criterio ja usado em comunidade.index)
    # pra nao contar duas vezes quem esta nos dois ao mesmo tempo.
    membros_diretorio = Membro.query.filter_by(comunidade_id=comunidade.id).all()
    emails_diretorio = {m.email.lower() for m in membros_diretorio if m.email}
    contas_vinculadas = UsuarioComunidade.query.filter_by(comunidade_id=comunidade.id).all()
    contas_extras = sum(
        1 for uc in contas_vinculadas
        if not uc.usuario.email or uc.usuario.email.lower() not in emails_diretorio
    )
    total_membros = len(membros_diretorio) + contas_extras

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

    # Diretorio (Membro, acima) e contas vinculadas (UsuarioComunidade) sao
    # coisas diferentes -- ver models.py -- mas quem entra em "Membros"
    # esperando ver quem de fato entrou pela comunidade (convite/link)
    # precisa ver as duas listas, senao a contagem em comunidade.detalhe nao
    # bate com ninguem aparecendo aqui.
    contas_vinculadas = sorted(
        UsuarioComunidade.query.filter_by(comunidade_id=comunidade.id).all(),
        key=lambda uc: (uc.papel, (uc.usuario.name or uc.usuario.username or uc.usuario.email).lower()),
    )

    return render_template(
        "comunidade/membros.html",
        comunidade=comunidade,
        diretorio=diretorio,
        contas_vinculadas=contas_vinculadas,
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


@bp.route("/<int:comunidade_id>/membros/<int:membro_id>/disponibilidade")
@login_required
def disponibilidade(comunidade_id, membro_id):
    comunidade = _comunidade_do_usuario_ou_404(comunidade_id)
    membro = Membro.query.filter_by(id=membro_id, comunidade_id=comunidade.id).first_or_404()

    ciclos = (
        CicloDisponibilidade.query.filter_by(membro_id=membro.id)
        .order_by(CicloDisponibilidade.data_inicio.desc())
        .all()
    )

    return render_template(
        "comunidade/disponibilidade.html",
        comunidade=comunidade,
        membro=membro,
        ciclos=ciclos,
        form=CicloDisponibilidadeForm(),
        acao_form=AcaoForm(),
    )


@bp.route("/<int:comunidade_id>/membros/<int:membro_id>/disponibilidade/nova", methods=["POST"])
@login_required
def nova_disponibilidade(comunidade_id, membro_id):
    comunidade = _comunidade_do_usuario_ou_404(comunidade_id)
    membro = Membro.query.filter_by(id=membro_id, comunidade_id=comunidade.id).first_or_404()
    form = CicloDisponibilidadeForm()

    if not form.validate_on_submit():
        erros = [erro for lista in form.errors.values() for erro in lista]
        flash(erros[0] if erros else "Nao foi possivel salvar o ciclo.", "danger")
        return redirect(url_for("comunidade.disponibilidade", comunidade_id=comunidade.id, membro_id=membro.id))

    segmentos = _ler_segmentos_do_form()
    if not segmentos:
        flash("Adicione pelo menos um segmento (ex: \"Trabalho\", 4 dias) antes de salvar.", "danger")
        return redirect(url_for("comunidade.disponibilidade", comunidade_id=comunidade.id, membro_id=membro.id))

    ciclo = CicloDisponibilidade(
        membro_id=membro.id, nome=form.nome.data.strip(), data_inicio=form.data_inicio.data
    )
    db.session.add(ciclo)
    db.session.flush()  # garante ciclo.id antes de criar os segmentos

    for ordem, segmento in enumerate(segmentos):
        db.session.add(SegmentoCiclo(
            ciclo_id=ciclo.id,
            ordem=ordem,
            nome=segmento["nome"],
            duracao_dias=segmento["duracao_dias"],
            indisponivel=segmento["indisponivel"],
        ))
    db.session.commit()

    flash(f'Ciclo "{ciclo.nome}" cadastrado pra {membro.nome}.', "success")
    return redirect(url_for("comunidade.disponibilidade", comunidade_id=comunidade.id, membro_id=membro.id))


@bp.route("/<int:comunidade_id>/disponibilidade/<int:ciclo_id>/excluir", methods=["POST"])
@login_required
def excluir_disponibilidade(comunidade_id, ciclo_id):
    comunidade = _comunidade_do_usuario_ou_404(comunidade_id)
    ciclo = (
        CicloDisponibilidade.query.join(Membro, CicloDisponibilidade.membro_id == Membro.id)
        .filter(CicloDisponibilidade.id == ciclo_id, Membro.comunidade_id == comunidade.id)
        .first_or_404()
    )
    membro_id = ciclo.membro_id
    form = AcaoForm()

    if not form.validate_on_submit():
        flash("Acao invalida.", "danger")
        return redirect(url_for("comunidade.disponibilidade", comunidade_id=comunidade.id, membro_id=membro_id))

    nome = ciclo.nome
    db.session.delete(ciclo)
    db.session.commit()
    flash(f'Ciclo "{nome}" removido.', "success")
    return redirect(url_for("comunidade.disponibilidade", comunidade_id=comunidade.id, membro_id=membro_id))


# Mesma lista de app/ministerio/routes.py::MESES_PT -- duplicada de proposito
# (nao importada) pra nao criar dependencia de import entre os dois modulos,
# ver historico de import circular entre comunidade/convites/ministerio.
_MESES_PT = [
    "", "Janeiro", "Fevereiro", "Marco", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
]


def _navegacao_calendario_comunidade(ano, mes):
    mes_anterior = mes - 1
    ano_mes_anterior = ano
    if mes_anterior < 1:
        mes_anterior = 12
        ano_mes_anterior -= 1

    proximo_mes = mes + 1
    ano_proximo_mes = ano
    if proximo_mes > 12:
        proximo_mes = 1
        ano_proximo_mes += 1

    return (ano_mes_anterior, mes_anterior), (ano_proximo_mes, proximo_mes)


@bp.route("/<int:comunidade_id>/calendario")
@login_required
def calendario(comunidade_id):
    """Igual ao calendario de um Ministerio (app/ministerio/routes.py::calendario),
    so que juntando as escalas de TODOS os Ministerios da Comunidade numa
    grade so -- pra quem lidera varios ministerios nao precisar ficar
    trocando de tela pra ver o mes inteiro."""
    comunidade, eh_dono = _comunidade_visivel_ou_404(comunidade_id)
    hoje = date.today()

    ano = request.args.get("ano", type=int) or hoje.year
    mes = request.args.get("mes", type=int) or hoje.month
    if not (1 <= mes <= 12):
        mes = hoje.month

    semanas = calendar.Calendar(firstweekday=6).monthdatescalendar(ano, mes)
    while len(semanas) < 6:
        ultimo_dia = semanas[-1][-1]
        semanas.append([ultimo_dia + timedelta(days=i) for i in range(1, 8)])

    escalas_do_mes = [
        e for ministerio in comunidade.ministerios for e in ministerio.escalas
        if e.data and e.data.year == ano and e.data.month == mes
    ]
    escalas_por_dia = {}
    for escala in escalas_do_mes:
        escalas_por_dia.setdefault(escala.data, []).append((escala, escala.cor))

    (ano_anterior, mes_anterior), (ano_proximo, mes_proximo) = _navegacao_calendario_comunidade(ano, mes)

    return render_template(
        "comunidade/calendario.html",
        comunidade=comunidade,
        semanas=semanas,
        mes=mes,
        ano=ano,
        nome_mes=_MESES_PT[mes],
        mes_ano_texto=f"{_MESES_PT[mes].lower()} de {ano}",
        escalas_por_dia=escalas_por_dia,
        legenda=[(e, e.cor) for e in escalas_do_mes],
        ano_anterior=ano_anterior,
        mes_anterior=mes_anterior,
        ano_proximo=ano_proximo,
        mes_proximo=mes_proximo,
        hoje=hoje,
    )


@bp.route("/<int:comunidade_id>/lideres")
@login_required
def lideres(comunidade_id):
    """Diretorio de quem lidera algo nesta Comunidade -- contato (e-mail, e
    telefone se a pessoa tambem estiver no diretorio de Membro com o mesmo
    e-mail) e quais Ministerios cada um lidera. Admin da Comunidade tem
    autoridade em cascata sobre TODOS os ministerios (ver
    _eh_admin_da_comunidade), entao aparece vinculado a todos eles, nao so
    aos que tem uma linha propria em UsuarioMinisterio."""
    comunidade, eh_dono = _comunidade_visivel_ou_404(comunidade_id)

    nomes_ministerios = [m.nome for m in comunidade.ministerios]

    por_usuario = {}
    for papel in UsuarioComunidade.query.filter_by(comunidade_id=comunidade.id, papel="admin").all():
        por_usuario[papel.usuario_id] = {
            "usuario": papel.usuario, "eh_admin": True, "ministerios": list(nomes_ministerios),
        }

    for ministerio in comunidade.ministerios:
        for papel in ministerio.papeis_usuarios:
            if papel.papel != "lider":
                continue
            entrada = por_usuario.setdefault(
                papel.usuario_id, {"usuario": papel.usuario, "eh_admin": False, "ministerios": []}
            )
            if ministerio.nome not in entrada["ministerios"]:
                entrada["ministerios"].append(ministerio.nome)

    lista_lideres = sorted(
        por_usuario.values(),
        key=lambda item: (item["usuario"].name or item["usuario"].username or item["usuario"].email).lower(),
    )
    for item in lista_lideres:
        membro_vinculado = Membro.query.filter_by(
            comunidade_id=comunidade.id, email=item["usuario"].email
        ).first()
        item["telefone"] = membro_vinculado.telefone if membro_vinculado else None

    return render_template("comunidade/lideres.html", comunidade=comunidade, lideres=lista_lideres)


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

    link_convite = (
        url_for("comunidade.entrar_via_link", token=comunidade.token_convite_publico, _external=True)
        if comunidade.token_convite_publico else None
    )

    return render_template(
        "comunidade/papeis.html",
        comunidade=comunidade,
        form=form,
        papeis_atuais=papeis_atuais,
        convites_pendentes=convites_pendentes,
        link_convite=link_convite,
        acao_form=AcaoForm(),
    )


@bp.route("/<int:comunidade_id>/papeis/link/gerar", methods=["POST"])
@login_required
def gerar_link_convite(comunidade_id):
    """Gera (ou regenera, invalidando o anterior) o link generico de
    entrada -- ver Comunidade.gerar_novo_link_convite e
    entrar_via_link abaixo. Diferente do convite por e-mail (app/convites):
    qualquer um com o link entra direto como "membro", sem o admin precisar
    saber o e-mail de antemao."""
    comunidade = _comunidade_do_usuario_ou_404(comunidade_id)
    form = AcaoForm()

    if not form.validate_on_submit():
        flash("Acao invalida.", "danger")
        return redirect(url_for("comunidade.papeis", comunidade_id=comunidade.id))

    comunidade.gerar_novo_link_convite()
    db.session.commit()
    flash("Novo link de convite gerado! O link anterior (se existia) parou de funcionar.", "success")
    return redirect(url_for("comunidade.papeis", comunidade_id=comunidade.id))


@bp.route("/entrar/<token>", methods=["GET", "POST"])
def entrar_via_link(token):
    """Publica de proposito (sem @login_required) -- quem ainda nao tem
    conta precisa ver a tela pra saber que precisa entrar/cadastrar antes.
    Mesmo padrao de app/convites/routes.py::ver_convite (session
    "proximo_apos_login" pra voltar pra ca depois de autenticar), mas mais
    simples: nao existe um registro de Convite aqui, so o token generico
    da propria Comunidade, e o papel concedido e sempre "membro" (nunca
    "admin" -- esse link nao serve pra promover ninguem).

    GET nunca muda estado (so mostra a tela) -- entrar de fato exige POST
    com CSRF (AcaoForm), senao um GET simples (preview de link no
    WhatsApp/Telegram, prefetch do navegador, ou um <img src="..."> num
    site malicioso) poderia inscrever alguem autenticado sem intencao."""
    comunidade = Comunidade.query.filter_by(token_convite_publico=token).first_or_404()

    if not current_user.is_authenticated:
        session["proximo_apos_login"] = url_for("comunidade.entrar_via_link", token=token)
        return render_template("comunidade/entrar.html", comunidade=comunidade)

    papel_existente = UsuarioComunidade.query.filter_by(
        usuario_id=current_user.id, comunidade_id=comunidade.id
    ).first()
    if papel_existente:
        # So leitura (ja tem papel, entrar de novo nao muda nada) -- seguro
        # em GET. O link generico nunca rebaixa ninguem, so avisa.
        flash(f'Voce ja faz parte de "{comunidade.nome}".', "success")
        # main.dashboard nao lista comunidades (e so perfil/notificacoes) --
        # um "membro" simples tambem nao acessa comunidade.detalhe (admin-only,
        # ver _comunidade_do_usuario_ou_404), entao o destino que sobra pra
        # ele ver algo de fato e comunidade.escalados (mesma rota que
        # comunidade/lista.html usa pras comunidades em que so participa).
        # Sem isso, quem entra por aqui e nao e admin cai numa tela que nao
        # mostra nenhum indicio de que a entrada funcionou.
        destino = (
            url_for("comunidade.detalhe", comunidade_id=comunidade.id)
            if papel_existente.papel == "admin" else url_for("comunidade.escalados", comunidade_id=comunidade.id)
        )
        return redirect(destino)

    form = AcaoForm()
    if request.method == "POST" and form.validate_on_submit():
        db.session.add(UsuarioComunidade(usuario_id=current_user.id, comunidade_id=comunidade.id, papel="membro"))

        nome_novo_membro = current_user.name or current_user.username or current_user.email
        for admin in _admins_da_comunidade(comunidade):
            if admin.id == current_user.id:
                continue  # nunca notifica quem acabou de entrar sobre a propria entrada
            db.session.add(Notificacao(
                usuario_id=admin.id,
                titulo=f'{nome_novo_membro} entrou em "{comunidade.nome}"',
                mensagem=f'{nome_novo_membro} entrou na comunidade pelo link de convite.',
                tipo="novo_membro",
            ))

        db.session.commit()
        flash(f'Voce entrou em "{comunidade.nome}"!', "success")
        return redirect(url_for("comunidade.escalados", comunidade_id=comunidade.id))

    return render_template("comunidade/entrar.html", comunidade=comunidade, precisa_confirmar=True, acao_form=form)


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


