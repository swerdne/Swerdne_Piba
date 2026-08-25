"""Controller (C do MVC): rotas do modulo escala."""
import concurrent.futures

from flask import render_template, redirect, url_for, flash, abort, request, jsonify, current_app
from flask_login import login_required, current_user
from sqlalchemy import or_

from app.extensions import db
from app.escala import bp
from app.escala.forms import (
    SelecionarMembroForm,
    MoverForm,
    StatusForm,
    AcaoForm,
    FuncaoForm,
    EscalaForm,
    EditarEscalaForm,
)
from app.escala.models import (
    Escala,
    Funcao,
    Membro,
    DEPARTAMENTOS,
    STATUS_PADRAO,
    STATUS_LABELS,
    STATUS_CORES,
    TIPO_SUBCABECALHO,
    criar_escala_com_funcoes_padrao,
    marcar_notificado,
    mensagem_para,
    trocar_atribuicao,
)
from app.emailing import enviar_email, EmailNaoEnviadoError
from app.sms import enviar_sms, SmsNaoEnviadoError
from app.auth.models import User
from app.notificacoes import Notificacao


def _escala_do_usuario_ou_404(escala_id):
    """Busca a escala garantindo que quem pede e admin da comunidade ou lider
    do ministerio dela (ver ministerio.routes._eh_lider_do_ministerio).

    Sem essa checagem, qualquer pessoa logada poderia mexer nos dados de
    outra conta so adivinhando o id na URL -- cada conta ve e altera apenas
    as proprias escalas/funcoes/membros.
    """
    from app.ministerio.routes import _eh_lider_do_ministerio

    escala = Escala.query.get_or_404(escala_id)
    if not _eh_lider_do_ministerio(escala.ministerio, current_user):
        abort(404)
    return escala


def _funcao_do_usuario_ou_404(funcao_id):
    from app.ministerio.routes import _eh_lider_do_ministerio

    funcao = Funcao.query.get_or_404(funcao_id)
    if not _eh_lider_do_ministerio(funcao.escala.ministerio, current_user):
        abort(404)
    return funcao


def _escala_visivel_ou_404(escala_id):
    """Acesso de LEITURA: admin/lider (gerencia) OU membro do ministerio OU
    convidado escalado nesta Escala especifica (Funcao.eh_convidado=True cujo
    Membro tem o mesmo e-mail da conta logada) -- mesmo mecanismo de match
    por e-mail ja usado em comunidade.routes._comunidade_visivel_ou_404, so
    que escopado a 1 unica Escala em vez da comunidade inteira. Retorna
    (escala, pode_gerenciar)."""
    from app.ministerio.routes import _eh_lider_do_ministerio, _eh_membro_do_ministerio

    escala = Escala.query.get_or_404(escala_id)
    pode_gerenciar = _eh_lider_do_ministerio(escala.ministerio, current_user)
    eh_membro = pode_gerenciar or _eh_membro_do_ministerio(escala.ministerio, current_user)
    eh_convidado_vinculado = any(
        f.eh_convidado and f.membro and f.membro.email == current_user.email
        for f in escala.funcoes
    )
    if not eh_membro and not eh_convidado_vinculado:
        abort(404)
    return escala, pode_gerenciar


def _fixar_se_gerada_por_rodizio(escala):
    """Uma edicao manual numa Escala gerada por Turno de Rodizio (ver
    app/plantao/sincronizacao.py) precisa travar essa ocorrencia (plantao_fixado)
    para o proximo sync nao sobrescrever a mudanca manual com a formula pura."""
    if escala.plantao_turno_id is not None:
        escala.plantao_fixado = True


@bp.route("/")
@login_required
def index():
    # A listagem de escalas agora vive dentro de cada comunidade.
    return redirect(url_for("comunidade.index"))


@bp.route("/ministerio/<int:ministerio_id>/nova", methods=["GET", "POST"])
@login_required
def nova(ministerio_id):
    from app.ministerio.routes import _ministerio_gerenciavel_ou_404

    ministerio = _ministerio_gerenciavel_ou_404(ministerio_id)
    form = EscalaForm()

    if form.validate_on_submit():
        escala = criar_escala_com_funcoes_padrao(
            ministerio_id=ministerio.id,
            nome=form.nome.data.strip(),
            departamento=form.departamento.data,
            data=form.data.data,
            horario=form.horario.data,
            cor_selecionada=form.cor.data or None,
        )
        flash(f'Escala "{escala.nome}" criada!', "success")
        return redirect(url_for("escala.detalhe", escala_id=escala.id))

    return render_template("escala/nova.html", form=form, ministerio=ministerio)


