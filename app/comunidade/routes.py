"""Controller (C do MVC): rotas do modulo comunidade."""
import calendar
from datetime import date, time, timedelta

from flask import render_template, redirect, url_for, flash, request, abort, session
from flask_login import login_required, current_user
from flask_wtf.csrf import generate_csrf

from app.imagens import salvar_imagem, remover_imagem
from app.extensions import limiter
from app.db_utils import delete_cascade, primeiro_ou_404
from app.comunidade import bp
from app.comunidade.forms import ComunidadeForm, MembroDiretorioForm, CicloDisponibilidadeForm, AcaoForm, EventoForm
from app.comunidade.models import Comunidade, UsuarioComunidade, PAPEIS_COMUNIDADE, Evento, criar_comunidade
from app.ministerio.models import Ministerio
from app.auth.models import User
from app.escala.models import (
    Escala,
    Funcao,
    Membro,
    CicloDisponibilidade,
    SegmentoCiclo,
    DEPARTAMENTOS,
    STATUS_LABELS,
    STATUS_CORES,
    resumos_para_calendario_em_lote,
    ensaios_do_mes_por_dia,
)
from app.convites.forms import ConvidarForm
from app.convites.models import Convite
from app.convites.adicao import adicionar_ou_convidar


def _eh_admin_da_comunidade(comunidade, usuario):
    """Admin: Super Admin da plataforma (acesso total, bypassa qualquer
    checagem) OU dono original (Comunidade.usuario_id -- metadado historico,
    ver models.py) OU papel=admin em UsuarioComunidade (concedido por convite
    aceito, ver app/convites/CLAUDE.md)."""
    if usuario.eh_super_admin:
        return True
    if comunidade.usuario_id == usuario.id:
        return True
    return UsuarioComunidade.objects(
        comunidade_id=comunidade.id, usuario_id=usuario.id, papel="admin"
    ).first() is not None


def _eh_membro_da_comunidade(comunidade, usuario):
    """Papel=membro em UsuarioComunidade -- visibilidade de leitura, mesmo
    nivel do vinculo por e-mail com o diretorio (ver _comunidade_visivel_ou_404)."""
    return UsuarioComunidade.objects(
        comunidade_id=comunidade.id, usuario_id=usuario.id, papel="membro"
    ).first() is not None


def _admins_da_comunidade(comunidade):
    """Todas as contas com papel=admin nesta Comunidade, incluindo o dono
    original (Comunidade.usuario_id, que nem sempre tem uma linha propria em
    UsuarioComunidade -- ver criar_comunidade). Usado pra notificar (sino
    in-app) quando algo relevante acontece, ex: alguem entra via link."""
    ids_admin = {
        row.usuario_id for row in
        UsuarioComunidade.objects(comunidade_id=comunidade.id, papel="admin")
    }
    if comunidade.usuario_id:
        ids_admin.add(comunidade.usuario_id)
    if not ids_admin:
        return []
    return list(User.objects(id__in=ids_admin))


def _comunidade_do_usuario_ou_404(comunidade_id):
    """Acesso de ADMIN (leitura+escrita). Usado por toda rota de gestao.

    Sem essa checagem, qualquer pessoa logada poderia mexer numa comunidade de
    outra conta so adivinhando o id na URL.
    """
    comunidade = primeiro_ou_404(Comunidade.objects(id=comunidade_id))
    if not _eh_admin_da_comunidade(comunidade, current_user):
        abort(404)
    return comunidade


def _comunidade_visivel_ou_404(comunidade_id):
    """Acesso de LEITURA: admin OU papel=membro OU membro do diretorio cujo
    email bate com a conta logada -- mesmo mecanismo de match por e-mail ja
    usado para ligar notificacoes in-app (ver
    app/escala/routes.py::enviar_notificacoes_da_escala).
    """
    comunidade = primeiro_ou_404(Comunidade.objects(id=comunidade_id))
    eh_dono = _eh_admin_da_comunidade(comunidade, current_user)
    eh_membro_vinculado = eh_dono or _eh_membro_da_comunidade(comunidade, current_user) or Membro.objects(
        comunidade_id=comunidade.id, email=current_user.email
    ).first() is not None
    if not eh_membro_vinculado:
        abort(404)
    return comunidade, eh_dono


