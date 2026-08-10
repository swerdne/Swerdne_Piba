"""Controller (C do MVC): rotas do modulo ministerio."""
import calendar
import os
import uuid
from datetime import date, timedelta

from flask import render_template, redirect, url_for, flash, request, current_app, abort
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from app.extensions import db
from app.ministerio import bp
from app.ministerio.forms import MinisterioForm, AcaoForm
from app.ministerio.models import Ministerio, criar_ministerio

MESES_PT = [
    "", "Janeiro", "Fevereiro", "Marco", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
]

DIAS_SEMANA_PT = [
    "segunda-feira", "terca-feira", "quarta-feira", "quinta-feira",
    "sexta-feira", "sabado", "domingo",
]


def _ministerio_do_usuario_ou_404(ministerio_id):
    """Busca o ministerio garantindo que pertence ao dono da comunidade dele."""
    ministerio = Ministerio.query.get_or_404(ministerio_id)
    if ministerio.comunidade.usuario_id != current_user.id:
        abort(404)
    return ministerio


def _salvar_logo(arquivo):
    extensao = arquivo.filename.rsplit(".", 1)[1].lower()
    nome_arquivo = secure_filename(f"ministerio_{uuid.uuid4().hex}.{extensao}")

    upload_folder = current_app.config["MINISTERIO_UPLOAD_FOLDER"]
    os.makedirs(upload_folder, exist_ok=True)
    arquivo.save(os.path.join(upload_folder, nome_arquivo))

    return f"/static/uploads/ministerios/{nome_arquivo}"


def _remover_logo_antiga(caminho):
    if caminho and caminho.startswith("/static/uploads/ministerios/"):
        caminho_absoluto = os.path.join("app", caminho.lstrip("/"))
        if os.path.isfile(caminho_absoluto):
            try:
                os.remove(caminho_absoluto)
            except OSError:
                pass


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
    # visualmente consistentes.
    escalas_do_mes = [e for e in ministerio.escalas if e.data and e.data.year == ano and e.data.month == mes]
    escalas_por_dia = {}
    for escala in escalas_do_mes:
        escalas_por_dia.setdefault(escala.data, []).append((escala, escala.cor))

    (ano_anterior, mes_anterior), (ano_proximo, mes_proximo) = _navegacao_calendario(ano, mes)

    return {
        "semanas": semanas,
        "mes": mes,
        "ano": ano,
        "nome_mes": MESES_PT[mes],
        "mes_ano_texto": f"{MESES_PT[mes].lower()} de {ano}",
        "escalas_por_dia": escalas_por_dia,
        "legenda": [(e, e.cor) for e in escalas_do_mes],
        "ano_anterior": ano_anterior,
        "mes_anterior": mes_anterior,
        "ano_proximo": ano_proximo,
        "mes_proximo": mes_proximo,
        "hoje": hoje,
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
    escalas_manuais = [e for e in ministerio.escalas if e.plantao_turno_id is None]

    ocorrencias_por_turno = {}
    for escala in ministerio.escalas:
        if escala.plantao_turno_id is not None:
            turno = escala.plantao_turno
            if turno is not None and turno.escala_origem is not None:
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
    ministerio = _ministerio_do_usuario_ou_404(ministerio_id)

    hoje = date.today()
    escalas, qtd_ocorrencias_por_turno = _escalas_agrupadas_por_turno(ministerio, hoje)
    turnos_plantao = sorted(ministerio.turnos_plantao, key=lambda t: t.nome)

    dados_calendario = _dados_calendario(ministerio, hoje)
    data_extenso = f"{DIAS_SEMANA_PT[hoje.weekday()]}, {hoje.day} de {MESES_PT[hoje.month].lower()}"

    return render_template(
        "ministerio/detalhe.html",
        ministerio=ministerio,
        escalas=escalas,
        qtd_ocorrencias_por_turno=qtd_ocorrencias_por_turno,
        turnos_plantao=turnos_plantao,
        data_extenso=data_extenso,
        acao_form=AcaoForm(),
        **dados_calendario,
    )


@bp.route("/<int:ministerio_id>/calendario")
@login_required
def calendario(ministerio_id):
    ministerio = _ministerio_do_usuario_ou_404(ministerio_id)
    hoje = date.today()
    dados_calendario = _dados_calendario(ministerio, hoje)

    return render_template(
        "ministerio/calendario.html",
        ministerio=ministerio,
        **dados_calendario,
    )


@bp.route("/<int:ministerio_id>/editar", methods=["GET", "POST"])
@login_required
def editar(ministerio_id):
    ministerio = _ministerio_do_usuario_ou_404(ministerio_id)
    form = MinisterioForm(nome=ministerio.nome, descricao=ministerio.descricao)

    if form.validate_on_submit():
        ministerio.nome = form.nome.data.strip()
        ministerio.descricao = (form.descricao.data or "").strip() or None

        if form.imagem.data:
            logo_antiga = ministerio.imagem
            ministerio.imagem = _salvar_logo(form.imagem.data)
            _remover_logo_antiga(logo_antiga)

        db.session.commit()
        flash("Ministerio atualizado!", "success")
        return redirect(url_for("ministerio.detalhe", ministerio_id=ministerio.id))

    return render_template("ministerio/editar.html", form=form, ministerio=ministerio)


@bp.route("/<int:ministerio_id>/excluir", methods=["POST"])
@login_required
def excluir_ministerio(ministerio_id):
    ministerio = _ministerio_do_usuario_ou_404(ministerio_id)
    form = AcaoForm()

    if not form.validate_on_submit():
        flash("Acao invalida.", "danger")
        return redirect(url_for("ministerio.detalhe", ministerio_id=ministerio.id))

    # Cascade (cascade="all, delete-orphan" em Ministerio.escalas e
    # Ministerio.turnos_plantao) apaga junto todas as Escalas do ministerio
    # -- manuais e as geradas por rodizio -- e os Turnos de Rodizio. Diferente
    # de plantao.excluir_turno (que preserva historico ao apagar so a regra),
    # aqui o ministerio inteiro some, entao nao ha nada a preservar.
    _remover_logo_antiga(ministerio.imagem)

    nome = ministerio.nome
    comunidade_id = ministerio.comunidade_id
    db.session.delete(ministerio)
    db.session.commit()

    flash(f'Ministerio "{nome}" excluido.', "success")
    return redirect(url_for("comunidade.detalhe", comunidade_id=comunidade_id))