@bp.route("/<int:escala_id>/editar", methods=["GET", "POST"])
@login_required
def editar(escala_id):
    escala = _escala_do_usuario_ou_404(escala_id)
    # obj= (nao kwargs soltos) porque nosso campo se chama "data", que colide
    # com o parametro reservado `data=` do proprio construtor do WTForms.
    form = EditarEscalaForm(obj=escala)
    if request.method == "GET":
        # obj= so casa por nome de atributo -- o campo se chama "cor" mas o
        # model guarda em cor_selecionada, entao precisa popular na mao.
        form.cor.data = escala.cor_selecionada or ""

    if form.validate_on_submit():
        nome_antigo = escala.nome
        data_antiga, horario_antigo = escala.data, escala.horario

        mudou_nome = form.nome.data.strip() != escala.nome
        mudou_data_horario = form.data.data != escala.data or form.horario.data != escala.horario

        escala.nome = form.nome.data.strip()
        escala.data = form.data.data
        escala.horario = form.horario.data
        escala.cor_selecionada = form.cor.data or None

        if mudou_data_horario:
            # A data/horario mudou -- as notificacoes automaticas de 24h/16h
            # precisam recalcular a partir da nova data (ver app/escala/agendador.py).
            escala.notificado_24h_em = None
            escala.notificado_16h_em = None

        if mudou_nome or mudou_data_horario:
            # Edicao manual de uma ocorrencia gerada por rodizio -- trava essa
            # Escala especifica pra o proximo sync do turno nao sobrescrever.
            _fixar_se_gerada_por_rodizio(escala)

        db.session.commit()

        mensagens = []
        if mudou_nome:
            mensagens.append(f'Nome atualizado de "{nome_antigo}" para "{escala.nome}".')
        if mudou_data_horario:
            resultado = enviar_notificacao_de_alteracao(escala, data_antiga, horario_antigo)
            partes = []
            if resultado["notificacoes_app"]:
                partes.append(f"{resultado['notificacoes_app']} notificacao(oes) no app")
            if resultado["email_enviados"]:
                partes.append(f"{resultado['email_enviados']} e-mail(s) enviado(s)")
            if resultado["sms_enviados"]:
                partes.append(f"{resultado['sms_enviados']} SMS enviado(s)")
            aviso = f" Equipe avisada da mudanca: {', '.join(partes)}." if partes else ""
            mensagens.append(f"Data/horario atualizados.{aviso}")
        if not mensagens:
            mensagens.append("Nenhuma mudanca.")

        flash(" ".join(mensagens), "success")
        return redirect(url_for("escala.detalhe", escala_id=escala.id))

    return render_template("escala/editar.html", form=form, escala=escala)


