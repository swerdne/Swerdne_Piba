"""Controller (C do MVC): rotas do modulo ministerio."""
import calendar
import random
import string
from datetime import date, datetime, timedelta, timezone

from flask import render_template, redirect, url_for, flash, request, abort, jsonify
from flask_login import login_required, current_user

from app.imagens import salvar_imagem, remover_imagem
from app.extensions import limiter
from app.db_utils import delete_cascade, primeiro_ou_404
from app.ministerio import bp
from app.ministerio.forms import MinisterioForm, AcaoForm, CriancaForm, CheckoutForm
from app.ministerio.models import (
    Ministerio,
    UsuarioMinisterio,
    PAPEIS_MINISTERIO,
    Crianca,
    CheckInCrianca,
    criar_ministerio,
)
from app.escala.models import (
    resumos_para_calendario_em_lote, Musica, ItemRepertorio, VersaoCifra,
    blocos_da_letra, projecao_da_cifra, tem_acordes, detectar_tom,
    TONS_MAIORES, TONS_MENORES,
)
from app.escala.forms import MusicaForm, LetraProjecaoForm, CifraLouvorForm
from app.convites.forms import ConvidarForm
from app.convites.models import Convite
from app.convites.adicao import adicionar_ou_convidar

MESES_PT = [
    "", "Janeiro", "Fevereiro", "Marco", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
]

DIAS_SEMANA_PT = [
    "segunda-feira", "terca-feira", "quarta-feira", "quinta-feira",
    "sexta-feira", "sabado", "domingo",
]


def _eh_lider_do_ministerio(ministerio, usuario):
    """Lider: admin da comunidade dona (autoridade cascata pra qualquer
    ministerio dela, mesmo sem linha propria em UsuarioMinisterio) OU
    papel=lider em UsuarioMinisterio (concedido por convite aceito)."""
    from app.comunidade.routes import _eh_admin_da_comunidade

    if _eh_admin_da_comunidade(ministerio.comunidade, usuario):
        return True
    return UsuarioMinisterio.objects(
        ministerio_id=ministerio.id, usuario_id=usuario.id, papel="lider"
    ).first() is not None


def _lideres_do_ministerio(ministerio):
    """Todas as contas com autoridade de lider sobre este Ministerio --
    dono original da Comunidade, quem tem papel=admin nela, e quem tem
    papel=lider no proprio Ministerio. Usado pra notificar (ver
    escala.routes::_notificar_lideres_do_ministerio); mesma logica de
    autoridade de _eh_lider_do_ministerio, so que devolvendo a lista em vez
    de checar uma conta especifica."""
    from app.auth.models import User
    from app.comunidade.models import UsuarioComunidade

    comunidade = ministerio.comunidade
    ids_admin_comunidade = {
        row.usuario_id for row in
        UsuarioComunidade.objects(comunidade_id=comunidade.id, papel="admin")
    }
    if comunidade.usuario_id:
        ids_admin_comunidade.add(comunidade.usuario_id)

    ids_lider_ministerio = {
        row.usuario_id for row in
        UsuarioMinisterio.objects(ministerio_id=ministerio.id, papel="lider")
    }

    ids = ids_admin_comunidade | ids_lider_ministerio
    if not ids:
        return []
    return list(User.objects(id__in=ids))


def _eh_membro_do_ministerio(ministerio, usuario):
    """Papel=membro em UsuarioMinisterio -- participa do ministerio,
    visualiza as escalas dele (leitura)."""
    return UsuarioMinisterio.objects(
        ministerio_id=ministerio.id, usuario_id=usuario.id, papel="membro"
    ).first() is not None


def _ministerio_do_usuario_ou_404(ministerio_id):
    """Acesso ESTRITO de admin da comunidade -- so pras acoes de CRUD do
    proprio Ministerio (criar/editar/excluir). Um lider de ministerio NAO
    passa aqui (pode gerenciar o CONTEUDO do ministerio -- escalas, turnos,
    membros -- mas nao apagar/renomear o ministerio em si); ver
    _ministerio_gerenciavel_ou_404 pra essa checagem mais ampla."""
    from app.comunidade.routes import _eh_admin_da_comunidade

    ministerio = primeiro_ou_404(Ministerio.objects(id=ministerio_id))
    if not _eh_admin_da_comunidade(ministerio.comunidade, current_user):
        abort(404)
    return ministerio


def _ministerio_gerenciavel_ou_404(ministerio_id):
    """Acesso de GESTAO DE CONTEUDO: admin da comunidade OU lider do
    ministerio. Usado por toda acao dentro do ministerio que nao seja CRUD do
    ministerio em si -- criar/editar escala ou turno de rodizio,
    adicionar/remover membro de funcao, adicionar convidado, etc. (ver
    app/escala/routes.py, app/plantao/routes.py)."""
    ministerio = primeiro_ou_404(Ministerio.objects(id=ministerio_id))
    if not _eh_lider_do_ministerio(ministerio, current_user):
        abort(404)
    return ministerio


def _ministerio_visivel_ou_404(ministerio_id):
    """Acesso de LEITURA: admin da comunidade, lider/membro do ministerio, OU
    qualquer membro da propria Comunidade (papel=membro em UsuarioComunidade)
    -- visibilidade de leitura de TODOS os ministerios da comunidade, nao so
    os que tem convite especifico via UsuarioMinisterio. Retorna (ministerio,
    pode_gerenciar) -- pode_gerenciar distingue quem so visualiza de quem
    tambem gerencia conteudo (admin/lider), pro template esconder acoes de
    escrita (editar, convidar etc.)."""
    from app.comunidade.routes import _eh_membro_da_comunidade

    ministerio = primeiro_ou_404(Ministerio.objects(id=ministerio_id))
    pode_gerenciar = _eh_lider_do_ministerio(ministerio, current_user)
    eh_visivel = (
        pode_gerenciar
        or _eh_membro_do_ministerio(ministerio, current_user)
        or _eh_membro_da_comunidade(ministerio.comunidade, current_user)
    )
    if not eh_visivel:
        abort(404)
    return ministerio, pode_gerenciar


def _salvar_logo(arquivo):
    return salvar_imagem(arquivo)


def _remover_logo_antiga(caminho):
    remover_imagem(caminho)


@bp.route("/comunidade/<int:comunidade_id>/nova", methods=["GET", "POST"])
@login_required
def nova(comunidade_id):
    from app.comunidade.routes import _comunidade_do_usuario_ou_404

    comunidade = _comunidade_do_usuario_ou_404(comunidade_id)
    form = MinisterioForm()

    if form.validate_on_submit():
        imagem = _salvar_logo(form.imagem.data) if form.imagem.data else None
        ministerio = criar_ministerio(
            comunidade_id=comunidade.id,
            nome=form.nome.data.strip(),
            descricao=(form.descricao.data or "").strip() or None,
            imagem=imagem,
        )
        ministerio.dias_culto = (
            ",".join(str(d) for d in sorted(form.dias_culto.data)) if form.dias_culto.data else None
        )
        ministerio.save()
        flash(f'Ministerio "{ministerio.nome}" criado!', "success")
        return redirect(url_for("ministerio.detalhe", ministerio_id=ministerio.id))

    return render_template("ministerio/nova.html", form=form, comunidade=comunidade)


def _navegacao_calendario(ano, mes):
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


def _dados_calendario(ministerio, hoje):
    """Monta a grade do mes (linhas=semanas, colunas=dias da semana) e os dados
    de cor/legenda das escalas daquele mes. Usado tanto pelo widget pequeno em
    ministerio.detalhe quanto pela pagina cheia em ministerio.calendario."""
    ano = request.args.get("ano", type=int) or hoje.year
    mes = request.args.get("mes", type=int) or hoje.month
    if not (1 <= mes <= 12):
        mes = hoje.month

    semanas = calendar.Calendar(firstweekday=6).monthdatescalendar(ano, mes)
    # Sempre 6 linhas (7x6), como um date picker de app -- monthdatescalendar
    # devolve so as semanas necessarias (4 a 6), entao completa com a(s)
    # semana(s) seguinte(s) quando o mes precisar de menos.
    while len(semanas) < 6:
        ultimo_dia = semanas[-1][-1]
        semanas.append([ultimo_dia + timedelta(days=i) for i in range(1, 8)])

    # Mesma cor ja usada na lista de escalas ao lado (escala.cor, por
    # departamento) -- nao uma paleta separada, pra manter os dois lugares
    # visualmente consistentes. Filtro de data direto na consulta (nao em
    # Python sobre TODAS as escalas do ministerio) -- evita carregar
    # historico inteiro so pra descartar quase tudo depois.
    from app.escala.models import Escala, ensaios_do_mes_por_dia

    primeiro_dia_mes = date(ano, mes, 1)
    ultimo_dia_mes = date(ano, mes, calendar.monthrange(ano, mes)[1])
    escalas_do_mes = list(Escala.objects(
        ministerio_id=ministerio.id, data__gte=primeiro_dia_mes, data__lte=ultimo_dia_mes
    ))
    escalas_por_dia = {}
    for escala in escalas_do_mes:
        escalas_por_dia.setdefault(escala.data, []).append((escala, escala.cor))

    ensaios_por_dia, escalas_dos_ensaios = ensaios_do_mes_por_dia(
        primeiro_dia_mes, ultimo_dia_mes, ministerio_ids=[ministerio.id]
    )
    ids_no_mes = {e.id for e in escalas_do_mes}
    escalas_pra_preview = escalas_do_mes + [e for e in escalas_dos_ensaios if e.id not in ids_no_mes]

    (ano_anterior, mes_anterior), (ano_proximo, mes_proximo) = _navegacao_calendario(ano, mes)

    return {
        "semanas": semanas,
        "mes": mes,
        "ano": ano,
        "nome_mes": MESES_PT[mes],
        "mes_ano_texto": f"{MESES_PT[mes].lower()} de {ano}",
        "escalas_por_dia": escalas_por_dia,
        "ensaios_por_dia": ensaios_por_dia,
        "legenda": [(e, e.cor) for e in escalas_do_mes],
        "ano_anterior": ano_anterior,
        "mes_anterior": mes_anterior,
        "ano_proximo": ano_proximo,
        "mes_proximo": mes_proximo,
        "hoje": hoje,
        "previews_calendario": resumos_para_calendario_em_lote(escalas_pra_preview),
    }