def _salvar_logo(arquivo):
    return salvar_imagem(arquivo)


def _remover_logo_antiga(caminho):
    remover_imagem(caminho)


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
        comunidades_dono = list(Comunidade.objects.order_by("nome"))
    else:
        ids_admin = [
            row.comunidade_id for row in
            UsuarioComunidade.objects(usuario_id=current_user.id, papel="admin")
        ]
        comunidades_dono = (
            list(Comunidade.objects(id__in=ids_admin).order_by("nome"))
            if ids_admin else []
        )

    comunidades_membro_ids = set(Membro.objects(email=current_user.email).distinct("comunidade_id"))
    ids_papel_membro = {
        row.comunidade_id for row in
        UsuarioComunidade.objects(usuario_id=current_user.id, papel="membro")
    }
    ids_dono = {c.id for c in comunidades_dono}
    ids_membro = (comunidades_membro_ids | ids_papel_membro) - ids_dono
    comunidades_participa = list(Comunidade.objects(id__in=ids_membro).order_by("nome")) if ids_membro else []

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
    ministerios = list(
        Ministerio.objects(comunidade_id=comunidade.id).order_by("nome")
    )
    # Membro (diretorio de escalacao) e UsuarioComunidade (conta que entrou
    # via convite/link) sao coisas diferentes -- ver models.py -- mas pra
    # quem esta contando "quantas pessoas" a comunidade tem, os dois contam.
    # Deduplicado por e-mail (mesmo criterio ja usado em comunidade.index)
    # pra nao contar duas vezes quem esta nos dois ao mesmo tempo.
    membros_diretorio = list(Membro.objects(comunidade_id=comunidade.id))
    emails_diretorio = {m.email.lower() for m in membros_diretorio if m.email}
    contas_vinculadas = list(UsuarioComunidade.objects(comunidade_id=comunidade.id))
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
        pedidos_diretorio=len(_pedidos_diretorio(comunidade, contas_vinculadas, emails_diretorio)),
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

        comunidade.save()
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

    # Comunidade, Ministerio e Membro (diretorio) agora vivem todos no Mongo
    # -- sem o cascade automatico que existia antes (cascade="all,
    # delete-orphan" em Comunidade.ministerios/membros), precisa apagar cada
    # lado explicitamente, na ordem certa: Ministerio primeiro (reaproveita
    # excluir_ministerio_em_cascata, que ja cuida do proprio Escala/Funcao
    # dele, ainda em SQLAlchemy) -- so depois Membro, ja que Funcao
    # referencia Membro e a exclusao ficaria inconsistente enquanto existir.
    from app.ministerio.routes import excluir_ministerio_em_cascata

    _remover_logo_antiga(comunidade.imagem)

    nome = comunidade.nome

    for ministerio in Ministerio.objects(comunidade_id=comunidade.id):
        excluir_ministerio_em_cascata(ministerio)

    for membro in Membro.objects(comunidade_id=comunidade.id):
        delete_cascade(membro)

    delete_cascade(comunidade)

    flash(f'Comunidade "{nome}" excluida.', "success")
    return redirect(url_for("comunidade.index"))


def _emails_do_diretorio(comunidade):
    return {
        m.email.strip().lower()
        for m in Membro.objects(comunidade_id=comunidade.id).only("email") if m.email
    }


def _pedidos_diretorio(comunidade, contas=None, emails_diretorio=None):
    """Contas com papel "membro" na comunidade (entraram pelo link ou por convite) que
    ainda nao estao no diretorio de escalacao (Membro, casado por e-mail) e
    que o admin nao recusou -- a lista "Aguardando entrar no diretorio"."""
    if contas is None:
        contas = UsuarioComunidade.objects(comunidade_id=comunidade.id)
    if emails_diretorio is None:
        emails_diretorio = _emails_do_diretorio(comunidade)
    pedidos = []
    for conta in contas:
        usuario = conta.usuario
        # So papel "membro" (quem entrou pelo link/convite de membro) -- admin
        # recebe o papel de proposito e e posto no diretorio a mao se precisar.
        if conta.papel != "membro" or conta.diretorio_recusado or usuario is None or not usuario.email:
            continue
        if usuario.email.strip().lower() not in emails_diretorio:
            pedidos.append(conta)
    return sorted(pedidos, key=lambda c: c.id)  # ordem de entrada