@bp.route("/<int:escala_id>")
@login_required
def detalhe(escala_id):
    escala, eh_dono = _escala_visivel_ou_404(escala_id)

    formularios_membro = {}
    formularios_mover = {}
    formularios_status = {}
    formularios_editar_funcao = {}
    diretorio_vazio = False

    if eh_dono:
        # Convidado so le a grade (ver template) -- monta os forms de escrita
        # so pra quem pode escrever, poupa consultas desnecessarias pro convidado.
        diretorio = Membro.query.filter_by(comunidade_id=escala.ministerio.comunidade_id).order_by(Membro.nome).all()
        diretorio_vazio = not diretorio
        destinos_possiveis = [f for f in escala.funcoes if not f.eh_subcabecalho]

        for funcao in escala.funcoes:
            formularios_editar_funcao[funcao.id] = FuncaoForm(nome=funcao.nome)

            if funcao.eh_subcabecalho:
                continue

            if funcao.membro_id is None:
                form_membro = SelecionarMembroForm()
                # Placeholder em 0 (nao um id real) -- sem isso o <select> nao
                # tem opcao em branco e o navegador mostra a primeira pessoa
                # da lista como se ja estivesse escolhida (DataRequired
                # barra o 0 como valor invalido se a pessoa nao trocar).
                form_membro.membro_id.choices = [(0, "Selecione a pessoa")] + [
                    (m.id, m.nome) for m in diretorio
                ]
                formularios_membro[funcao.id] = form_membro
            else:
                mover_form = MoverForm()
                mover_form.destino_funcao_id.choices = [
                    (f.id, f.nome) for f in destinos_possiveis if f.id != funcao.id
                ]
                formularios_mover[funcao.id] = mover_form
                formularios_status[funcao.id] = StatusForm(status=funcao.status or STATUS_PADRAO)
    else:
        # Nao gerencia a escala, mas pode marcar o PROPRIO status (ver
        # escala.routes.atualizar_status) -- so monta o form pra funcao(oes)
        # cujo Membro bate por e-mail com a conta logada.
        email_logado = (current_user.email or "").lower()
        for funcao in escala.funcoes:
            if (
                not funcao.eh_subcabecalho and funcao.membro_id and funcao.membro.email
                and funcao.membro.email.lower() == email_logado
            ):
                formularios_status[funcao.id] = StatusForm(status=funcao.status or STATUS_PADRAO)

    return render_template(
        "escala/detalhe.html",
        escala=escala,
        eh_dono=eh_dono,
        diretorio_vazio=diretorio_vazio,
        formularios_membro=formularios_membro,
        formularios_mover=formularios_mover,
        formularios_status=formularios_status,
        formularios_editar_funcao=formularios_editar_funcao,
        formulario_nova_funcao=FuncaoForm(),
        formulario_novo_subcabecalho=FuncaoForm(),
        acao_form=AcaoForm(),
        status_labels=STATUS_LABELS,
        status_cores=STATUS_CORES,
    )


@bp.route("/<int:escala_id>/funcao/adicionar", methods=["POST"])
@login_required
def adicionar_funcao(escala_id):
    escala = _escala_do_usuario_ou_404(escala_id)

    if escala.plantao_turno_id is not None:
        flash("Escalas geradas por rodizio tem sempre uma unica funcao.", "danger")
        return redirect(url_for("escala.detalhe", escala_id=escala.id))

    form = FuncaoForm()

    if not form.validate_on_submit():
        erros = [erro for lista in form.errors.values() for erro in lista]
        flash(erros[0] if erros else "Nao foi possivel adicionar a funcao.", "danger")
        return redirect(url_for("escala.detalhe", escala_id=escala.id))

    maior_ordem = max([f.ordem for f in escala.funcoes], default=-1)
    nova_funcao = Funcao(escala_id=escala.id, nome=form.nome.data.strip(), ordem=maior_ordem + 1)
    db.session.add(nova_funcao)
    db.session.commit()

    flash(f'Funcao "{nova_funcao.nome}" adicionada em {escala.nome}.', "success")
    return redirect(url_for("escala.detalhe", escala_id=escala.id))


@bp.route("/<int:escala_id>/subcabecalho/adicionar", methods=["POST"])
@login_required
def adicionar_subcabecalho(escala_id):
    escala = _escala_do_usuario_ou_404(escala_id)

    if escala.plantao_turno_id is not None:
        flash("Escalas geradas por rodizio tem sempre uma unica funcao.", "danger")
        return redirect(url_for("escala.detalhe", escala_id=escala.id))

    form = FuncaoForm()

    if not form.validate_on_submit():
        erros = [erro for lista in form.errors.values() for erro in lista]
        flash(erros[0] if erros else "Nao foi possivel adicionar a categoria.", "danger")
        return redirect(url_for("escala.detalhe", escala_id=escala.id))

    maior_ordem = max([f.ordem for f in escala.funcoes], default=-1)
    novo_subcabecalho = Funcao(
        escala_id=escala.id, nome=form.nome.data.strip(), ordem=maior_ordem + 1, tipo=TIPO_SUBCABECALHO
    )
    db.session.add(novo_subcabecalho)
    db.session.commit()

    flash(f'Categoria "{novo_subcabecalho.nome}" adicionada em {escala.nome}.', "success")
    return redirect(url_for("escala.detalhe", escala_id=escala.id))