def _escalas_agrupadas_por_turno(ministerio, hoje):
    """Escalas manuais aparecem uma a uma, como sempre. Escalas geradas por
    rodizio (plantao_turno_id preenchido) sao agrupadas por turno de origem
    -- a listagem mostra so 1 capa por turno (a proxima ocorrencia, ou a mais
    recente ja ocorrida se nao houver nenhuma futura) em vez de um card por
    ocorrencia, que poluiria a lista pra turnos recorrentes de longa duracao.

    EXCECAO: turnos com uma Escala de origem vinculada (Escala.turno_plantao_origem_id
    -- "Criar turno de rodizio com esta equipe", ver app/plantao/CLAUDE.md) nao
    geram capa nenhuma aqui -- a propria escala de origem (que ja aparece na
    lista como escala manual) e o unico ponto de entrada, com um link pra
    plantao.detalhe (ver escala/detalhe.html). Sem isso, a escala de origem E
    a capa do turno apareceriam como duas entradas parecidas na mesma lista.
    """
    # 1 unica leitura de ministerio.escalas (nao 2) -- e o turno.escala_origem
    # de cada turno de rodizio em lote (1 consulta pra todos, nao 1 por
    # turno+escala, ver Escala.turno_plantao_origem_id).
    todas_escalas = list(ministerio.escalas)
    escalas_manuais = [e for e in todas_escalas if e.plantao_turno_id is None]
    escalas_de_rodizio = [e for e in todas_escalas if e.plantao_turno_id is not None]

    ids_turnos_com_origem = set()
    ids_turnos = {e.plantao_turno_id for e in escalas_de_rodizio}
    if ids_turnos:
        from app.escala.models import Escala
        ids_turnos_com_origem = {
            e.turno_plantao_origem_id
            for e in Escala.objects(turno_plantao_origem_id__in=list(ids_turnos))
        }

    ocorrencias_por_turno = {}
    for escala in escalas_de_rodizio:
        if escala.plantao_turno_id in ids_turnos_com_origem:
            continue
        ocorrencias_por_turno.setdefault(escala.plantao_turno_id, []).append(escala)

    capas = []
    qtd_ocorrencias_por_turno = {}
    for turno_id, ocorrencias in ocorrencias_por_turno.items():
        ocorrencias.sort(key=lambda e: e.data)
        futuras = [e for e in ocorrencias if e.data >= hoje]
        capas.append(futuras[0] if futuras else ocorrencias[-1])
        qtd_ocorrencias_por_turno[turno_id] = len(ocorrencias)

    escalas = sorted(
        escalas_manuais + capas,
        key=lambda e: (e.data is None, e.data, e.horario is None, e.horario),
    )
    return escalas, qtd_ocorrencias_por_turno


@bp.route("/<int:ministerio_id>")
@login_required
def detalhe(ministerio_id):
    from app.comunidade.routes import _eh_admin_da_comunidade

    ministerio, pode_gerenciar = _ministerio_visivel_ou_404(ministerio_id)
    eh_admin = _eh_admin_da_comunidade(ministerio.comunidade, current_user)

    hoje = date.today()
    escalas, qtd_ocorrencias_por_turno = _escalas_agrupadas_por_turno(ministerio, hoje)
    # Mesma excecao de _escalas_agrupadas_por_turno acima: um turno com escala
    # de origem vinculada (Escala.turno_plantao_origem_id) ja aparece na lista
    # de Escalas, atraves da propria escala de origem -- sem isso aqui, ele
    # apareceria DE NOVO, agora como card independente nesta secao, dando
    # impressao de que o rodizio existe solto fora da escala. escala_origem
    # de todos os turnos em lote (1 consulta, nao 1 por turno).
    todos_turnos = list(ministerio.turnos_plantao)
    ids_turnos_com_origem_geral = set()
    if todos_turnos:
        from app.escala.models import Escala
        ids_turnos_com_origem_geral = {
            e.turno_plantao_origem_id
            for e in Escala.objects(turno_plantao_origem_id__in=[t.id for t in todos_turnos])
        }
    turnos_plantao = sorted(
        (t for t in todos_turnos if t.id not in ids_turnos_com_origem_geral),
        key=lambda t: t.nome,
    )

    dados_calendario = _dados_calendario(ministerio, hoje)

    # Proximo ensaio (nao cancelado) de cada escala da lista, numa consulta so.
    from app.escala.models import Ensaio
    proximo_ensaio_por_escala = {}
    if escalas:
        for ensaio in Ensaio.objects(
            escala_id__in=[e.id for e in escalas], data__gte=hoje, cancelado__ne=True
        ).order_by("data", "horario"):
            proximo_ensaio_por_escala.setdefault(ensaio.escala_id, ensaio)

    data_extenso = f"{DIAS_SEMANA_PT[hoje.weekday()]}, {hoje.day} de {MESES_PT[hoje.month].lower()}"

    return render_template(
        "ministerio/detalhe.html",
        ministerio=ministerio,
        pode_gerenciar=pode_gerenciar,
        eh_admin=eh_admin,
        escalas=escalas,
        qtd_ocorrencias_por_turno=qtd_ocorrencias_por_turno,
        proximo_ensaio_por_escala=proximo_ensaio_por_escala,
        turnos_plantao=turnos_plantao,
        data_extenso=data_extenso,
        acao_form=AcaoForm(),
        **dados_calendario,
    )


@bp.route("/<int:ministerio_id>/calendario")
@login_required
def calendario(ministerio_id):
    ministerio, pode_gerenciar = _ministerio_visivel_ou_404(ministerio_id)
    hoje = date.today()
    dados_calendario = _dados_calendario(ministerio, hoje)

    return render_template(
        "ministerio/calendario.html",
        ministerio=ministerio,
        pode_gerenciar=pode_gerenciar,
        **dados_calendario,
    )


@bp.route("/<int:ministerio_id>/local-checkin", methods=["GET", "POST"])
@login_required
def local_checkin(ministerio_id):
    """Local proprio do check-in do ministerio (lider/admin); sem ele, vale o
    da comunidade (ver app/escala/checkin.py)."""
    from app.escala.local_checkin import tela_local_checkin

    ministerio = _ministerio_gerenciavel_ou_404(ministerio_id)
    return tela_local_checkin(
        ministerio, ministerio.nome, url_for("ministerio.detalhe", ministerio_id=ministerio.id), ministerio=ministerio,
    )

@bp.route("/<int:ministerio_id>/estatisticas", methods=["GET", "POST"])
@login_required
def estatisticas(ministerio_id):
    """Estatisticas de comparecimento do ministerio (lider/admin), ver
    app/escala/estatisticas.py."""
    from app.escala.estatisticas import tela_estatisticas

    ministerio = _ministerio_gerenciavel_ou_404(ministerio_id)
    return tela_estatisticas(
        [ministerio], ministerio.nome, url_for("ministerio.detalhe", ministerio_id=ministerio.id),
        lambda **args: url_for("ministerio.estatisticas", ministerio_id=ministerio.id, **args),
        ministerio_config=ministerio,
    )


@bp.route("/<int:ministerio_id>/editar", methods=["GET", "POST"])
@login_required
def editar(ministerio_id):
    ministerio = _ministerio_do_usuario_ou_404(ministerio_id)
    form = MinisterioForm(nome=ministerio.nome, descricao=ministerio.descricao)

    if request.method == "GET":
        # SelectMultipleField nao entende a coluna CSV crua -- mesmo padrao
        # de plantao.routes.editar com dias_semana.
        form.dias_culto.data = ministerio.dias_culto_efetivos

    if form.validate_on_submit():
        ministerio.nome = form.nome.data.strip()
        ministerio.descricao = (form.descricao.data or "").strip() or None
        ministerio.dias_culto = (
            ",".join(str(d) for d in sorted(form.dias_culto.data)) if form.dias_culto.data else None
        )

        if form.imagem.data:
            logo_antiga = ministerio.imagem
            ministerio.imagem = _salvar_logo(form.imagem.data)
            _remover_logo_antiga(logo_antiga)

        ministerio.save()
        flash("Ministerio atualizado!", "success")
        return redirect(url_for("ministerio.detalhe", ministerio_id=ministerio.id))

    return render_template("ministerio/editar.html", form=form, ministerio=ministerio)


def excluir_ministerio_em_cascata(ministerio):
    """Apaga um Ministerio e tudo que pende dele -- usado tanto por
    excluir_ministerio (abaixo) quanto por comunidade.routes.excluir_comunidade
    (que precisa apagar cada Ministerio da comunidade antes de poder apagar a
    propria comunidade). delete_cascade cobre Escala -> Funcao/ItemRepertorio
    e TurnoPlantao -> EquipeTurno -> EquipeMembro. Diferente de
    plantao.excluir_turno (que preserva historico ao apagar so a regra), aqui
    o ministerio inteiro some, entao nao ha nada a preservar."""
    from app.escala.models import Escala
    from app.plantao.models import TurnoPlantao

    _remover_logo_antiga(ministerio.imagem)

    for escala in Escala.objects(ministerio_id=ministerio.id):
        delete_cascade(escala)

    for turno in TurnoPlantao.objects(ministerio_id=ministerio.id):
        delete_cascade(turno)

    delete_cascade(ministerio)


@bp.route("/<int:ministerio_id>/excluir", methods=["POST"])
@login_required
def excluir_ministerio(ministerio_id):
    ministerio = _ministerio_do_usuario_ou_404(ministerio_id)
    form = AcaoForm()

    if not form.validate_on_submit():
        flash("Acao invalida.", "danger")
        return redirect(url_for("ministerio.detalhe", ministerio_id=ministerio.id))

    nome = ministerio.nome
    comunidade_id = ministerio.comunidade_id
    excluir_ministerio_em_cascata(ministerio)

    flash(f'Ministerio "{nome}" excluido.', "success")
    return redirect(url_for("comunidade.detalhe", comunidade_id=comunidade_id))


# --- Papeis e convites -------------------------------------------------------
#
# Admin da comunidade pode conceder "lider" ou "membro" neste ministerio.
# Lider (que nao seja tambem admin) so pode conceder "membro" -- nunca outro
# lider nem admin de comunidade (hierarquia, ver app/convites/CLAUDE.md).

def _papeis_convidaveis_no_ministerio(ministerio, usuario):
    from app.comunidade.routes import _eh_admin_da_comunidade

    if _eh_admin_da_comunidade(ministerio.comunidade, usuario):
        return list(PAPEIS_MINISTERIO)  # ["lider", "membro"]
    if _eh_lider_do_ministerio(ministerio, usuario):
        return ["membro"]
    return []