def _colocar_no_diretorio(comunidade, conta):
    """Cria o Membro do diretorio a partir da conta (nome + e-mail da conta,
    o mesmo e-mail que liga notificacoes/"Minha escala" a ela). Nao duplica
    se ja tiver alguem com esse e-mail."""
    usuario = conta.usuario
    if usuario.email.strip().lower() not in _emails_do_diretorio(comunidade):
        Membro(
            comunidade_id=comunidade.id,
            nome=(usuario.name or usuario.username or usuario.email.split("@")[0])[:120],
            email=usuario.email,
        ).save()
    if conta.diretorio_recusado:
        conta.diretorio_recusado = False
        conta.save()
    return usuario.name or usuario.username or usuario.email


@bp.route("/<int:comunidade_id>/membros/pedidos/<int:conta_id>/<any(aceitar, recusar):acao>", methods=["POST"])
@login_required
def responder_pedido_diretorio(comunidade_id, conta_id, acao):
    comunidade = _comunidade_do_usuario_ou_404(comunidade_id)
    conta = primeiro_ou_404(UsuarioComunidade.objects(id=conta_id, comunidade_id=comunidade.id))
    destino = url_for("comunidade.membros", comunidade_id=comunidade.id)
    if not AcaoForm().validate_on_submit() or conta.usuario is None:
        flash("Acao invalida.", "danger")
        return redirect(destino)

    if acao == "aceitar":
        nome = _colocar_no_diretorio(comunidade, conta)
        flash(f"{nome} entrou no diretorio -- ja pode ser escalado(a).", "success")
    else:
        conta.diretorio_recusado = True
        conta.save()
        nome = conta.usuario.name or conta.usuario.username or conta.usuario.email
        flash(f"{nome} nao vai entrar no diretorio (continua com a conta na comunidade).", "success")
    return redirect(destino)


@bp.route("/<int:comunidade_id>/membros/pedidos/aceitar-todos", methods=["POST"])
@login_required
def aceitar_todos_pedidos_diretorio(comunidade_id):
    comunidade = _comunidade_do_usuario_ou_404(comunidade_id)
    destino = url_for("comunidade.membros", comunidade_id=comunidade.id)
    if not AcaoForm().validate_on_submit():
        flash("Acao invalida.", "danger")
        return redirect(destino)
    pedidos = _pedidos_diretorio(comunidade)
    for conta in pedidos:
        _colocar_no_diretorio(comunidade, conta)
    flash(f"{len(pedidos)} pessoa(s) adicionada(s) ao diretorio.", "success")
    return redirect(destino)


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
        membro.save()
        flash(f"{membro.nome} adicionado(a) ao diretorio.", "success")
        return redirect(proximo or url_for("comunidade.membros", comunidade_id=comunidade.id))

    diretorio = list(Membro.objects(comunidade_id=comunidade.id).order_by("nome"))

    # Diretorio (Membro, acima) e contas vinculadas (UsuarioComunidade) sao
    # coisas diferentes -- ver models.py -- mas quem entra em "Membros"
    # esperando ver quem de fato entrou pela comunidade (convite/link)
    # precisa ver as duas listas, senao a contagem em comunidade.detalhe nao
    # bate com ninguem aparecendo aqui.
    contas_vinculadas = sorted(
        UsuarioComunidade.objects(comunidade_id=comunidade.id),
        key=lambda uc: (uc.papel, (uc.usuario.name or uc.usuario.username or uc.usuario.email).lower()),
    )

    emails_diretorio = {m.email.strip().lower() for m in diretorio if m.email}
    return render_template(
        "comunidade/membros.html",
        comunidade=comunidade,
        diretorio=diretorio,
        contas_vinculadas=contas_vinculadas,
        pedidos=_pedidos_diretorio(comunidade, contas_vinculadas, emails_diretorio),
        emails_diretorio=emails_diretorio,
        form=form,
        acao_form=AcaoForm(),
        proximo=proximo,
    )