@bp.route("/funcao/<int:funcao_id>/editar", methods=["POST"])
@login_required
def editar_funcao(funcao_id):
    funcao = _funcao_do_usuario_ou_404(funcao_id)
    form = FuncaoForm()

    if not form.validate_on_submit():
        erros = [erro for lista in form.errors.values() for erro in lista]
        flash(erros[0] if erros else "Nao foi possivel renomear a funcao.", "danger")
        return redirect(url_for("escala.detalhe", escala_id=funcao.escala_id))

    nome_antigo = funcao.nome
    funcao.nome = form.nome.data.strip()
    db.session.commit()

    flash(f'"{nome_antigo}" renomeada para "{funcao.nome}".', "success")
    return redirect(url_for("escala.detalhe", escala_id=funcao.escala_id))


@bp.route("/funcao/<int:funcao_id>/excluir", methods=["POST"])
@login_required
def excluir_funcao(funcao_id):
    funcao = _funcao_do_usuario_ou_404(funcao_id)
    form = AcaoForm()
    escala_id = funcao.escala_id

    if not form.validate_on_submit():
        flash("Acao invalida.", "danger")
        return redirect(url_for("escala.detalhe", escala_id=escala_id))

    nome = funcao.nome
    escala_nome = funcao.escala.nome
    db.session.delete(funcao)
    db.session.commit()

    flash(f'Funcao "{nome}" removida de {escala_nome}.', "success")
    return redirect(url_for("escala.detalhe", escala_id=escala_id))


@bp.route("/funcao/<int:funcao_id>/adicionar", methods=["POST"])
@login_required
def adicionar_membro(funcao_id):
    funcao = _funcao_do_usuario_ou_404(funcao_id)
    comunidade_id = funcao.escala.ministerio.comunidade_id
    diretorio = Membro.query.filter_by(comunidade_id=comunidade_id).order_by(Membro.nome).all()

    if not diretorio:
        flash(
            "O diretorio da comunidade ainda nao tem ninguem cadastrado.",
            "danger",
        )
        return redirect(url_for("comunidade.membros", comunidade_id=comunidade_id))

    form = SelecionarMembroForm()
    form.membro_id.choices = [(m.id, m.nome) for m in diretorio]

    if not form.validate_on_submit():
        erros = [erro for lista in form.errors.values() for erro in lista]
        flash(erros[0] if erros else "Nao foi possivel adicionar o membro.", "danger")
        return redirect(url_for("escala.detalhe", escala_id=funcao.escala_id))

    membro = Membro.query.filter_by(id=form.membro_id.data, comunidade_id=comunidade_id).first()
    if membro is None:
        flash("Pessoa invalida para esta comunidade.", "danger")
        return redirect(url_for("escala.detalhe", escala_id=funcao.escala_id))

    funcao.membro_id = membro.id
    funcao.status = STATUS_PADRAO
    funcao.notificado_em = None
    funcao.eh_convidado = False
    _fixar_se_gerada_por_rodizio(funcao.escala)
    db.session.commit()

    flash(f"{membro.nome} adicionado(a) em {funcao.nome}.", "success")
    return redirect(url_for("escala.detalhe", escala_id=funcao.escala_id))


@bp.route("/funcao/<int:funcao_id>/buscar-usuario")
@login_required
def buscar_usuario(funcao_id):
    """Busca contas (User) ja cadastradas na plataforma por nome/username/
    e-mail, pra vincular como convidado (ver adicionar_convidado). JSON, sem
    campos sensiveis -- so o que aparece no autocomplete de busca."""
    _funcao_do_usuario_ou_404(funcao_id)
    termo = request.args.get("q", "").strip()

    if len(termo) < 2:
        return jsonify([])

    padrao = f"%{termo}%"
    usuarios = (
        User.query.filter(
            or_(User.name.ilike(padrao), User.username.ilike(padrao), User.email.ilike(padrao))
        )
        .order_by(User.name)
        .limit(8)
        .all()
    )

    return jsonify([
        {"id": u.id, "label": f"{u.name or u.username or u.email} ({u.email})"}
        for u in usuarios
    ])