@bp.route("/<int:ministerio_id>/papeis", methods=["GET", "POST"])
@login_required
def papeis(ministerio_id):
    ministerio = _ministerio_gerenciavel_ou_404(ministerio_id)
    papeis_permitidos = _papeis_convidaveis_no_ministerio(ministerio, current_user)

    form = ConvidarForm()
    form.papel.choices = [(p, p.capitalize()) for p in papeis_permitidos]

    if form.validate_on_submit():
        # Defesa em profundidade: o form ja limita as choices, mas confirma
        # de novo aqui -- alguem poderia montar o POST na mao com um papel
        # fora da hierarquia que tem permissao de conceder.
        if form.papel.data not in papeis_permitidos:
            flash("Voce nao tem permissao para conceder esse papel.", "danger")
            return redirect(url_for("ministerio.papeis", ministerio_id=ministerio.id))

        # Direto ou por convite, conforme a preferencia de privacidade da
        # pessoa -- ver app/convites/adicao.py.
        mensagem, categoria = adicionar_ou_convidar(
            "ministerio", ministerio, form.papel.data, form.email.data, current_user
        )
        flash(mensagem, categoria)
        return redirect(url_for("ministerio.papeis", ministerio_id=ministerio.id))

    papeis_atuais = list(
        UsuarioMinisterio.objects(ministerio_id=ministerio.id).order_by("papel")
    )
    convites_pendentes = list(
        Convite.objects(escopo_tipo="ministerio", escopo_id=ministerio.id, status="pendente")
        .order_by("-criado_em")
    )

    link_convite = (
        url_for("ministerio.entrar_via_link", token=ministerio.token_convite_publico, _external=True)
        if ministerio.token_convite_publico else None
    )

    return render_template(
        "ministerio/papeis.html",
        ministerio=ministerio,
        form=form,
        link_convite=link_convite,
        pode_convidar=bool(papeis_permitidos),
        papeis_atuais=papeis_atuais,
        convites_pendentes=convites_pendentes,
        acao_form=AcaoForm(),
    )


@bp.route("/<int:ministerio_id>/papeis/link/gerar", methods=["POST"])
@login_required
def gerar_link_convite(ministerio_id):
    """Gera (ou regenera, invalidando o anterior) o link de acesso direto do
    ministerio -- ver app/convites/link_publico.py. Lider ou admin da
    comunidade; quem entra por ele e sempre "membro"."""
    ministerio = _ministerio_gerenciavel_ou_404(ministerio_id)
    if not AcaoForm().validate_on_submit():
        flash("Acao invalida.", "danger")
        return redirect(url_for("ministerio.papeis", ministerio_id=ministerio.id))
    ministerio.gerar_novo_link_convite()
    ministerio.save()
    flash("Novo link de acesso gerado! O link anterior (se existia) parou de funcionar.", "success")
    return redirect(url_for("ministerio.papeis", ministerio_id=ministerio.id))


@bp.route("/entrar/<token>", methods=["GET", "POST"])
@limiter.limit("30 per minute")
def entrar_via_link(token):
    """Publica (sem @login_required): quem nao tem conta ve a tela pra entrar
    ou se cadastrar, e a entrada se conclui sozinha depois. Mesmo fluxo de
    comunidade.routes.entrar_via_link."""
    from app.convites.link_publico import entrar_no_ministerio, eh_navegacao_direta, guardar_entrada_pendente

    ministerio = primeiro_ou_404(Ministerio.objects(token_convite_publico=token))
    tela = dict(
        nome_escopo=ministerio.nome, tipo_escopo="ministerio", imagem_escopo=ministerio.imagem,
        comunidade_escopo=ministerio.comunidade.nome if ministerio.comunidade else None,
    )

    if not current_user.is_authenticated:
        guardar_entrada_pendente("ministerio", token, url_for("ministerio.entrar_via_link", token=token))
        return render_template("comunidade/entrar.html", **tela)

    form = AcaoForm()
    if (request.method == "POST" and form.validate_on_submit()) or (
        request.method == "GET" and eh_navegacao_direta(request)
    ) or UsuarioMinisterio.objects(usuario_id=current_user.id, ministerio_id=ministerio.id).first():
        destino, mensagem = entrar_no_ministerio(current_user, ministerio)
        flash(mensagem, "success")
        return redirect(destino)

    return render_template("comunidade/entrar.html", precisa_confirmar=True, acao_form=form, **tela)


@bp.route("/<int:ministerio_id>/papeis/<int:usuario_ministerio_id>/remover", methods=["POST"])
@login_required
def remover_papel(ministerio_id, usuario_ministerio_id):
    ministerio = _ministerio_gerenciavel_ou_404(ministerio_id)
    papel = primeiro_ou_404(UsuarioMinisterio.objects(id=usuario_ministerio_id, ministerio_id=ministerio.id))
    form = AcaoForm()

    if not form.validate_on_submit():
        flash("Acao invalida.", "danger")
        return redirect(url_for("ministerio.papeis", ministerio_id=ministerio.id))

    # Um lider (nao-admin) so pode remover papeis que ele mesmo poderia
    # conceder (membro) -- nao pode expulsar outro lider.
    papeis_permitidos = _papeis_convidaveis_no_ministerio(ministerio, current_user)
    if papel.papel not in papeis_permitidos:
        flash("Voce nao tem permissao para remover esse papel.", "danger")
        return redirect(url_for("ministerio.papeis", ministerio_id=ministerio.id))

    nome = papel.usuario.name or papel.usuario.username or papel.usuario.email
    papel.delete()
    flash(f"{nome} removido(a) do ministerio.", "success")
    return redirect(url_for("ministerio.papeis", ministerio_id=ministerio.id))


@bp.route("/<int:ministerio_id>/papeis/convite/<int:convite_id>/cancelar", methods=["POST"])
@login_required
def cancelar_convite(ministerio_id, convite_id):
    ministerio = _ministerio_gerenciavel_ou_404(ministerio_id)
    convite = primeiro_ou_404(Convite.objects(
        id=convite_id, escopo_tipo="ministerio", escopo_id=ministerio.id, status="pendente"
    ))
    form = AcaoForm()

    if not form.validate_on_submit():
        flash("Acao invalida.", "danger")
        return redirect(url_for("ministerio.papeis", ministerio_id=ministerio.id))

    convite.delete()
    flash("Convite cancelado.", "success")
    return redirect(url_for("ministerio.papeis", ministerio_id=ministerio.id))


@bp.route("/<int:ministerio_id>/checkin", methods=["GET", "POST"])
@login_required
def checkin(ministerio_id):
    ministerio = _ministerio_gerenciavel_ou_404(ministerio_id)
    form_crianca = CriancaForm()

    if form_crianca.validate_on_submit():
        crianca = Crianca(
            ministerio_id=ministerio.id,
            nome=form_crianca.nome.data.strip(),
            data_nascimento=form_crianca.data_nascimento.data,
            responsavel_nome=form_crianca.responsavel_nome.data.strip(),
            responsavel_telefone=(form_crianca.responsavel_telefone.data or "").strip() or None,
            observacoes=(form_crianca.observacoes.data or "").strip() or None,
        )
        crianca.save()
        flash(f"{crianca.nome} cadastrado(a).", "success")
        return redirect(url_for("ministerio.checkin", ministerio_id=ministerio.id))

    criancas = list(Crianca.objects(ministerio_id=ministerio.id).order_by("nome"))
    ids_criancas = [c.id for c in criancas]
    presentes = list(
        CheckInCrianca.objects(crianca_id__in=ids_criancas, hora_saida=None).order_by("-hora_entrada")
    )
    formularios_checkout = {registro.id: CheckoutForm() for registro in presentes}

    return render_template(
        "ministerio/checkin.html",
        ministerio=ministerio,
        criancas=criancas,
        presentes=presentes,
        form_crianca=form_crianca,
        formularios_checkout=formularios_checkout,
        acao_form=AcaoForm(),
    )


@bp.route("/<int:ministerio_id>/checkin/<int:crianca_id>/entrada", methods=["POST"])
@login_required
def fazer_checkin(ministerio_id, crianca_id):
    ministerio = _ministerio_gerenciavel_ou_404(ministerio_id)
    crianca = primeiro_ou_404(Crianca.objects(id=crianca_id, ministerio_id=ministerio.id))
    form = AcaoForm()

    if not form.validate_on_submit():
        flash("Acao invalida.", "danger")
        return redirect(url_for("ministerio.checkin", ministerio_id=ministerio.id))

    ja_presente = CheckInCrianca.objects(crianca_id=crianca.id, hora_saida=None).first()
    if ja_presente:
        flash(f"{crianca.nome} ja esta com check-in em aberto.", "warning")
        return redirect(url_for("ministerio.checkin", ministerio_id=ministerio.id))

    codigo = "".join(random.choices(string.digits, k=4))
    registro = CheckInCrianca(
        crianca_id=crianca.id,
        data=date.today(),
        codigo_seguranca=codigo,
        registrado_por_id=current_user.id,
    )
    registro.save()

    flash(
        f"Check-in de {crianca.nome} feito. Codigo de seguranca: {codigo} -- "
        "anote ou tire uma foto pra entregar ao responsavel.",
        "success",
    )
    return redirect(url_for("ministerio.checkin", ministerio_id=ministerio.id))


@bp.route("/<int:ministerio_id>/checkin/<int:checkin_id>/saida", methods=["POST"])
@login_required
def fazer_checkout(ministerio_id, checkin_id):
    ministerio = _ministerio_gerenciavel_ou_404(ministerio_id)
    registro = primeiro_ou_404(CheckInCrianca.objects(id=checkin_id))
    if registro.crianca is None or registro.crianca.ministerio_id != ministerio.id:
        abort(404)
    form = CheckoutForm()

    if not form.validate_on_submit():
        flash("Informe o codigo de seguranca.", "danger")
        return redirect(url_for("ministerio.checkin", ministerio_id=ministerio.id))

    if registro.hora_saida is not None:
        flash(f"{registro.crianca.nome} ja teve saida registrada.", "danger")
        return redirect(url_for("ministerio.checkin", ministerio_id=ministerio.id))

    if form.codigo_seguranca.data.strip() != registro.codigo_seguranca:
        flash("Codigo de seguranca nao confere.", "danger")
        return redirect(url_for("ministerio.checkin", ministerio_id=ministerio.id))

    registro.hora_saida = datetime.now(timezone.utc)
    registro.retirado_por_id = current_user.id
    registro.save()

    flash(f"Saida de {registro.crianca.nome} confirmada.", "success")
    return redirect(url_for("ministerio.checkin", ministerio_id=ministerio.id))


