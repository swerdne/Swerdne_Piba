"""Controller (C do MVC): rotas do modulo ministerio."""
import calendar
import random
import string
from datetime import date, datetime, timedelta, timezone

from flask import render_template, redirect, url_for, flash, request, abort
from flask_login import login_required, current_user

from app.imagens import salvar_imagem, remover_imagem
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
from app.escala.models import resumos_para_calendario_em_lote, Musica, ItemRepertorio, blocos_da_letra
from app.escala.forms import MusicaForm, LetraProjecaoForm, CifraLouvorForm
from app.convites.forms import ConvidarForm
from app.convites.models import Convite, criar_ou_reenviar_convite
from app.convites.routes import _enviar_email_de_convite

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

        convite = criar_ou_reenviar_convite(
            escopo_tipo="ministerio", escopo_id=ministerio.id,
            papel=form.papel.data, email=form.email.data,
            convidado_por_id=current_user.id,
        )
        _enviar_email_de_convite(convite)
        flash(f"Convite enviado para {convite.email}.", "success")
        return redirect(url_for("ministerio.papeis", ministerio_id=ministerio.id))

    papeis_atuais = list(
        UsuarioMinisterio.objects(ministerio_id=ministerio.id).order_by("papel")
    )
    convites_pendentes = list(
        Convite.objects(escopo_tipo="ministerio", escopo_id=ministerio.id, status="pendente")
        .order_by("-criado_em")
    )

    return render_template(
        "ministerio/papeis.html",
        ministerio=ministerio,
        form=form,
        pode_convidar=bool(papeis_permitidos),
        papeis_atuais=papeis_atuais,
        convites_pendentes=convites_pendentes,
        acao_form=AcaoForm(),
    )


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


# --- Repertorio: banco de musicas do ministerio (ver escala.models.Musica) ---

def _tags_do_texto(texto):
    tags = []
    for tag in (texto or "").split(","):
        tag = tag.strip()[:40]
        if tag and tag.lower() not in [t.lower() for t in tags]:
            tags.append(tag)
    return tags[:12]


def _musica_visivel_ou_404(musica_id):
    musica = primeiro_ou_404(Musica.objects(id=musica_id))
    ministerio, pode_gerenciar = _ministerio_visivel_ou_404(musica.ministerio_id)
    return musica, ministerio, pode_gerenciar


def _musica_do_lider_ou_404(musica_id):
    musica, ministerio, pode_gerenciar = _musica_visivel_ou_404(musica_id)
    if not pode_gerenciar:
        abort(404)
    return musica, ministerio


@bp.route("/<int:ministerio_id>/repertorio")
@login_required
def repertorio(ministerio_id):
    ministerio, pode_gerenciar = _ministerio_visivel_ou_404(ministerio_id)
    musicas = list(
        Musica.objects(ministerio_id=ministerio.id)
        .only("id", "nome", "artista", "tom", "tags", "letra_projecao", "cifra_louvor")
        .order_by("nome")
    )
    return render_template(
        "ministerio/repertorio.html",
        ministerio=ministerio,
        pode_gerenciar=pode_gerenciar,
        musicas=musicas,
        form=MusicaForm(),
    )


@bp.route("/<int:ministerio_id>/repertorio/nova", methods=["POST"])
@login_required
def nova_musica(ministerio_id):
    ministerio, pode_gerenciar = _ministerio_visivel_ou_404(ministerio_id)
    if not pode_gerenciar:
        abort(404)
    form = MusicaForm()
    if not form.validate_on_submit():
        erros = [erro for lista in form.errors.values() for erro in lista]
        flash(erros[0] if erros else "Nao foi possivel cadastrar a musica.", "danger")
        return redirect(url_for("ministerio.repertorio", ministerio_id=ministerio.id))
    musica = Musica(
        ministerio_id=ministerio.id,
        nome=form.nome.data.strip(),
        artista=(form.artista.data or "").strip() or None,
        tom=(form.tom.data or "").strip() or None,
        tags=_tags_do_texto(form.tags.data),
        link=(form.link.data or "").strip() or None,
    )
    musica.save()
    flash(f'"{musica.nome}" cadastrada. Agora preencha as versoes de projecao e louvor.', "success")
    return redirect(url_for("ministerio.musica", musica_id=musica.id))