@bp.route("/funcao/<int:funcao_id>/adicionar-convidado", methods=["POST"])
@login_required
def adicionar_convidado(funcao_id):
    """Vincula uma conta (User) ja existente na plataforma a funcao, como
    convidado -- participacao pontual. Nao cria uma conta nova nem duplica
    cadastro: encontra ou cria o Membro correspondente (por e-mail) no
    diretorio da comunidade, reaproveitando o mesmo caminho de atribuicao
    (Funcao.membro_id) que ja existe, so marcado com eh_convidado=True."""
    funcao = _funcao_do_usuario_ou_404(funcao_id)
    comunidade_id = funcao.escala.ministerio.comunidade_id

    form = AcaoForm()
    if not form.validate_on_submit():
        flash("Acao invalida.", "danger")
        return redirect(url_for("escala.detalhe", escala_id=funcao.escala_id))

    usuario_id = request.form.get("usuario_id", type=int)
    usuario = User.query.get(usuario_id) if usuario_id else None
    if usuario is None:
        flash("Selecione um usuario valido na busca.", "danger")
        return redirect(url_for("escala.detalhe", escala_id=funcao.escala_id))

    membro = Membro.query.filter_by(comunidade_id=comunidade_id, email=usuario.email).first()
    if membro is None:
        membro = Membro(
            comunidade_id=comunidade_id,
            nome=usuario.name or usuario.username or usuario.email,
            email=usuario.email,
        )
        db.session.add(membro)
        db.session.flush()

    funcao.membro_id = membro.id
    funcao.status = STATUS_PADRAO
    funcao.notificado_em = None
    funcao.eh_convidado = True
    _fixar_se_gerada_por_rodizio(funcao.escala)
    db.session.commit()

    flash(f"{membro.nome} adicionado(a) como convidado(a) em {funcao.nome}.", "success")
    return redirect(url_for("escala.detalhe", escala_id=funcao.escala_id))


@bp.route("/funcao/<int:funcao_id>/remover", methods=["POST"])
@login_required
def remover_membro(funcao_id):
    funcao = _funcao_do_usuario_ou_404(funcao_id)
    form = AcaoForm()
    escala_id = funcao.escala_id

    if not form.validate_on_submit():
        flash("Acao invalida.", "danger")
        return redirect(url_for("escala.detalhe", escala_id=escala_id))

    nome_removido = funcao.membro.nome if funcao.membro else None
    funcao.membro_id = None
    funcao.status = None
    funcao.notificado_em = None
    funcao.eh_convidado = False
    _fixar_se_gerada_por_rodizio(funcao.escala)
    db.session.commit()

    if nome_removido:
        flash(f"{nome_removido} removido(a) de {funcao.nome}.", "success")
    return redirect(url_for("escala.detalhe", escala_id=escala_id))


@bp.route("/funcao/<int:funcao_id>/mover", methods=["POST"])
@login_required
def mover_membro(funcao_id):
    origem = _funcao_do_usuario_ou_404(funcao_id)
    escala_id = origem.escala_id

    if origem.membro_id is None:
        flash("Essa funcao nao tem ninguem escalado para mover.", "danger")
        return redirect(url_for("escala.detalhe", escala_id=escala_id))

    outras = [f for f in origem.escala.funcoes if f.id != origem.id and not f.eh_subcabecalho]
    form = MoverForm()
    form.destino_funcao_id.choices = [(f.id, f.nome) for f in outras]

    if not form.validate_on_submit():
        flash("Nao foi possivel mover o membro.", "danger")
        return redirect(url_for("escala.detalhe", escala_id=escala_id))

    destino = _funcao_do_usuario_ou_404(form.destino_funcao_id.data)

    # Troca (swap) os dois lados -- se o destino estiver vazio, e so uma mudanca de lugar.
    trocar_atribuicao(origem, destino)
    _fixar_se_gerada_por_rodizio(origem.escala)
    _fixar_se_gerada_por_rodizio(destino.escala)
    db.session.commit()

    flash(f"{origem.nome} e {destino.nome} atualizados.", "success")
    return redirect(url_for("escala.detalhe", escala_id=escala_id))