@bp.route("/<int:ministerio_id>/checkin/criancas/<int:crianca_id>/excluir", methods=["POST"])
@login_required
def excluir_crianca(ministerio_id, crianca_id):
    ministerio = _ministerio_gerenciavel_ou_404(ministerio_id)
    crianca = primeiro_ou_404(Crianca.objects(id=crianca_id, ministerio_id=ministerio.id))
    form = AcaoForm()

    if not form.validate_on_submit():
        flash("Acao invalida.", "danger")
        return redirect(url_for("ministerio.checkin", ministerio_id=ministerio.id))

    nome = crianca.nome
    delete_cascade(crianca)

    flash(f"{nome} removido(a) do cadastro.", "success")
    return redirect(url_for("ministerio.checkin", ministerio_id=ministerio.id))


# --- Bancos de musicas: OFICIAL da comunidade e LOCAL de cada ministerio ------
#
# Ver app/escala/banco_musicas.py pras regras. Resumo de quem pode:
# - VER os dois bancos e as pastas: qualquer pessoa da comunidade (admin,
#   membro, lider/membro de algum ministerio dela, ou do diretorio por e-mail).
# - Banco OFICIAL (/musicas/<comunidade_id>/...): so admin da comunidade
#   cadastra/importa/edita -- e aprova musica de banco local pra virar oficial.
# - Banco LOCAL (/<ministerio_id>/repertorio/...): o lider do ministerio (e o
#   admin, que lidera todos) cadastra/importa/edita a vontade.
# As rotas que valem pros dois bancos tem as duas URLs; `Banco.args` monta a
# certa no url_for.

def _tags_do_texto(texto):
    """"amor, Cruz, amor" -> ["amor", "Cruz"] (sem repetir, ignorando
    maiuscula e acento -- "adoracao" e "adoração" contam como a mesma)."""
    from app.escala.temas import _sem_acento

    tags = []
    for tag in (texto or "").split(","):
        tag = tag.strip()[:40]
        if tag and _sem_acento(tag) not in [_sem_acento(t) for t in tags]:
            tags.append(tag)
    return tags[:12]


def _ministerios_da_comunidade(comunidade_id):
    return list(Ministerio.objects(comunidade_id=comunidade_id).order_by("nome"))


def _pode_ver_banco(comunidade, usuario):
    from app.comunidade.routes import _eh_admin_da_comunidade, _eh_membro_da_comunidade
    from app.escala.models import Membro

    if _eh_admin_da_comunidade(comunidade, usuario) or _eh_membro_da_comunidade(comunidade, usuario):
        return True
    # Lider/membro convidado direto num ministerio (sem papel na comunidade)
    # tambem monta repertorio -- precisa enxergar o banco.
    ids_ministerios = [m.id for m in Ministerio.objects(comunidade_id=comunidade.id).only("id")]
    if UsuarioMinisterio.objects(usuario_id=usuario.id, ministerio_id__in=ids_ministerios).first():
        return True
    return Membro.da_conta(usuario.email, comunidade_id=comunidade.id).first() is not None


def _banco_ou_404(comunidade_id=None, ministerio_id=None):
    """Banco OFICIAL (comunidade_id) ou LOCAL (ministerio_id), ja com a
    permissao de edicao da conta logada. Junta os bancos antigos na 1a vez."""
    from app.comunidade.models import Comunidade
    from app.comunidade.routes import _eh_admin_da_comunidade
    from app.escala.banco_musicas import Banco, unificar_banco_da_comunidade

    ministerio = None
    if ministerio_id is not None:
        ministerio = primeiro_ou_404(Ministerio.objects(id=ministerio_id))
        comunidade_id = ministerio.comunidade_id
    comunidade = primeiro_ou_404(Comunidade.objects(id=comunidade_id))
    if not _pode_ver_banco(comunidade, current_user):
        abort(404)
    unificar_banco_da_comunidade(comunidade.id)
    if ministerio is not None:
        pode_editar = _eh_lider_do_ministerio(ministerio, current_user)
    else:
        pode_editar = _eh_admin_da_comunidade(comunidade, current_user)
    return Banco(comunidade, ministerio, pode_editar)


def _banco_editavel_ou_404(comunidade_id=None, ministerio_id=None):
    banco = _banco_ou_404(comunidade_id, ministerio_id)
    if not banco.pode_editar:
        abort(404)
    return banco


def _musica_visivel_ou_404(musica_id):
    """(musica, banco onde ela mora)."""
    from app.escala.banco_musicas import chave_do_nome, musicas_oficiais

    musica = primeiro_ou_404(Musica.objects(id=musica_id))
    if musica.comunidade_id is not None:
        if musica.oficial is False:
            return musica, _banco_ou_404(ministerio_id=musica.ministerio_id)
        return musica, _banco_ou_404(comunidade_id=musica.comunidade_id)

    # Musica antiga com o banco ainda nao unificado: unifica agora (ela vira
    # oficial). Se era repetida e foi juntada noutra, abre a que ficou.
    ministerio = primeiro_ou_404(Ministerio.objects(id=musica.ministerio_id))
    banco = _banco_ou_404(comunidade_id=ministerio.comunidade_id)
    atual = Musica.objects(id=musica_id).first()
    if atual is None:
        chave = chave_do_nome(musica.nome)
        atual = next((m for m in musicas_oficiais(banco.comunidade.id) if chave_do_nome(m.nome) == chave), None)
    if atual is None:
        abort(404)
    return atual, banco


def _musica_editavel_ou_404(musica_id):
    musica, banco = _musica_visivel_ou_404(musica_id)
    if not banco.pode_editar:
        abort(404)
    return musica, banco


def _url_do_banco(banco):
    return url_for("ministerio.banco_musicas" if banco.oficial else "ministerio.repertorio", **banco.args)


def _ids_ministerios_visiveis(comunidade):
    """Ministerios cujas escalas a conta enxerga (pras pastas automaticas)."""
    from app.comunidade.routes import _eh_admin_da_comunidade, _eh_membro_da_comunidade

    todos = [m.id for m in Ministerio.objects(comunidade_id=comunidade.id).only("id")]
    if _eh_admin_da_comunidade(comunidade, current_user) or _eh_membro_da_comunidade(comunidade, current_user):
        return todos
    return [u.ministerio_id for u in UsuarioMinisterio.objects(usuario_id=current_user.id, ministerio_id__in=todos)]


def _repertorios_das_escalas(comunidade, limite=20):
    """Pastas automaticas do modo "Pastas": o repertorio de cada escala
    recente/proxima (60 dias pra tras em diante) que tenha musica."""
    from app.escala.models import Escala

    ids = _ids_ministerios_visiveis(comunidade)
    if not ids:
        return []
    desde = date.today() - timedelta(days=60)
    escalas = list(Escala.objects(ministerio_id__in=ids, data__gte=desde).order_by("data"))
    if not escalas:
        return []
    itens_por_escala = {}
    for item in ItemRepertorio.objects(escala_id__in=[e.id for e in escalas]).order_by("ordem"):
        itens_por_escala.setdefault(item.escala_id, []).append(item)
    grupos = [{"escala": e, "itens": itens_por_escala[e.id]} for e in escalas if e.id in itens_por_escala]
    return grupos[:limite]


def _palavras_chave_se_faltar(musica):
    """Musica sem palavras-chave ganha as de tema pela letra/cifra (ver
    escala/temas.py) -- nunca troca tag que alguem escreveu. Devolve as
    tags novas (lista vazia se nao mudou nada)."""
    from app.escala.temas import sugerir_tags

    if musica.tags:
        return []
    tags = sugerir_tags(musica.nome, letra=musica.letra_projecao, cifra=musica.cifra_louvor)
    if tags:
        musica.tags = tags
        musica.palavras_chave_verificadas = True
    return tags


def projecao_espelha_cifra(musica):
    """A letra de projecao ainda e so o reflexo da cifra (vazia ou igual ao
    que a cifra gera) -- ninguem a ajustou a mao. Enquanto for, ela segue a
    cifra sozinha (aqui no salvar e ao vivo na tela, ver musica.html)."""
    return _eh_reflexo_da_cifra(musica.letra_projecao, musica.cifra_louvor)


def _eh_reflexo_da_cifra(projecao, cifra):
    """Projecao vazia ou igual ao que a cifra gera -- no formato atual (slides
    de 4 linhas) ou no antigo (sem quebrar slides), que e como estao as
    musicas importadas/geradas antes dessa mudanca."""
    atual = (projecao or "").strip()
    if not atual:
        return True
    cifra = cifra or ""
    formatos = (
        projecao_da_cifra(cifra),  # atual: slides de 4 + rotulos deduzidos
        projecao_da_cifra(cifra, deduzir_rotulos=False),  # versao anterior: sem rotulos deduzidos
        projecao_da_cifra(cifra, linhas_por_slide=10 ** 6, deduzir_rotulos=False),  # a 1a: um bloco so
    )
    return atual in {f.strip() for f in formatos}


def _espelhar_projecao(musica, cifra_antiga):
    """Depois de trocar a cifra original: se a projecao era so o reflexo da
    cifra ANTIGA (ou estava vazia), remonta da nova. Projecao ajustada a mao
    nunca e mexida. Devolve True se remontou."""
    if not _eh_reflexo_da_cifra(musica.letra_projecao, cifra_antiga):
        return False
    nova = projecao_da_cifra(musica.cifra_louvor or "") or None
    if nova == musica.letra_projecao:
        return False
    musica.letra_projecao = nova
    return True


def _texto_tags_novas(tags):
    return f" Palavras-chave: {', '.join(tags)}." if tags else ""


def _repertorios_por_ministerio(comunidade, ministerios):
    """[(nome do grupo, [repertorios])] na ordem dos ministerios; os antigos
    sem ministerio vao pro fim, em "Sem ministerio"."""
    from app.escala.models import PastaMusicas

    por_ministerio = {}
    for pasta in PastaMusicas.objects(comunidade_id=comunidade.id).order_by("nome"):
        por_ministerio.setdefault(pasta.ministerio_id, []).append(pasta)
    grupos = [(m, por_ministerio[m.id]) for m in ministerios if m.id in por_ministerio]
    if None in por_ministerio:
        grupos.append((None, por_ministerio[None]))
    return grupos