@bp.route("/repertorio/<int:musica_id>")
@login_required
def musica(musica_id):
    musica, ministerio, pode_gerenciar = _musica_visivel_ou_404(musica_id)
    form_info = MusicaForm(
        nome=musica.nome, artista=musica.artista, tom=musica.tom,
        tags=", ".join(musica.tags or []), link=musica.link,
    )
    return render_template(
        "ministerio/musica.html",
        musica=musica,
        ministerio=ministerio,
        pode_gerenciar=pode_gerenciar,
        form_info=form_info,
        form_projecao=LetraProjecaoForm(letra_projecao=musica.letra_projecao),
        form_louvor=CifraLouvorForm(cifra_louvor=musica.cifra_louvor),
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
    musica, _ = _musica_do_lider_ou_404(musica_id)
    form = MusicaForm()
    if not form.validate_on_submit():
        erros = [erro for lista in form.errors.values() for erro in lista]
        flash(erros[0] if erros else "Nao foi possivel salvar.", "danger")
        return redirect(url_for("ministerio.musica", musica_id=musica.id))
    musica.nome = form.nome.data.strip()
    musica.artista = (form.artista.data or "").strip() or None
    musica.tom = (form.tom.data or "").strip() or None
    musica.tags = _tags_do_texto(form.tags.data)
    musica.link = (form.link.data or "").strip() or None
    return _salvar_musica(musica, "info", "Dados da musica salvos.")


@bp.route("/repertorio/<int:musica_id>/projecao", methods=["POST"])
@login_required
def salvar_projecao_musica(musica_id):
    """So a versao de projecao -- nao toca na cifra (edicao independente)."""
    musica, _ = _musica_do_lider_ou_404(musica_id)
    form = LetraProjecaoForm()
    if not form.validate_on_submit():
        flash("Nao foi possivel salvar a letra de projecao.", "danger")
        return redirect(url_for("ministerio.musica", musica_id=musica.id) + "#projecao")
    musica.letra_projecao = form.letra_projecao.data or None
    return _salvar_musica(musica, "projecao", "Versao de projecao salva.")


@bp.route("/repertorio/<int:musica_id>/louvor", methods=["POST"])
@login_required
def salvar_louvor_musica(musica_id):
    """So a versao com cifras -- nao toca na letra de projecao."""
    musica, _ = _musica_do_lider_ou_404(musica_id)
    form = CifraLouvorForm()
    if not form.validate_on_submit():
        flash("Nao foi possivel salvar a cifra.", "danger")
        return redirect(url_for("ministerio.musica", musica_id=musica.id) + "#louvor")
    musica.cifra_louvor = form.cifra_louvor.data or None
    return _salvar_musica(musica, "louvor", "Versao do louvor (cifra) salva.")


@bp.route("/repertorio/<int:musica_id>/excluir", methods=["POST"])
@login_required
def excluir_musica(musica_id):
    musica, ministerio = _musica_do_lider_ou_404(musica_id)
    if not AcaoForm().validate_on_submit():
        flash("Acao invalida.", "danger")
        return redirect(url_for("ministerio.musica", musica_id=musica.id))
    nome = musica.nome
    # As escalas que usavam a musica ficam com o item "avulso" (nome/tom).
    ItemRepertorio.objects(musica_id=musica.id).update(set__musica_id=None)
    musica.delete()
    flash(f'"{nome}" removida do repertorio.', "success")
    return redirect(url_for("ministerio.repertorio", ministerio_id=ministerio.id))