@bp.route("/funcao/<int:funcao_id>/status", methods=["POST"])
@login_required
def atualizar_status(funcao_id):
    # Excecao proposital: marcar o PROPRIO status (presente/confirmado/etc)
    # e permitido pra quem esta escalado naquela funcao (Membro.email bate
    # com a conta logada, mesmo mecanismo de convidado/visibilidade por
    # e-mail), sem precisar ser lider/admin -- "marcar ausencia -> o proprio
    # membro escalado, ou lider/admin" (ver app/convites/CLAUDE.md). Qualquer
    # outra pessoa continua exigindo _funcao_do_usuario_ou_404 (lider/admin).
    funcao_bruta = Funcao.query.get_or_404(funcao_id)
    eh_proprio_escalado = (
        funcao_bruta.membro_id is not None
        and funcao_bruta.membro.email
        and funcao_bruta.membro.email.lower() == (current_user.email or "").lower()
    )
    funcao = funcao_bruta if eh_proprio_escalado else _funcao_do_usuario_ou_404(funcao_id)
    escala_id = funcao.escala_id

    if funcao.membro_id is None:
        flash("Essa funcao nao tem ninguem escalado.", "danger")
        return redirect(url_for("escala.detalhe", escala_id=escala_id))

    form = StatusForm()
    if not form.validate_on_submit():
        flash("Status invalido.", "danger")
        return redirect(url_for("escala.detalhe", escala_id=escala_id))

    funcao.status = form.status.data
    db.session.commit()
    return redirect(url_for("escala.detalhe", escala_id=escala_id))


# Teto pro tempo TOTAL de uma leva de notificacoes, nao por pessoa. Cada
# enviar_email/enviar_sms ja tem seu proprio timeout individual (~12s), mas
# antes disso as tentativas rodavam uma de cada vez -- uma escala com N
# pessoas e um servidor de e-mail fora do ar levava N vezes o timeout de uma
# unica tentativa, o que ja estourou o timeout do worker do servidor de
# producao (gunicorn) e derrubou o processo (SIGKILL) mesmo depois do
# timeout individual existir. Ver _disparar_notificacoes_em_paralelo abaixo.
_TIMEOUT_TOTAL_NOTIFICACAO_SEGUNDOS = 20


def _disparar_notificacoes_em_paralelo(tarefas):
    """Dispara e-mail/SMS de cada tarefa ao mesmo tempo (nao uma por vez).

    So faz chamada de rede -- nunca toca no ORM/sessao do banco, que nao e
    thread-safe entre threads diferentes. `tarefas` e uma lista de dicts com
    dados ja extraidos (nao objetos do SQLAlchemy), pra cada worker ficar
    isolado de qualquer estado da sessao da request original.
    """
    resultados = {t["funcao_id"]: {"email_ok": False, "sms_ok": False} for t in tarefas}
    if not tarefas:
        return resultados

    app_obj = current_app._get_current_object()

    def _enviar_para_uma_tarefa(tarefa):
        resultado = {"email_ok": False, "sms_ok": False}
        with app_obj.app_context():
            if tarefa["email"]:
                try:
                    enviar_email(destinatario=tarefa["email"], assunto=tarefa["assunto"], corpo=tarefa["mensagem"])
                    resultado["email_ok"] = True
                except EmailNaoEnviadoError:
                    pass
            if tarefa["telefone"]:
                try:
                    enviar_sms(destinatario=tarefa["telefone"], corpo=tarefa["mensagem"])
                    resultado["sms_ok"] = True
                except SmsNaoEnviadoError:
                    pass
        return tarefa["funcao_id"], resultado

    pool = concurrent.futures.ThreadPoolExecutor(max_workers=min(len(tarefas), 8))
    futuro_para_tarefa = {pool.submit(_enviar_para_uma_tarefa, t): t for t in tarefas}

    # wait() com timeout unico pro lote inteiro -- nao um .result(timeout=X)
    # por future em sequencia, que voltaria a somar o tempo por pessoa.
    concluidos, _pendentes = concurrent.futures.wait(
        futuro_para_tarefa.keys(), timeout=_TIMEOUT_TOTAL_NOTIFICACAO_SEGUNDOS
    )
    for futuro in concluidos:
        funcao_id, resultado = futuro.result()
        resultados[funcao_id] = resultado

    # wait=False: tarefas que ainda nao terminaram ficam presas em segundo
    # plano (pool com tamanho fixo, entao o teto de memoria e limitado) em vez
    # de travar a resposta da request esperando elas acabarem.
    pool.shutdown(wait=False)
    return resultados