def _temas_populares(musicas, limite=10):
    """Palavras-chave mais usadas no banco -- viram atalhos de busca na tela
    (a lista de musicas fica escondida ate a pessoa pesquisar/escolher)."""
    from collections import Counter
    from app.escala.temas import _sem_acento

    contagem, grafia = Counter(), {}
    for musica in musicas:
        for tag in musica.tags or []:
            chave = _sem_acento(tag)
            contagem[chave] += 1
            grafia.setdefault(chave, tag)
    return [grafia[chave] for chave, _ in contagem.most_common(limite)]


def _render_banco(banco):
    from app.escala.banco_musicas import preencher_palavras_chave_da_comunidade, sugestoes_dos_ministerios

    from app.ministerio.compartilhamento import opcoes_de_envio

    # Musica sem palavras-chave ganha as dela sozinha (uma vez por musica).
    preencher_palavras_chave_da_comunidade(banco.comunidade.id)
    lidera = _ministerios_que_lidera(banco.comunidade)
    musicas = list(banco.musicas().only(
        "id", "nome", "artista", "tom", "tags", "letra_projecao", "cifra_louvor"
    ).order_by("nome"))
    ministerios = _ministerios_da_comunidade(banco.comunidade.id)
    nome_ministerio = {m.id: m.nome for m in ministerios}
    sugestoes = []
    if banco.oficial and banco.pode_editar:
        sugestoes = [
            {"musica": m, "ministerio": nome_ministerio.get(m.ministerio_id, "ministerio removido")}
            for m in sugestoes_dos_ministerios(banco.comunidade.id).order_by("nome")
        ]

    if banco.oficial:
        from app.comunidade.routes import _eh_admin_da_comunidade
        admin = _eh_admin_da_comunidade(banco.comunidade, current_user)
        voltar = url_for("comunidade.detalhe" if admin else "comunidade.escalados", comunidade_id=banco.comunidade.id)
    else:
        voltar = url_for("ministerio.detalhe", ministerio_id=banco.ministerio.id)

    return render_template(
        "ministerio/repertorio.html",
        banco=banco,
        comunidade=banco.comunidade,
        pode_gerenciar=banco.pode_editar,
        musicas=musicas,
        sugestoes=sugestoes,
        ministerios=ministerios,
        repertorios=_repertorios_por_ministerio(banco.comunidade, ministerios),
        ministerios_que_lidera=lidera,
        opcoes_envio=opcoes_de_envio(banco.comunidade.id, current_user.id) if lidera else [],
        repertorios_escalas=_repertorios_das_escalas(banco.comunidade),
        voltar_url=voltar,
        temas_populares=_temas_populares(musicas),
        frase_apagar_todas=FRASE_APAGAR_TODAS,
        form=MusicaForm(),
        acao_form=AcaoForm(),
    )


@bp.route("/musicas/<int:comunidade_id>")
@login_required
def banco_musicas(comunidade_id):
    """Banco OFICIAL da comunidade."""
    return _render_banco(_banco_ou_404(comunidade_id=comunidade_id))


@bp.route("/<int:ministerio_id>/repertorio")
@login_required
def repertorio(ministerio_id):
    """Banco LOCAL do ministerio (mesmo endereco de quando cada ministerio
    tinha o seu banco -- links antigos continuam caindo no lugar certo)."""
    return _render_banco(_banco_ou_404(ministerio_id=ministerio_id))


@bp.route("/musicas/<int:comunidade_id>/nova", methods=["POST"])
@bp.route("/<int:ministerio_id>/repertorio/nova", methods=["POST"])
@login_required
def nova_musica(comunidade_id=None, ministerio_id=None):
    banco = _banco_editavel_ou_404(comunidade_id, ministerio_id)
    form = MusicaForm()
    if not form.validate_on_submit():
        erros = [erro for lista in form.errors.values() for erro in lista]
        flash(erros[0] if erros else "Nao foi possivel cadastrar a musica.", "danger")
        return redirect(_url_do_banco(banco))
    musica = banco.nova_musica(
        nome=form.nome.data.strip(),
        artista=(form.artista.data or "").strip() or None,
        tom=(form.tom.data or "").strip() or None,
        tags=_tags_do_texto(form.tags.data),
        link=(form.link.data or "").strip() or None,
    )
    # Sem letra ainda: tenta so pelo titulo; a cifra/letra salva depois completa.
    _palavras_chave_se_faltar(musica)
    musica.palavras_chave_verificadas = False
    musica.save()
    flash(f'"{musica.nome}" cadastrada. Cole a cifra aqui no Louvor; na aba Projecao, '
          '"Gerar da cifra" monta a letra sem acordes.', "success")
    return redirect(url_for("ministerio.musica", musica_id=musica.id) + "#louvor")


# --- Aprovacao: musica do banco local -> banco oficial (so admin) ------------

def _sugestao_do_admin_ou_404(musica_id):
    from app.comunidade.routes import _eh_admin_da_comunidade
    from app.comunidade.models import Comunidade

    musica = primeiro_ou_404(Musica.objects(id=musica_id, oficial=False))
    comunidade = primeiro_ou_404(Comunidade.objects(id=musica.comunidade_id))
    if not _eh_admin_da_comunidade(comunidade, current_user):
        abort(404)
    return musica, comunidade


@bp.route("/musicas/sugestao/<int:musica_id>/aprovar", methods=["POST"])
@login_required
def aprovar_musica(musica_id):
    """Promove a musica do banco local pro OFICIAL da comunidade (ela sai do
    local e passa a valer pra todos os ministerios; ministerio_id fica como
    historico de onde veio). Avisa os lideres do ministerio de origem."""
    from app.escala.banco_musicas import chave_do_nome, musicas_oficiais
    from app.notificacoes import Notificacao

    musica, comunidade = _sugestao_do_admin_ou_404(musica_id)
    voltar = url_for("ministerio.banco_musicas", comunidade_id=comunidade.id) + "#sugestoes"
    if not AcaoForm().validate_on_submit():
        flash("Acao invalida.", "danger")
        return redirect(voltar)

    chave = chave_do_nome(musica.nome)
    ja_tinha = any(chave_do_nome(m.nome) == chave for m in musicas_oficiais(comunidade.id).only("nome"))
    musica.oficial = True
    musica.sugestao_dispensada = False
    musica.atualizada_em = datetime.now(timezone.utc)
    musica.save()

    origem = Ministerio.objects(id=musica.ministerio_id).first()
    if origem is not None:
        for lider in _lideres_do_ministerio(origem):
            if lider.id != current_user.id:
                Notificacao(
                    usuario_id=lider.id, tipo="musica_aprovada",
                    titulo=f'"{musica.nome}" agora e do banco oficial'[:120],
                    mensagem=f'A musica "{musica.nome}" do banco do {origem.nome} foi aprovada '
                             f'para o banco de musicas oficial de {comunidade.nome}.',
                ).save()

    mensagem = f'"{musica.nome}" aprovada: agora faz parte do banco oficial da comunidade.'
    if ja_tinha:
        mensagem += " Ja existia uma musica oficial com esse nome -- se for a mesma, exclua uma das duas."
    flash(mensagem, "success")
    return redirect(voltar)


@bp.route("/musicas/sugestao/<int:musica_id>/dispensar", methods=["POST"])
@login_required
def dispensar_sugestao(musica_id):
    """Tira a musica da lista de sugestoes (ela continua no banco local)."""
    musica, comunidade = _sugestao_do_admin_ou_404(musica_id)
    if AcaoForm().validate_on_submit():
        musica.sugestao_dispensada = True
        musica.save()
        flash(f'"{musica.nome}" saiu das sugestoes (continua no banco do ministerio).', "success")
    return redirect(url_for("ministerio.banco_musicas", comunidade_id=comunidade.id) + "#sugestoes")


# --- Importacao de cifras em lote a partir de PDF/Word (ver importar_cifras.py) ---
#
# Tres passos, pra caber qualquer quantidade sem estourar o timeout do
# servidor nem o limite de 2 MB por requisicao (MAX_CONTENT_LENGTH): a tela
# manda UM arquivo por vez pra `extrair` (so le, nao grava nada), mostra tudo
# pra pessoa revisar/corrigir, e so entao manda o lote revisado pra `salvar`.
# Vale pros dois bancos (oficial: admin; local: lider do ministerio).

_MAX_MUSICAS_POR_LOTE = 200


@bp.route("/musicas/<int:comunidade_id>/importar")
@bp.route("/<int:ministerio_id>/repertorio/importar")
@login_required
def importar_musicas(comunidade_id=None, ministerio_id=None):
    banco = _banco_editavel_ou_404(comunidade_id, ministerio_id)
    return render_template(
        "ministerio/importar_musicas.html", banco=banco, comunidade=banco.comunidade, acao_form=AcaoForm(),
        tons_maiores=TONS_MAIORES, tons_menores=TONS_MENORES,
    )


@bp.route("/musicas/<int:comunidade_id>/importar/extrair", methods=["POST"])
@bp.route("/<int:ministerio_id>/repertorio/importar/extrair", methods=["POST"])
@login_required
@limiter.limit("300 per minute")
def extrair_musica_pdf(comunidade_id=None, ministerio_id=None):
    """Le 1 arquivo (PDF ou .docx) e devolve a musica sugerida em JSON --
    nao grava nada."""
    from app.escala.banco_musicas import musicas_oficiais
    from app.ministerio.importar_cifras import ArquivoInvalidoError, extrair_musica

    banco = _banco_editavel_ou_404(comunidade_id, ministerio_id)
    if not AcaoForm().validate_on_submit():
        return jsonify({"erro": "Sessao expirada -- recarregue a pagina."}), 400
    arquivo = request.files.get("arquivo")
    if arquivo is None or not arquivo.filename:
        return jsonify({"erro": "Envie um arquivo PDF ou Word (.docx)."}), 400
    try:
        musica = extrair_musica(arquivo.read(), arquivo.filename)
    except ArquivoInvalidoError as erro:
        return jsonify({"erro": str(erro)}), 422

    # Aviso de repetida (mesmo nome, sem diferenciar maiuscula) no proprio
    # banco ou -- pra banco local -- no oficial, que o ministerio ja usa.
    # A tela deixa desmarcada, mas a pessoa pode importar mesmo assim.
    nome = musica["nome"]
    no_proprio_banco = banco.musicas().filter(nome__iexact=nome).first()
    musica["ja_existe"] = (
        no_proprio_banco is not None
        or (not banco.oficial and musicas_oficiais(banco.comunidade.id).filter(nome__iexact=nome).first() is not None)
    )
    # So da pra ATUALIZAR musica do proprio banco (lider nao mexe no oficial).
    musica["existente_id"] = no_proprio_banco.id if no_proprio_banco is not None else None
    return jsonify({"musica": musica})