@bp.route("/<int:comunidade_id>/membros/<int:membro_id>/excluir", methods=["POST"])
@login_required
def excluir_membro(comunidade_id, membro_id):
    comunidade = _comunidade_do_usuario_ou_404(comunidade_id)
    membro = primeiro_ou_404(Membro.objects(id=membro_id, comunidade_id=comunidade.id))
    form = AcaoForm()

    if not form.validate_on_submit():
        flash("Acao invalida.", "danger")
        return redirect(url_for("comunidade.membros", comunidade_id=comunidade.id))

    if Funcao.objects(membro_id=membro.id).count() > 0:
        flash(f"Remova {membro.nome} das escalas antes de excluir do diretorio.", "danger")
        return redirect(url_for("comunidade.membros", comunidade_id=comunidade.id))

    delete_cascade(membro)
    flash(f"{membro.nome} removido(a) do diretorio.", "success")
    return redirect(url_for("comunidade.membros", comunidade_id=comunidade.id))


@bp.route("/<int:comunidade_id>/membros/<int:membro_id>/disponibilidade")
@login_required
def disponibilidade(comunidade_id, membro_id):
    comunidade = _comunidade_do_usuario_ou_404(comunidade_id)
    membro = primeiro_ou_404(Membro.objects(id=membro_id, comunidade_id=comunidade.id))

    ciclos = list(
        CicloDisponibilidade.objects(membro_id=membro.id).order_by("-data_inicio")
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
    membro = primeiro_ou_404(Membro.objects(id=membro_id, comunidade_id=comunidade.id))
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
    ciclo.save()

    for ordem, segmento in enumerate(segmentos):
        SegmentoCiclo(
            ciclo_id=ciclo.id,
            ordem=ordem,
            nome=segmento["nome"],
            duracao_dias=segmento["duracao_dias"],
            indisponivel=segmento["indisponivel"],
        ).save()

    flash(f'Ciclo "{ciclo.nome}" cadastrado pra {membro.nome}.', "success")
    return redirect(url_for("comunidade.disponibilidade", comunidade_id=comunidade.id, membro_id=membro.id))


@bp.route("/<int:comunidade_id>/disponibilidade/<int:ciclo_id>/excluir", methods=["POST"])
@login_required
def excluir_disponibilidade(comunidade_id, ciclo_id):
    comunidade = _comunidade_do_usuario_ou_404(comunidade_id)
    ciclo = primeiro_ou_404(CicloDisponibilidade.objects(id=ciclo_id))
    # Autorizacao: o ciclo precisa pertencer a um Membro desta comunidade
    # (sem join possivel entre CicloDisponibilidade e Membro, os dois no
    # Mongo agora -- confere em duas etapas em vez de uma so consulta).
    if ciclo.membro is None or ciclo.membro.comunidade_id != comunidade.id:
        abort(404)
    membro_id = ciclo.membro_id
    form = AcaoForm()

    if not form.validate_on_submit():
        flash("Acao invalida.", "danger")
        return redirect(url_for("comunidade.disponibilidade", comunidade_id=comunidade.id, membro_id=membro_id))

    nome = ciclo.nome
    delete_cascade(ciclo)
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

    # Consultas em lote (nao 1 por Ministerio + 1 por Escala + 1 por Membro
    # escalado) -- filtro de data direto no banco, nao em Python sobre o
    # historico inteiro de cada ministerio.
    ministerios_da_comunidade = list(comunidade.ministerios)
    nomes_por_ministerio = {m.id: m.nome for m in ministerios_da_comunidade}
    primeiro_dia_mes = date(ano, mes, 1)
    ultimo_dia_mes = date(ano, mes, calendar.monthrange(ano, mes)[1])
    escalas_do_mes = list(Escala.objects(
        ministerio_id__in=list(nomes_por_ministerio.keys()),
        data__gte=primeiro_dia_mes, data__lte=ultimo_dia_mes,
    ))
    escalas_por_dia = {}
    for escala in escalas_do_mes:
        escalas_por_dia.setdefault(escala.data, []).append((escala, escala.cor))

    # Igual ao de um Ministerio (ver ministerio.routes._dados_calendario),
    # so que com o nome do ministerio junto -- aqui um mesmo dia pode ter
    # escalas de ministerios diferentes.
    ensaios_por_dia, escalas_dos_ensaios = ensaios_do_mes_por_dia(
        primeiro_dia_mes, ultimo_dia_mes, ministerio_ids=list(nomes_por_ministerio.keys())
    )
    ids_no_mes = {e.id for e in escalas_do_mes}
    escalas_pra_preview = escalas_do_mes + [e for e in escalas_dos_ensaios if e.id not in ids_no_mes]

    previews_calendario = resumos_para_calendario_em_lote(escalas_pra_preview)
    for escala in escalas_pra_preview:
        previews_calendario[escala.id]["ministerio"] = nomes_por_ministerio.get(escala.ministerio_id)

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
        ensaios_por_dia=ensaios_por_dia,
        legenda=[(e, e.cor) for e in escalas_do_mes],
        ano_anterior=ano_anterior,
        mes_anterior=mes_anterior,
        ano_proximo=ano_proximo,
        mes_proximo=mes_proximo,
        hoje=hoje,
        previews_calendario=previews_calendario,
        eh_dono=eh_dono,
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
    for papel in UsuarioComunidade.objects(comunidade_id=comunidade.id, papel="admin"):
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
        membro_vinculado = Membro.objects(
            comunidade_id=comunidade.id, email=item["usuario"].email
        ).first()
        item["telefone"] = membro_vinculado.telefone if membro_vinculado else None

    return render_template("comunidade/lideres.html", comunidade=comunidade, eh_dono=eh_dono, lideres=lista_lideres)


@bp.route("/<int:comunidade_id>/eventos", methods=["GET", "POST"])
@login_required
def eventos(comunidade_id):
    """Eventos pontuais da comunidade (conferencia, culto especial etc.) --
    diferente de Escala, que e ensaio/culto de rotina escalado por
    Ministerio (ver Evento em models.py). Qualquer vinculado ve a lista;
    so admin cria/exclui."""
    comunidade, eh_dono = _comunidade_visivel_ou_404(comunidade_id)
    form = EventoForm()

    if form.validate_on_submit():
        if not eh_dono:
            flash("Apenas administradores podem criar eventos.", "danger")
            return redirect(url_for("comunidade.eventos", comunidade_id=comunidade.id))

        evento = Evento(
            comunidade_id=comunidade.id,
            nome=form.nome.data.strip(),
            descricao=(form.descricao.data or "").strip() or None,
            data=form.data.data,
            data_fim=form.data_fim.data,
            horario=form.horario.data,
            local=(form.local.data or "").strip() or None,
        )
        evento.save()
        flash(f'Evento "{evento.nome}" criado!', "success")
        return redirect(url_for("comunidade.eventos", comunidade_id=comunidade.id))

    hoje = date.today()
    todos_eventos = list(Evento.objects(comunidade_id=comunidade.id).order_by("data"))
    proximos = [e for e in todos_eventos if (e.data_fim or e.data) >= hoje]
    passados = [e for e in reversed(todos_eventos) if (e.data_fim or e.data) < hoje]

    return render_template(
        "comunidade/eventos.html",
        comunidade=comunidade,
        eh_dono=eh_dono,
        form=form,
        proximos=proximos,
        passados=passados,
        acao_form=AcaoForm(),
    )


@bp.route("/<int:comunidade_id>/eventos/<int:evento_id>/excluir", methods=["POST"])
@login_required
def excluir_evento(comunidade_id, evento_id):
    comunidade = _comunidade_do_usuario_ou_404(comunidade_id)
    evento = primeiro_ou_404(Evento.objects(id=evento_id, comunidade_id=comunidade.id))
    form = AcaoForm()

    if not form.validate_on_submit():
        flash("Acao invalida.", "danger")
        return redirect(url_for("comunidade.eventos", comunidade_id=comunidade.id))

    nome = evento.nome
    evento.delete()
    flash(f'Evento "{nome}" excluido.', "success")
    return redirect(url_for("comunidade.eventos", comunidade_id=comunidade.id))


@bp.route("/<int:comunidade_id>/escalados")
@login_required
def escalados(comunidade_id):
    comunidade, eh_dono = _comunidade_visivel_ou_404(comunidade_id)

    data_de = request.args.get("data_de", "").strip()
    data_ate = request.args.get("data_ate", "").strip()
    departamento = request.args.get("departamento", "").strip()
    funcao_nome = request.args.get("funcao", "").strip()

    # Ministerio/Escala/Funcao agora vivem no Mongo -- sem join possivel
    # entre eles (SQLAlchemy). Busca em duas etapas: primeiro as Escalas do
    # periodo/ministerios da comunidade, depois as Funcoes preenchidas
    # dessas escalas -- ordena em Python (dá pra fazer com aggregation
    # pipeline, mas nao compensa a complexidade nessa escala de dados).
    ministerios = list(Ministerio.objects(comunidade_id=comunidade.id).order_by("nome"))
    ids_ministerios = [m.id for m in ministerios]
    filtro_escala = {"ministerio_id__in": ids_ministerios}
    if data_de:
        filtro_escala["data__gte"] = date.fromisoformat(data_de)
    if data_ate:
        filtro_escala["data__lte"] = date.fromisoformat(data_ate)
    if departamento:
        filtro_escala["departamento"] = departamento
    escalas_relevantes = {e.id: e for e in Escala.objects(**filtro_escala)}

    filtro_funcao = {"escala_id__in": list(escalas_relevantes.keys()), "membro_id__ne": None}
    if funcao_nome:
        filtro_funcao["nome__icontains"] = funcao_nome

    funcoes = list(Funcao.objects(**filtro_funcao))
    funcoes.sort(key=lambda f: (
        escalas_relevantes[f.escala_id].data is None,
        escalas_relevantes[f.escala_id].data or date.min,
        escalas_relevantes[f.escala_id].horario is None,
        escalas_relevantes[f.escala_id].horario or time.min,
    ))

    return render_template(
        "comunidade/escalados.html",
        comunidade=comunidade,
        eh_dono=eh_dono,
        ministerios=ministerios,
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
        # Direto ou por convite, conforme a preferencia de privacidade da
        # pessoa -- ver app/convites/adicao.py.
        mensagem, categoria = adicionar_ou_convidar(
            "comunidade", comunidade, form.papel.data, form.email.data, current_user
        )
        flash(mensagem, categoria)
        return redirect(url_for("comunidade.papeis", comunidade_id=comunidade.id))

    papeis_atuais = list(
        UsuarioComunidade.objects(comunidade_id=comunidade.id).order_by("papel")
    )
    convites_pendentes = list(
        Convite.objects(escopo_tipo="comunidade", escopo_id=comunidade.id, status="pendente")
        .order_by("-criado_em")
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
    comunidade.save()
    flash("Novo link de convite gerado! O link anterior (se existia) parou de funcionar.", "success")
    return redirect(url_for("comunidade.papeis", comunidade_id=comunidade.id))


@bp.route("/entrar/<token>", methods=["GET", "POST"])
@limiter.limit("30 per minute")
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
    from app.convites.link_publico import entrar_na_comunidade, eh_navegacao_direta, guardar_entrada_pendente

    comunidade = primeiro_ou_404(Comunidade.objects(token_convite_publico=token))
    tela = dict(nome_escopo=comunidade.nome, tipo_escopo="comunidade", imagem_escopo=comunidade.imagem)

    if not current_user.is_authenticated:
        guardar_entrada_pendente("comunidade", token, url_for("comunidade.entrar_via_link", token=token))
        return render_template("comunidade/entrar.html", **tela)

    form = AcaoForm()
    # Abrir o link no navegador ja e o aceite (entra direto). POST e o botao
    # da tela de confirmacao, pra navegador que nao manda Sec-Fetch-*.
    if (request.method == "POST" and form.validate_on_submit()) or (
        request.method == "GET" and eh_navegacao_direta(request)
    ) or UsuarioComunidade.objects(usuario_id=current_user.id, comunidade_id=comunidade.id).first():
        destino, mensagem = entrar_na_comunidade(current_user, comunidade)
        flash(mensagem, "success")
        return redirect(destino)

    return render_template("comunidade/entrar.html", precisa_confirmar=True, acao_form=form, **tela)


@bp.route("/<int:comunidade_id>/papeis/<int:usuario_comunidade_id>/remover", methods=["POST"])
@login_required
def remover_papel(comunidade_id, usuario_comunidade_id):
    comunidade = _comunidade_do_usuario_ou_404(comunidade_id)
    papel = primeiro_ou_404(UsuarioComunidade.objects(id=usuario_comunidade_id, comunidade_id=comunidade.id))
    form = AcaoForm()

    if not form.validate_on_submit():
        flash("Acao invalida.", "danger")
        return redirect(url_for("comunidade.papeis", comunidade_id=comunidade.id))

    nome = papel.usuario.name or papel.usuario.username or papel.usuario.email
    papel.delete()
    flash(f"{nome} removido(a) dos administradores/membros da comunidade.", "success")
    return redirect(url_for("comunidade.papeis", comunidade_id=comunidade.id))


@bp.route("/<int:comunidade_id>/papeis/<int:usuario_comunidade_id>/alterar-papel", methods=["POST"])
@login_required
def alterar_papel(comunidade_id, usuario_comunidade_id):
    """Promove um membro a admin ou rebaixa um admin a membro -- alterna
    entre os dois unicos valores de PAPEIS_COMUNIDADE. Bloqueia rebaixar o
    ultimo admin: sem essa checagem, a comunidade ficaria sem ninguem capaz
    de acessar /papeis (_comunidade_do_usuario_ou_404 exige papel=admin ou
    ser o dono original) pra reverter o proprio erro."""
    comunidade = _comunidade_do_usuario_ou_404(comunidade_id)
    papel = primeiro_ou_404(UsuarioComunidade.objects(id=usuario_comunidade_id, comunidade_id=comunidade.id))
    form = AcaoForm()

    if not form.validate_on_submit():
        flash("Acao invalida.", "danger")
        return redirect(url_for("comunidade.papeis", comunidade_id=comunidade.id))

    nome = papel.usuario.name or papel.usuario.username or papel.usuario.email

    if papel.papel == "admin":
        total_admins = UsuarioComunidade.objects(comunidade_id=comunidade.id, papel="admin").count()
        if total_admins <= 1:
            flash("Nao e possivel rebaixar o ultimo administrador. Promova outra pessoa antes.", "danger")
            return redirect(url_for("comunidade.papeis", comunidade_id=comunidade.id))
        papel.papel = "membro"
        papel.save()
        flash(f"{nome} agora e membro (nao e mais administrador).", "success")
    else:
        papel.papel = "admin"
        papel.save()
        flash(f"{nome} agora e administrador(a) da comunidade.", "success")

    return redirect(url_for("comunidade.papeis", comunidade_id=comunidade.id))


@bp.route("/<int:comunidade_id>/papeis/convite/<int:convite_id>/cancelar", methods=["POST"])
@login_required
def cancelar_convite(comunidade_id, convite_id):
    comunidade = _comunidade_do_usuario_ou_404(comunidade_id)
    convite = primeiro_ou_404(Convite.objects(
        id=convite_id, escopo_tipo="comunidade", escopo_id=comunidade.id, status="pendente"
    ))
    form = AcaoForm()

    if not form.validate_on_submit():
        flash("Acao invalida.", "danger")
        return redirect(url_for("comunidade.papeis", comunidade_id=comunidade.id))

    convite.delete()
    flash("Convite cancelado.", "success")
    return redirect(url_for("comunidade.papeis", comunidade_id=comunidade.id))