def enviar_notificacoes_da_escala(escala):
    """Notifica todo mundo escalado numa escala (por e-mail/SMS/app).

    Reutilizada tanto pelo botao manual quanto pelo agendador automatico
    (24h/16h antes do evento) -- ver app/escala/agendador.py.
    """
    escalados = [f for f in escala.funcoes if f.membro_id is not None]

    tarefas = [
        {
            "funcao_id": funcao.id,
            "email": funcao.membro.email,
            "telefone": funcao.membro.telefone,
            "mensagem": mensagem_para(escala, funcao, funcao.membro),
            "assunto": f"Voce foi escalado(a): {funcao.nome} - {escala.nome}",
        }
        for funcao in escalados
    ]
    resultados_por_funcao = _disparar_notificacoes_em_paralelo(tarefas)

    notificacoes_app = 0
    email_enviados = email_falhas = 0
    sms_enviados = sms_falhas = 0
    sem_contato = 0

    for funcao in escalados:
        membro = funcao.membro
        resultado = resultados_por_funcao[funcao.id]
        notificou_algum_canal = False

        if membro.email:
            # Se a pessoa tem conta no site, tambem aparece no sino dela ao logar --
            # isso e um EXTRA, nao substitui o e-mail.
            usuario_vinculado = User.query.filter_by(email=membro.email).first()
            if usuario_vinculado:
                db.session.add(Notificacao(
                    usuario_id=usuario_vinculado.id,
                    titulo=f"Voce foi escalado(a) para {funcao.nome}",
                    mensagem=f"{escala.nome} ({escala.departamento}) - {funcao.nome}.",
                ))
                notificacoes_app += 1
                notificou_algum_canal = True

            if resultado["email_ok"]:
                email_enviados += 1
                notificou_algum_canal = True
            else:
                email_falhas += 1

        if membro.telefone:
            if resultado["sms_ok"]:
                sms_enviados += 1
                notificou_algum_canal = True
            else:
                sms_falhas += 1

        if not membro.email and not membro.telefone:
            sem_contato += 1

        if notificou_algum_canal:
            marcar_notificado(funcao)

    db.session.commit()

    return {
        "escalados": len(escalados),
        "notificacoes_app": notificacoes_app,
        "email_enviados": email_enviados,
        "email_falhas": email_falhas,
        "sms_enviados": sms_enviados,
        "sms_falhas": sms_falhas,
        "sem_contato": sem_contato,
    }


def enviar_notificacao_de_alteracao(escala, data_antiga, horario_antigo):
    """Avisa quem ja esta escalado que a data/horario do evento mudou.

    Chamada por app/escala/routes.py::editar_data_horario apos uma edicao que
    realmente muda data ou horario -- nao mexe em Funcao.notificado_em, que e
    especifico da notificacao de escalacao (ver enviar_notificacoes_da_escala).
    """
    escalados = [f for f in escala.funcoes if f.membro_id is not None]

    data_antiga_texto = data_antiga.strftime("%d/%m/%Y") if data_antiga else "sem data definida"
    horario_antigo_texto = f" as {horario_antigo.strftime('%H:%M')}" if horario_antigo else ""
    data_nova_texto = escala.data.strftime("%d/%m/%Y") if escala.data else "sem data definida"
    horario_novo_texto = f" as {escala.horario.strftime('%H:%M')}" if escala.horario else ""

    mensagem = (
        f"A data/horario de {escala.nome} mudou de {data_antiga_texto}{horario_antigo_texto} "
        f"para {data_nova_texto}{horario_novo_texto}."
    )

    notificacoes_app = 0
    email_enviados = email_falhas = 0
    sms_enviados = sms_falhas = 0

    for funcao in escalados:
        membro = funcao.membro

        if membro.email:
            usuario_vinculado = User.query.filter_by(email=membro.email).first()
            if usuario_vinculado:
                db.session.add(Notificacao(
                    usuario_id=usuario_vinculado.id,
                    titulo=f"Mudanca de data: {escala.nome}",
                    mensagem=mensagem,
                ))
                notificacoes_app += 1

            try:
                enviar_email(
                    destinatario=membro.email,
                    assunto=f"Mudanca de data: {escala.nome}",
                    corpo=mensagem,
                )
                email_enviados += 1
            except EmailNaoEnviadoError:
                email_falhas += 1

        if membro.telefone:
            try:
                enviar_sms(destinatario=membro.telefone, corpo=mensagem)
                sms_enviados += 1
            except SmsNaoEnviadoError:
                sms_falhas += 1

    db.session.commit()

    return {
        "notificacoes_app": notificacoes_app,
        "email_enviados": email_enviados,
        "email_falhas": email_falhas,
        "sms_enviados": sms_enviados,
        "sms_falhas": sms_falhas,
    }