@bp.route("/musicas/<int:comunidade_id>/importar/salvar", methods=["POST"])
@bp.route("/<int:ministerio_id>/repertorio/importar/salvar", methods=["POST"])
@login_required
def salvar_musicas_importadas(comunidade_id=None, ministerio_id=None):
    """Grava o lote ja revisado na tela. A versao de Projecao ja sai gerada
    da cifra (mesmo rascunho do botao "Gerar da cifra"), pra musica ficar
    pronta pras duas folhas sem mais um passo por musica."""
    import json

    banco = _banco_editavel_ou_404(comunidade_id, ministerio_id)
    if not AcaoForm().validate_on_submit():
        return jsonify({"erro": "Sessao expirada -- recarregue a pagina."}), 400
    try:
        itens = json.loads(request.form.get("musicas") or "[]")
    except ValueError:
        return jsonify({"erro": "Dados invalidos."}), 400
    if not isinstance(itens, list) or not itens:
        return jsonify({"erro": "Nenhuma musica selecionada."}), 400
    if len(itens) > _MAX_MUSICAS_POR_LOTE:
        return jsonify({"erro": f"Importe no maximo {_MAX_MUSICAS_POR_LOTE} musicas por vez."}), 400

    novas, atualizadas = [], 0
    for item in itens:
        if not isinstance(item, dict):
            continue
        nome = str(item.get("nome") or "").strip()[:150]
        if not nome:
            continue
        cifra = str(item.get("cifra") or "").replace("\r\n", "\n").strip("\n") or None
        tom = str(item.get("tom") or "").strip()[:10] or None

        # Reimportacao pra corrigir: troca a cifra da musica que ja existe no
        # MESMO banco, sem duplicar. Letra de projecao, tags, link e escalas
        # ficam; so o que estiver vazio e preenchido.
        atualizar_id = str(item.get("atualizar_id") or "")
        if atualizar_id.isdigit():
            existente = banco.musicas().filter(id=int(atualizar_id)).first()
            if existente is not None:
                cifra_antiga = existente.cifra_louvor
                existente.cifra_louvor = cifra or existente.cifra_louvor
                existente.tom = existente.tom or tom
                existente.artista = existente.artista or str(item.get("artista") or "").strip()[:120] or None
                # Projecao que so espelhava a cifra antiga (ou vazia) segue a nova.
                _espelhar_projecao(existente, cifra_antiga)
                if not existente.tags:
                    existente.tags = _tags_do_texto(str(item.get("tags") or ""))
                existente.atualizada_em = datetime.now(timezone.utc)
                existente.save()
                atualizadas += 1
                continue

        novas.append(banco.nova_musica(
            nome=nome,
            artista=str(item.get("artista") or "").strip()[:120] or None,
            tom=tom,
            tags=_tags_do_texto(str(item.get("tags") or "")),
            palavras_chave_verificadas=True,  # revisadas no card da importacao
            cifra_louvor=cifra,
            letra_projecao=projecao_da_cifra(cifra) or None if cifra else None,
        ))
    for musica in novas:
        musica.save()

    # Lote grande chega em partes (ver importar_musicas.html): so a ultima
    # avisa, com o total de todas -- senao viria 1 aviso por parte.
    if request.form.get("parcial") != "1":
        total = request.form.get("total", type=int) or (len(novas) + atualizadas)
        flash(f"{total} musica(s) importada(s) para o {banco.titulo.lower()}.", "success")
    return jsonify({"criadas": len(novas) + atualizadas, "destino": _url_do_banco(banco)})


# --- Tela e edicao de 1 musica ---------------------------------------------------

@bp.route("/repertorio/<int:musica_id>")
@login_required
def musica(musica_id):
    musica, banco = _musica_visivel_ou_404(musica_id)
    if musica.id != musica_id:  # era repetida e foi juntada noutra
        return redirect(url_for("ministerio.musica", musica_id=musica.id))
    # ?tom=D abre a versao salva nesse tom (a original, se nao existir).
    pedido = (request.args.get("tom") or "").strip()
    versao = None if musica.eh_tom_original(pedido) else musica.versao_no_tom(pedido)
    aberta_eh_original = versao is None
    cifra_aberta = musica.cifra_louvor if aberta_eh_original else versao.cifra
    tom_aberto = (musica.tom or "") if aberta_eh_original else versao.tom
    form_info = MusicaForm(
        nome=musica.nome, artista=musica.artista, tom=musica.tom,
        tags=", ".join(musica.tags or []), link=musica.link,
    )
    return render_template(
        "ministerio/musica.html",
        musica=musica,
        banco=banco,
        comunidade=banco.comunidade,
        url_do_banco=_url_do_banco(banco),
        pode_gerenciar=banco.pode_editar,
        form_info=form_info,
        form_projecao=LetraProjecaoForm(letra_projecao=musica.letra_projecao),
        form_louvor=CifraLouvorForm(cifra_louvor=cifra_aberta, tom=tom_aberto),
        tom_aberto=tom_aberto,
        aberta_eh_original=aberta_eh_original,
        projecao_tem_acordes=tem_acordes(musica.letra_projecao),
        projecao_espelha=projecao_espelha_cifra(musica) and aberta_eh_original,
        blocos=blocos_da_letra(musica.letra_projecao),
        acao_form=AcaoForm(),
    )


def _salvar_musica(musica, aba, mensagem):
    musica.atualizada_em = datetime.now(timezone.utc)
    musica.save()
    flash(mensagem, "success")
    return redirect(url_for("ministerio.musica", musica_id=musica.id) + f"#{aba}")


@bp.route("/repertorio/<int:musica_id>/info", methods=["POST"])
@login_required
def salvar_info_musica(musica_id):
    musica, _ = _musica_editavel_ou_404(musica_id)
    form = MusicaForm()
    if not form.validate_on_submit():
        erros = [erro for lista in form.errors.values() for erro in lista]
        flash(erros[0] if erros else "Nao foi possivel salvar.", "danger")
        return redirect(url_for("ministerio.musica", musica_id=musica.id))
    musica.nome = form.nome.data.strip()
    musica.artista = (form.artista.data or "").strip() or None
    musica.tom = (form.tom.data or "").strip() or None
    musica.tags = _tags_do_texto(form.tags.data)
    musica.palavras_chave_verificadas = True  # tags agora sao escolha da pessoa
    musica.link = (form.link.data or "").strip() or None
    return _salvar_musica(musica, "info", "Dados da musica salvos.")


@bp.route("/repertorio/<int:musica_id>/projecao", methods=["POST"])
@login_required
def salvar_projecao_musica(musica_id):
    """So a versao de projecao -- nao toca na cifra (edicao independente)."""
    musica, _ = _musica_editavel_ou_404(musica_id)
    form = LetraProjecaoForm()
    if not form.validate_on_submit():
        flash("Nao foi possivel salvar a letra de projecao.", "danger")
        return redirect(url_for("ministerio.musica", musica_id=musica.id) + "#projecao")
    musica.letra_projecao = form.letra_projecao.data or None
    novas = _palavras_chave_se_faltar(musica)
    return _salvar_musica(musica, "projecao", "Versao de projecao salva." + _texto_tags_novas(novas))


@bp.route("/repertorio/<int:musica_id>/louvor", methods=["POST"])
@login_required
def salvar_louvor_musica(musica_id):
    """So a versao com cifras -- nao toca na letra de projecao."""
    musica, _ = _musica_editavel_ou_404(musica_id)
    form = CifraLouvorForm()
    if not form.validate_on_submit():
        flash("Nao foi possivel salvar a cifra.", "danger")
        return redirect(url_for("ministerio.musica", musica_id=musica.id) + "#louvor")
    tom = (form.tom.data or "").strip()
    if musica.eh_tom_original(tom):
        cifra_antiga = musica.cifra_louvor
        musica.cifra_louvor = form.cifra_louvor.data or None
        tags_novas = _texto_tags_novas(_palavras_chave_se_faltar(musica))
        if _espelhar_projecao(musica, cifra_antiga):
            tags_novas = " Projecao montada a partir da cifra." + tags_novas
        # Musica sem tom cadastrado: identifica pelos acordes (so preenche o
        # vazio -- nunca troca um tom que alguem ja informou).
        if not musica.tom and not tom:
            identificado = detectar_tom(musica.cifra_louvor)
            if identificado:
                musica.tom = identificado
                return _salvar_musica(
                    musica, "louvor",
                    f"Cifra original salva. Tom {identificado} identificado pelos acordes -- "
                    "se nao for esse, corrija em Dados da musica." + tags_novas,
                )
        return _salvar_musica(musica, "louvor", "Cifra original salva." + tags_novas)
    # Outro tom: vira (ou atualiza) uma versao separada -- a original fica intacta.
    versao = musica.versao_no_tom(tom)
    if versao is None:
        versao = VersaoCifra(tom=tom)
        musica.versoes_cifra.append(versao)
    versao.cifra = form.cifra_louvor.data or None
    versao.atualizada_em = datetime.now(timezone.utc)
    musica.atualizada_em = versao.atualizada_em
    musica.save()
    flash(f"Cifra salva no tom {tom}. A original em {musica.tom} continua guardada.", "success")
    return redirect(url_for("ministerio.musica", musica_id=musica.id, tom=tom) + "#louvor")


@bp.route("/repertorio/<int:musica_id>/louvor/excluir-versao", methods=["POST"])
@login_required
def excluir_versao_cifra(musica_id):
    musica, _ = _musica_editavel_ou_404(musica_id)
    tom = (request.form.get("tom") or "").strip()
    if not AcaoForm().validate_on_submit() or musica.eh_tom_original(tom) or not musica.versao_no_tom(tom):
        flash("Versao nao encontrada.", "danger")
        return redirect(url_for("ministerio.musica", musica_id=musica.id) + "#louvor")
    musica.versoes_cifra = [v for v in musica.versoes_cifra if v is not musica.versao_no_tom(tom)]
    return _salvar_musica(musica, "louvor", f"Versao em {tom} removida.")


