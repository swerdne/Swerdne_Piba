"""Controller (C do MVC): rotas do modulo escala."""
from flask import render_template, redirect, url_for, flash, abort
from flask_login import login_required, current_user

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
    """Busca a escala garantindo que pertence ao dono da comunidade dela.

    Sem essa checagem, qualquer pessoa logada poderia mexer nos dados de
    outra conta so adivinhando o id na URL -- cada conta ve e altera apenas
    as proprias escalas/funcoes/membros.
    """
    escala = Escala.query.get_or_404(escala_id)
    if escala.ministerio.comunidade.usuario_id != current_user.id:
        abort(404)
    return escala


def _funcao_do_usuario_ou_404(funcao_id):
    funcao = Funcao.query.get_or_404(funcao_id)
    if funcao.escala.ministerio.comunidade.usuario_id != current_user.id:
        abort(404)
    return funcao


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
    from app.ministerio.routes import _ministerio_do_usuario_ou_404

    ministerio = _ministerio_do_usuario_ou_404(ministerio_id)
    form = EscalaForm()

    if form.validate_on_submit():
        escala = criar_escala_com_funcoes_padrao(
            ministerio_id=ministerio.id,
            nome=form.nome.data.strip(),
            departamento=form.departamento.data,
            data=form.data.data,
            horario=form.horario.data,
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

    if form.validate_on_submit():
        nome_antigo = escala.nome
        data_antiga, horario_antigo = escala.data, escala.horario

        mudou_nome = form.nome.data.strip() != escala.nome
        mudou_data_horario = form.data.data != escala.data or form.horario.data != escala.horario

        escala.nome = form.nome.data.strip()
        escala.data = form.data.data
        escala.horario = form.horario.data

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
    escala = _escala_do_usuario_ou_404(escala_id)

    formularios_membro = {}
    formularios_mover = {}
    formularios_status = {}
    formularios_editar_funcao = {}

    diretorio = Membro.query.filter_by(comunidade_id=escala.ministerio.comunidade_id).order_by(Membro.nome).all()

    destinos_possiveis = [f for f in escala.funcoes if not f.eh_subcabecalho]

    for funcao in escala.funcoes:
        formularios_editar_funcao[funcao.id] = FuncaoForm(nome=funcao.nome)

        if funcao.eh_subcabecalho:
            continue

        if funcao.membro_id is None:
            form_membro = SelecionarMembroForm()
            form_membro.membro_id.choices = [(m.id, m.nome) for m in diretorio]
            formularios_membro[funcao.id] = form_membro
        else:
            mover_form = MoverForm()
            mover_form.destino_funcao_id.choices = [
                (f.id, f.nome) for f in destinos_possiveis if f.id != funcao.id
            ]
            formularios_mover[funcao.id] = mover_form
            formularios_status[funcao.id] = StatusForm(status=funcao.status or STATUS_PADRAO)

    return render_template(
        "escala/detalhe.html",
        escala=escala,
        diretorio_vazio=not diretorio,
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
    _fixar_se_gerada_por_rodizio(funcao.escala)
    db.session.commit()

    flash(f"{membro.nome} adicionado(a) em {funcao.nome}.", "success")
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
    funcao = _funcao_do_usuario_ou_404(funcao_id)
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


def enviar_notificacoes_da_escala(escala):
    """Notifica todo mundo escalado numa escala (por e-mail/SMS/app).

    Reutilizada tanto pelo botao manual quanto pelo agendador automatico
    (24h/16h antes do evento) -- ver app/escala/agendador.py.
    """
    escalados = [f for f in escala.funcoes if f.membro_id is not None]

    notificacoes_app = 0
    email_enviados = email_falhas = 0
    sms_enviados = sms_falhas = 0
    sem_contato = 0

    for funcao in escalados:
        membro = funcao.membro
        mensagem = mensagem_para(escala, funcao, membro)
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

            try:
                enviar_email(
                    destinatario=membro.email,
                    assunto=f"Voce foi escalado(a): {funcao.nome} - {escala.nome}",
                    corpo=mensagem,
                )
                email_enviados += 1
                notificou_algum_canal = True
            except EmailNaoEnviadoError:
                email_falhas += 1

        if membro.telefone:
            try:
                enviar_sms(destinatario=membro.telefone, corpo=mensagem)
                sms_enviados += 1
                notificou_algum_canal = True
            except SmsNaoEnviadoError:
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