@bp.route("/<int:escala_id>/notificar", methods=["POST"])
@login_required
def notificar_escala(escala_id):
    escala = _escala_do_usuario_ou_404(escala_id)
    form = AcaoForm()

    if not form.validate_on_submit():
        flash("Acao invalida.", "danger")
        return redirect(url_for("escala.detalhe", escala_id=escala.id))

    if not any(f.membro_id is not None for f in escala.funcoes):
        flash(f"Ninguem escalado em {escala.nome} para notificar.", "danger")
        return redirect(url_for("escala.detalhe", escala_id=escala.id))

    resultado = enviar_notificacoes_da_escala(escala)

    partes = []
    if resultado["notificacoes_app"]:
        partes.append(f"{resultado['notificacoes_app']} notificacao(oes) no app")
    if resultado["email_enviados"]:
        partes.append(f"{resultado['email_enviados']} e-mail(s) enviado(s)")
    if resultado["sms_enviados"]:
        partes.append(f"{resultado['sms_enviados']} SMS enviado(s)")
    if resultado["email_falhas"]:
        partes.append(f"{resultado['email_falhas']} e-mail(s) falharam")
    if resultado["sms_falhas"]:
        partes.append(f"{resultado['sms_falhas']} SMS falharam")
    if resultado["sem_contato"]:
        partes.append(f"{resultado['sem_contato']} sem e-mail/telefone cadastrado")

    houve_sucesso = bool(resultado["notificacoes_app"] or resultado["email_enviados"] or resultado["sms_enviados"])
    flash(", ".join(partes) + "." if partes else "Nada foi enviado.", "success" if houve_sucesso else "danger")
    return redirect(url_for("escala.detalhe", escala_id=escala.id))


@bp.route("/<int:escala_id>/excluir", methods=["POST"])
@login_required
def excluir_escala(escala_id):
    escala = _escala_do_usuario_ou_404(escala_id)
    form = AcaoForm()

    if not form.validate_on_submit():
        flash("Acao invalida.", "danger")
        return redirect(url_for("escala.detalhe", escala_id=escala.id))

    nome = escala.nome
    ministerio_id = escala.ministerio_id
    db.session.delete(escala)
    db.session.commit()

    flash(f'Escala "{nome}" excluida.', "success")
    return redirect(url_for("ministerio.detalhe", ministerio_id=ministerio_id))


@bp.route("/excluir-varias", methods=["POST"])
@login_required
def excluir_varias():
    """Exclusao em lote (ver ministerio/detalhe.html) -- so mexe em escalas
    manuais (plantao_turno_id vazio) de ministerios que o usuario lidera/
    administra; nunca confia cegamente na lista de ids recebida do form."""
    from app.ministerio.routes import _eh_lider_do_ministerio

    form = AcaoForm()
    if not form.validate_on_submit():
        flash("Acao invalida.", "danger")
        return redirect(request.referrer or url_for("comunidade.index"))

    ids = request.form.getlist("escala_ids", type=int)
    escalas = Escala.query.filter(Escala.id.in_(ids)).all() if ids else []

    # Commit por escala (nao um so no final) -- ver mesmo comentario em
    # comunidade.excluir_varias: um commit unico no fim perde tudo se a
    # requisicao for interrompida no meio de um lote grande.
    ministerio_id = None
    excluidas = 0
    for escala in escalas:
        ministerio_id = ministerio_id or escala.ministerio_id
        if escala.plantao_turno_id is not None:
            continue  # gerada por rodizio -- fora do escopo da exclusao em lote
        if not _eh_lider_do_ministerio(escala.ministerio, current_user):
            continue
        db.session.delete(escala)
        db.session.commit()
        excluidas += 1

    if excluidas:
        plural = "s" if excluidas != 1 else ""
        flash(f"{excluidas} escala{plural} excluida{plural}.", "success")
    else:
        flash("Nenhuma escala valida foi selecionada.", "danger")

    if ministerio_id:
        return redirect(url_for("ministerio.detalhe", ministerio_id=ministerio_id))
    return redirect(request.referrer or url_for("comunidade.index"))