@bp.route("/repertorio/<int:musica_id>/rascunho-projecao", methods=["POST"])
@login_required
def rascunho_projecao(musica_id):
    """Devolve (sem gravar nada) a letra de projecao gerada a partir de um
    texto com cifra -- o enviado no campo "texto" ou, sem ele, a cifra
    original. A tela poe no editor da projecao e a pessoa ajusta/salva."""
    musica, _ = _musica_editavel_ou_404(musica_id)
    if not AcaoForm().validate_on_submit():
        abort(400)
    texto = request.form.get("texto")
    if texto is None:
        texto = musica.cifra_louvor or ""
    return jsonify({"texto": projecao_da_cifra(texto)})


@bp.route("/repertorio/<int:musica_id>/excluir", methods=["POST"])
@login_required
def excluir_musica(musica_id):
    musica, banco = _musica_editavel_ou_404(musica_id)
    if not AcaoForm().validate_on_submit():
        flash("Acao invalida.", "danger")
        return redirect(url_for("ministerio.musica", musica_id=musica.id))
    nome = musica.nome
    # As escalas que usavam a musica ficam com o item "avulso" (nome/tom).
    ItemRepertorio.objects(musica_id=musica.id).update(set__musica_id=None)
    musica.delete()
    flash(f'"{nome}" removida do {banco.titulo.lower()}.', "success")
    return redirect(_url_do_banco(banco))


FRASE_APAGAR_TODAS = "APAGAR TODAS"


def _soltar_musicas_apagadas(ids, comunidade_id):
    """Escalas e repertorios que usavam musicas apagadas nao quebram: o item
    vira avulso (fica com nome/tom/momento, so perde o vinculo com o banco)."""
    from app.escala.models import PastaMusicas

    ItemRepertorio.objects(musica_id__in=ids).update(set__musica_id=None)
    for pasta in PastaMusicas.objects(comunidade_id=comunidade_id, itens__musica_id__in=ids):
        for item in pasta.itens:
            if item.musica_id in ids:
                item.musica_id = None
        pasta.save()


@bp.route("/musicas/<int:comunidade_id>/apagar-todas", methods=["POST"])
@bp.route("/<int:ministerio_id>/repertorio/apagar-todas", methods=["POST"])
@login_required
def apagar_todas_musicas(comunidade_id=None, ministerio_id=None):
    """Apaga TODAS as musicas de um banco (oficial ou local). Duas
    confirmacoes: a tela pede um confirm() do navegador E a frase
    FRASE_APAGAR_TODAS digitada -- conferida de novo aqui, porque o confirm
    do navegador nao protege contra POST montado a mao."""
    banco = _banco_editavel_ou_404(comunidade_id, ministerio_id)
    frase = " ".join((request.form.get("confirmacao") or "").split()).upper()
    if not AcaoForm().validate_on_submit() or frase != FRASE_APAGAR_TODAS:
        flash(f'Nada foi apagado: pra confirmar, digite exatamente "{FRASE_APAGAR_TODAS}".', "danger")
        return redirect(_url_do_banco(banco))

    ids = [m.id for m in banco.musicas().only("id")]
    if ids:
        _soltar_musicas_apagadas(ids, banco.comunidade.id)
        Musica.objects(id__in=ids).delete()
    flash(f"{len(ids)} musica(s) apagada(s) do {banco.titulo.lower()}. "
          "Escalas e repertorios que usavam alguma ficaram com ela como musica avulsa.", "success")
    return redirect(_url_do_banco(banco))


# --- Baixar musicas (Word) -----------------------------------------------------
# Quem ve o banco (ou o repertorio) baixa: 1 musica = .docx; varias = .zip
# com um .docx por musica (ver ministerio/exportar_cifras.py). So leitura, por
# isso GET.

_TIPO_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _arquivo_pra_baixar(dados, nome, tipo):
    import io
    from flask import send_file

    resposta = send_file(io.BytesIO(dados), mimetype=tipo, as_attachment=True, download_name=nome)
    resposta.headers["Cache-Control"] = "private, no-store"
    return resposta


@bp.route("/repertorio/<int:musica_id>/baixar")
@login_required
def baixar_musica(musica_id):
    """?tom=D baixa a versao salva nesse tom (como a tela da musica)."""
    from app.ministerio.exportar_cifras import docx_da_musica, nome_de_arquivo

    musica, _ = _musica_visivel_ou_404(musica_id)
    pedido = (request.args.get("tom") or "").strip()
    versao = None if musica.eh_tom_original(pedido) else musica.versao_no_tom(pedido)
    dados = docx_da_musica(musica, versao.cifra if versao else None, versao.tom if versao else None)
    return _arquivo_pra_baixar(dados, nome_de_arquivo(musica.nome, "docx"), _TIPO_DOCX)


@bp.route("/musicas/<int:comunidade_id>/baixar")
@bp.route("/<int:ministerio_id>/repertorio/baixar")
@login_required
def baixar_musicas(comunidade_id=None, ministerio_id=None):
    """Banco inteiro, ou so as marcadas (?ids=1,2,3), num .zip."""
    from app.ministerio.exportar_cifras import nome_de_arquivo, zip_de_musicas

    banco = _banco_ou_404(comunidade_id, ministerio_id)
    musicas = banco.musicas()
    ids = [int(i) for i in (request.args.get("ids") or "").split(",") if i.strip().isdigit()]
    if ids:
        musicas = musicas.filter(id__in=ids)
    musicas = list(musicas.order_by("nome"))
    if not musicas:
        flash("Nenhuma música para baixar.", "warning")
        return redirect(_url_do_banco(banco))
    nome = f"{banco.titulo} - {banco.comunidade.nome}" if banco.oficial else banco.titulo
    dados = zip_de_musicas((m, None, None) for m in musicas)
    return _arquivo_pra_baixar(dados, nome_de_arquivo(nome, "zip"), "application/zip")


@bp.route("/pastas/<int:pasta_id>/baixar")
@login_required
def baixar_pasta(pasta_id):
    """Musicas do repertorio num .zip, na ordem (01 - ..., 02 - ...) e no tom
    guardado em cada item (mesma cifra da folha de cifras)."""
    from app.escala.models import itens_para_folha
    from app.ministerio.exportar_cifras import nome_de_arquivo, zip_de_musicas

    pasta, _, _ = _pasta_ou_404(pasta_id)
    musicas = _musicas_por_id([i.musica_id for i in pasta.itens])
    itens = itens_para_folha((i.nome, i.momento, musicas.get(i.musica_id), i.tom) for i in pasta.itens)
    entradas = [(i["musica"], i["cifra"], i["tom"]) for i in itens if i["musica"]]
    if not entradas:
        flash("Este repertório não tem músicas do banco para baixar.", "warning")
        return redirect(url_for("ministerio.pasta", pasta_id=pasta.id))
    dados = zip_de_musicas(entradas, numerar=True)
    return _arquivo_pra_baixar(dados, nome_de_arquivo(pasta.nome, "zip"), "application/zip")


# --- Repertorios (aba "Repertorios" do banco) e envio pra outras pessoas -----
#
# Um repertorio (PastaMusicas, escala/models.py -- o nome da classe ficou do
# 1o desenho, "pasta") e uma lista com nome de musicas de um MINISTERIO (ex:
# "Repertorio da manha" e "da noite" do Louvor) -- montado marcando musicas
# no banco ou copiado do repertorio de uma escala. As rotas continuam em
# /pastas/... (so URL interna). Quem pode:
# - VER (e baixar as folhas): qualquer pessoa da comunidade, ou quem recebeu
#   o repertorio (de qualquer comunidade/ministerio).
# - CRIAR / EDITAR / ENVIAR: lider do ministerio dono, admin, ou quem criou.
# Quem recebe ve na tela inicial (main.dashboard) ate abrir.

def _ministerios_que_lidera(comunidade):
    """Ministerios da comunidade em que a conta pode criar repertorio
    (admin da comunidade lidera todos)."""
    return [m for m in _ministerios_da_comunidade(comunidade.id) if _eh_lider_do_ministerio(m, current_user)]

def _pasta_ou_404(pasta_id):
    """(pasta, pode_editar, pode_compartilhar)."""
    from app.comunidade.routes import _eh_admin_da_comunidade
    from app.escala.models import PastaMusicas

    pasta = primeiro_ou_404(PastaMusicas.objects(id=pasta_id))
    comunidade = pasta.comunidade
    if comunidade is None:
        abort(404)
    da_comunidade = _pode_ver_banco(comunidade, current_user)
    if not da_comunidade and pasta.compartilhamento_de(current_user.id) is None:
        abort(404)
    ministerio = pasta.ministerio
    pode_editar = da_comunidade and (
        pasta.criada_por_id == current_user.id
        or _eh_admin_da_comunidade(comunidade, current_user)
        or (ministerio is not None and _eh_lider_do_ministerio(ministerio, current_user))
    )
    return pasta, pode_editar, pode_editar


def _pasta_editavel_ou_404(pasta_id):
    pasta, pode_editar, _ = _pasta_ou_404(pasta_id)
    if not pode_editar:
        abort(404)
    return pasta


def _voltar_pra_pasta(pasta, ancora=""):
    return redirect(url_for("ministerio.pasta", pasta_id=pasta.id) + ancora)


def _musicas_por_id(ids):
    ids = [i for i in ids if i]
    return {m.id: m for m in Musica.objects(id__in=ids)} if ids else {}


@bp.route("/musicas/<int:comunidade_id>/pastas/nova", methods=["POST"])
@login_required
def nova_pasta(comunidade_id):
    """Cria o repertorio (de um ministerio que a conta lidera) com as musicas
    marcadas no modo Lista do banco."""
    from app.escala.models import ItemPasta, PastaMusicas

    banco = _banco_ou_404(comunidade_id=comunidade_id)
    voltar = request.form.get("voltar") or ""
    if not voltar.startswith("/") or voltar.startswith("//"):
        voltar = _url_do_banco(banco)
    if not AcaoForm().validate_on_submit():
        flash("Acao invalida.", "danger")
        return redirect(voltar)
    nome = (request.form.get("nome") or "").strip()[:120]
    ids = [int(i) for i in request.form.getlist("musica_id") if i.isdigit()]
    musicas = list(Musica.objects(id__in=ids, comunidade_id=banco.comunidade.id)) if ids else []
    lidera = {m.id: m for m in _ministerios_que_lidera(banco.comunidade)}
    ministerio = lidera.get(request.form.get("ministerio_id", type=int))
    if ministerio is None:
        flash("Escolha um ministerio que voce lidera pra guardar o repertorio.", "danger")
        return redirect(voltar)
    if not nome or not musicas:
        flash("De um nome pro repertorio e marque pelo menos uma musica.", "danger")
        return redirect(voltar)
    ordem = {musica_id: posicao for posicao, musica_id in enumerate(ids)}
    musicas.sort(key=lambda m: ordem[m.id])
    pasta = PastaMusicas(
        comunidade_id=banco.comunidade.id, ministerio_id=ministerio.id, nome=nome, criada_por_id=current_user.id,
        itens=[ItemPasta(musica_id=m.id, nome=m.nome, tom=m.tom) for m in musicas],
    )
    pasta.save()
    flash(f'Repertorio "{pasta.nome}" criado no {ministerio.nome} com {len(musicas)} musica(s).', "success")
    return _voltar_pra_pasta(pasta)


@bp.route("/pastas/<int:pasta_id>")
@login_required
def pasta(pasta_id):
    from app.auth.models import User
    from app.escala.banco_musicas import musicas_oficiais

    pasta, pode_editar, pode_compartilhar = _pasta_ou_404(pasta_id)

    # Quem recebeu: abrir a pasta tira ela de "novo" na tela inicial.
    meu = pasta.compartilhamento_de(current_user.id)
    if meu is not None and meu.visto_em is None:
        meu.visto_em = datetime.now(timezone.utc)
        pasta.save()

    musicas = _musicas_por_id([i.musica_id for i in pasta.itens])
    da_comunidade = _pode_ver_banco(pasta.comunidade, current_user)
    itens = [{"indice": n, "item": i, "musica": musicas.get(i.musica_id)} for n, i in enumerate(pasta.itens)]

    disponiveis = {}
    if pode_editar:
        nomes = {m.id: m.nome for m in Ministerio.objects(comunidade_id=pasta.comunidade_id)}
        disponiveis["Banco da comunidade"] = list(
            musicas_oficiais(pasta.comunidade_id).only("id", "nome").order_by("nome")
        )
        locais = Musica.objects(comunidade_id=pasta.comunidade_id, oficial=False).only("id", "nome", "ministerio_id")
        for musica in locais.order_by("nome"):
            grupo = "Banco do " + nomes.get(musica.ministerio_id, "ministerio")
            disponiveis.setdefault(grupo, []).append(musica)

    ids_pessoas = [c.usuario_id for c in pasta.compartilhada_com] + [pasta.criada_por_id]
    pessoas = {u.id: u for u in User.objects(id__in=ids_pessoas)}
    from app.ministerio.compartilhamento import opcoes_de_envio

    lidera = _ministerios_que_lidera(pasta.comunidade) if pode_editar else []
    return render_template(
        "ministerio/pasta.html",
        pasta=pasta,
        opcoes_envio=opcoes_de_envio(pasta.comunidade_id, current_user.id) if pode_compartilhar else [],
        ministerios_que_lidera=lidera,
        itens=itens,
        da_comunidade=da_comunidade,
        pode_editar=pode_editar,
        pode_compartilhar=pode_compartilhar,
        disponiveis=disponiveis,
        pessoas=pessoas,
        tons_maiores=TONS_MAIORES,
        tons_menores=TONS_MENORES,
        acao_form=AcaoForm(),
    )


@bp.route("/pastas/<int:pasta_id>/adicionar", methods=["POST"])
@login_required
def adicionar_na_pasta(pasta_id):
    from app.escala.models import ItemPasta

    pasta = _pasta_editavel_ou_404(pasta_id)
    musica = Musica.objects(id=request.form.get("musica_id", type=int), comunidade_id=pasta.comunidade_id).first()
    if not AcaoForm().validate_on_submit() or musica is None:
        flash("Escolha uma musica do banco.", "danger")
        return _voltar_pra_pasta(pasta)
    tom = (request.form.get("tom") or "").strip()[:10] or musica.tom
    pasta.itens.append(ItemPasta(musica_id=musica.id, nome=musica.nome, tom=tom))
    pasta.save()
    flash(f'"{musica.nome}" adicionada ao repertorio.', "success")
    return _voltar_pra_pasta(pasta)


@bp.route("/pastas/<int:pasta_id>/remover/<int:indice>", methods=["POST"])
@login_required
def remover_da_pasta(pasta_id, indice):
    pasta = _pasta_editavel_ou_404(pasta_id)
    if AcaoForm().validate_on_submit() and 0 <= indice < len(pasta.itens):
        nome = pasta.itens[indice].nome
        del pasta.itens[indice]
        pasta.save()
        flash(f'"{nome}" saiu do repertorio.', "success")
    return _voltar_pra_pasta(pasta)


@bp.route("/pastas/<int:pasta_id>/renomear", methods=["POST"])
@login_required
def renomear_pasta(pasta_id):
    pasta = _pasta_editavel_ou_404(pasta_id)
    nome = (request.form.get("nome") or "").strip()[:120]
    if AcaoForm().validate_on_submit() and nome:
        pasta.nome = nome
        # Trocar de ministerio: so pra um que a conta tambem lidera.
        novo = {m.id: m for m in _ministerios_que_lidera(pasta.comunidade)}.get(request.form.get("ministerio_id", type=int))
        if novo is not None:
            pasta.ministerio_id = novo.id
        pasta.save()
        flash("Repertorio atualizado.", "success")
    return _voltar_pra_pasta(pasta)


@bp.route("/pastas/<int:pasta_id>/excluir", methods=["POST"])
@login_required
def excluir_pasta(pasta_id):
    pasta = _pasta_editavel_ou_404(pasta_id)
    if not AcaoForm().validate_on_submit():
        flash("Acao invalida.", "danger")
        return _voltar_pra_pasta(pasta)
    comunidade_id, nome = pasta.comunidade_id, pasta.nome
    pasta.delete()
    flash(f'Repertorio "{nome}" excluido. As musicas continuam no banco.', "success")
    return redirect(url_for("ministerio.banco_musicas", comunidade_id=comunidade_id) + "#repertorios")


def enviar_repertorio(pasta, alvos):
    """Manda o repertorio pros alvos [(ministerio, funcao)] -- cada um e um
    ministerio inteiro (funcao vazia) ou quem serve numa funcao dele (ver
    ministerio/compartilhamento.py). Cada conta, uma vez so, ganha leitura +
    o repertorio na tela inicial + aviso no sino. Devolve quantas pessoas
    receberam. Reenviar pra quem ja tinha volta a marcar como novo."""
    from app.escala.models import CompartilhamentoPasta
    from app.ministerio.compartilhamento import descricao_de_varios, destinatarios_de_varios
    from app.notificacoes import Notificacao

    pessoas = destinatarios_de_varios(alvos, current_user.id)
    descricao = descricao_de_varios(alvos)
    agora = datetime.now(timezone.utc)
    for pessoa in pessoas:
        existente = pasta.compartilhamento_de(pessoa.id)
        if existente is not None:
            existente.enviado_por_id, existente.enviado_em, existente.visto_em = current_user.id, agora, None
        else:
            pasta.compartilhada_com.append(CompartilhamentoPasta(usuario_id=pessoa.id, enviado_por_id=current_user.id))
    if pessoas:
        pasta.envios.append(f"{descricao}: {len(pessoas)} pessoa(s), {agora.strftime('%d/%m/%Y')}"[:200])
    pasta.save()

    remetente = current_user.name or current_user.username or current_user.email
    for pessoa in pessoas:
        Notificacao(
            usuario_id=pessoa.id, tipo="repertorio_compartilhado",
            titulo=f'{remetente} enviou o repertorio "{pasta.nome}"'[:120],
            mensagem=f'Repertorio "{pasta.nome}" ({len(pasta.itens)} musica(s)) pra {descricao}. '
                     "Abra pela tela inicial pra ver e baixar as cifras.",
        ).save()
    return len(pessoas)


def _alvos_do_form(comunidade_id):
    """Alvos marcados no formulario de envio (campos "alvo" = "ministerio_id|funcao")."""
    from app.ministerio.compartilhamento import ler_alvos
    return ler_alvos(request.form.getlist("alvo"), comunidade_id)


def _mensagem_de_envio(pasta, alvos, quantos):
    from app.ministerio.compartilhamento import descricao_de_varios

    if not quantos:
        return (f"Ninguem com conta em {descricao_de_varios(alvos)} pra receber -- nada foi enviado.", "danger")
    return (f'Repertorio "{pasta.nome}" enviado pra {quantos} pessoa(s) -- {descricao_de_varios(alvos)}. '
            "Aparece na tela inicial de cada uma.", "success")


@bp.route("/pastas/<int:pasta_id>/compartilhar", methods=["POST"])
@login_required
def compartilhar_pasta(pasta_id):
    pasta, _, pode_compartilhar = _pasta_ou_404(pasta_id)
    if not pode_compartilhar:
        abort(404)
    alvos = _alvos_do_form(pasta.comunidade_id)
    voltar = request.form.get("voltar") or ""
    destino = redirect(voltar) if voltar.startswith("/") and not voltar.startswith("//") else _voltar_pra_pasta(pasta, "#compartilhar")
    if not AcaoForm().validate_on_submit() or not alvos:
        flash("Marque pelo menos um ministerio ou funcao pra receber.", "danger")
        return destino
    flash(*_mensagem_de_envio(pasta, alvos, enviar_repertorio(pasta, alvos)))
    return destino


@bp.route("/pastas/<int:pasta_id>/<any(projecao, cifras):tipo>")
@login_required
def folha_pasta(pasta_id, tipo):
    """Mesma folha de imprimir/salvar em PDF do repertorio da escala
    (templates/escala/folha_repertorio.html), com o tom guardado na pasta."""
    from app.escala.models import itens_para_folha

    pasta, _, _ = _pasta_ou_404(pasta_id)
    musicas = _musicas_por_id([i.musica_id for i in pasta.itens])
    itens = itens_para_folha((i.nome, i.momento, musicas.get(i.musica_id), i.tom) for i in pasta.itens)
    comunidade = pasta.comunidade
    return render_template(
        "escala/folha_repertorio.html",
        tipo=tipo,
        itens=itens,
        nome_documento=pasta.nome,
        titulo=pasta.nome,
        subtitulo=comunidade.nome if comunidade else "",
        voltar_url=url_for("ministerio.pasta", pasta_id=pasta.id),
        observacoes=None,
        vazio="Nenhuma musica nesta pasta.",
    )
