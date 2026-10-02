"""Controller (C do MVC): rotas do modulo escala."""
import concurrent.futures
import os
import io
from datetime import datetime, time, timedelta, timezone

from flask import render_template, redirect, url_for, flash, abort, request, jsonify, current_app, send_file
from flask_login import login_required, current_user
from mongoengine.queryset.visitor import Q as MongoQ

from app.db_utils import delete_cascade, primeiro_ou_404
from app.escala import bp
from app.escala.forms import (
    SelecionarMembroForm,
    MoverForm,
    StatusForm,
    AcaoForm,
    FuncaoForm,
    EscalaForm,
    EditarEscalaForm,
    TrocaAprovarForm,
    ItemRepertorioForm,
    EnsaioForm,
    AnexoForm,
    ItemDoBancoForm,
    ObservacoesRepertorioForm,
)
from app.escala.models import (
    Escala,
    Funcao,
    Membro,
    ItemRepertorio,
    Ensaio,
    Anexo,
    Musica,
    blocos_da_letra,
    TIPOS_ANEXO,
    TAMANHO_MAXIMO_ANEXO,
    DEPARTAMENTOS,
    STATUS_PADRAO,
    STATUS_LABELS,
    STATUS_CORES,
    TIPO_SUBCABECALHO,
    criar_escala_com_funcoes_padrao,
    marcar_notificado,
    mensagem_para,
    trocar_atribuicao,
    avisos_disponibilidade,
)
from app.emailing import enviar_email, EmailNaoEnviadoError
from app.sms import enviar_sms, SmsNaoEnviadoError
from app.whatsapp import enviar_whatsapp_template, WhatsappNaoEnviadoError
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

    escala = primeiro_ou_404(Escala.objects(id=escala_id))
    if not _eh_lider_do_ministerio(escala.ministerio, current_user):
        abort(404)
    return escala


def _funcao_do_usuario_ou_404(funcao_id):
    from app.ministerio.routes import _eh_lider_do_ministerio

    funcao = primeiro_ou_404(Funcao.objects(id=funcao_id))
    if not _eh_lider_do_ministerio(funcao.escala.ministerio, current_user):
        abort(404)
    return funcao


def _escala_visivel_ou_404(escala_id):
    """Acesso de LEITURA: admin/lider (gerencia) OU membro do ministerio OU
    qualquer membro da Comunidade (papel=membro em UsuarioComunidade, mesma
    extensao de ministerio.routes._ministerio_visivel_ou_404) OU convidado
    escalado nesta Escala especifica (Funcao.eh_convidado=True cujo Membro
    tem o mesmo e-mail da conta logada) -- mesmo mecanismo de match por
    e-mail ja usado em comunidade.routes._comunidade_visivel_ou_404, so que
    escopado a 1 unica Escala em vez da comunidade inteira. Retorna
    (escala, pode_gerenciar)."""
    from app.comunidade.routes import _eh_membro_da_comunidade
    from app.ministerio.routes import _eh_lider_do_ministerio, _eh_membro_do_ministerio

    escala = primeiro_ou_404(Escala.objects(id=escala_id))
    pode_gerenciar = _eh_lider_do_ministerio(escala.ministerio, current_user)
    eh_membro = (
        pode_gerenciar
        or _eh_membro_do_ministerio(escala.ministerio, current_user)
        or _eh_membro_da_comunidade(escala.ministerio.comunidade, current_user)
    )
    eh_convidado_vinculado = any(
        f.eh_convidado and f.membro and f.membro.email == current_user.email
        for f in escala.funcoes
    )
    if not eh_membro and not eh_convidado_vinculado:
        abort(404)
    return escala, pode_gerenciar


def _avisos_conflito_horario(membro, escala_atual, funcao_atual_id=None):
    """Lista de avisos (string) se `membro` ja estiver escalado em OUTRA
    Escala com horario conflitante na mesma data -- nunca bloqueia, so
    avisa (quem esta montando a escala decide, ex: revezamento rapido entre
    dois cultos e as vezes intencional). Evento sem horario_fim e tratado
    como instantaneo (fim = inicio) na comparacao."""
    if not escala_atual.data:
        return []

    inicio_atual = escala_atual.horario or time.min
    fim_atual = escala_atual.horario_fim or inicio_atual

    # Sem join possivel (Funcao/Escala os dois no Mongo agora): busca as
    # outras Escalas na mesma data primeiro, depois as Funcoes desse membro
    # nelas.
    ids_outras_escalas = [
        e.id for e in Escala.objects(data=escala_atual.data, id__ne=escala_atual.id)
    ]
    outras_funcoes = list(Funcao.objects(
        membro_id=membro.id, escala_id__in=ids_outras_escalas, id__ne=(funcao_atual_id or -1)
    ))

    avisos = []
    for outra_funcao in outras_funcoes:
        outra_escala = outra_funcao.escala
        inicio_outro = outra_escala.horario or time.min
        fim_outro = outra_escala.horario_fim or inicio_outro
        if inicio_atual <= fim_outro and inicio_outro <= fim_atual:
            avisos.append(f'{membro.nome} ja esta escalado em "{outra_escala.nome}" nesse mesmo horario.')
    return avisos


def _fixar_se_gerada_por_rodizio(escala):
    """Uma edicao manual numa Escala gerada por Turno de Rodizio (ver
    app/plantao/sincronizacao.py) precisa travar essa ocorrencia (plantao_fixado)
    para o proximo sync nao sobrescrever a mudanca manual com a formula pura.

    Salva na hora (nao so muta o objeto em memoria) -- `escala` property do
    MongoEngine nao tem identity map, cada acesso a `funcao.escala` busca uma
    instancia NOVA, entao um `db.session.commit()` la no chamador nao
    persistiria essa mudanca."""
    if escala.plantao_turno_id is not None:
        escala.plantao_fixado = True
        escala.save()


def _notificar_lideres_do_ministerio(escala, titulo, mensagem, tipo):
    """Notifica (sino in-app) todo lider/admin com autoridade sobre o
    Ministerio dessa Escala (ver ministerio.routes._lideres_do_ministerio).

    So chamada quando o PROPRIO escalado muda seu status (ver
    atualizar_status) -- se quem mudou o status e o lider/admin, a mudanca ja
    e obra dele mesmo, notifica-lo seria ruido.
    """
    from app.ministerio.routes import _lideres_do_ministerio

    for lider in _lideres_do_ministerio(escala.ministerio):
        Notificacao(
            usuario_id=lider.id,
            titulo=titulo,
            mensagem=mensagem,
            escala_id=escala.id,
            tipo=tipo,
        ).save()


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

    if request.method == "GET":
        # Predefine horario/horario_fim com o ultimo usado nesse Ministerio --
        # poupa quem cria escalas recorrentes (ex: sempre o mesmo ensaio de
        # quarta) de digitar o mesmo horario toda vez. So um ponto de
        # partida, continua editavel.
        ultima_escala = (
            Escala.objects(ministerio_id=ministerio.id, horario__ne=None)
            .order_by("-criada_em")
            .first()
        )
        if ultima_escala:
            form.horario.data = ultima_escala.horario
            form.horario_fim.data = ultima_escala.horario_fim

    if form.validate_on_submit():
        escala = criar_escala_com_funcoes_padrao(
            ministerio_id=ministerio.id,
            nome=form.nome.data.strip(),
            departamento=form.departamento.data,
            data=form.data.data,
            horario=form.horario.data,
            horario_fim=form.horario_fim.data,
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
        mudou_data_horario = (
            form.data.data != escala.data
            or form.horario.data != escala.horario
            or form.horario_fim.data != escala.horario_fim
        )

        escala.nome = form.nome.data.strip()
        escala.data = form.data.data
        escala.horario = form.horario.data
        escala.horario_fim = form.horario_fim.data
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

        escala.save()

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
            if resultado["whatsapp_enviados"]:
                partes.append(f"{resultado['whatsapp_enviados']} WhatsApp enviado(s)")
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
    formularios_aprovar_troca = {}
    avisos_por_funcao = {}
    diretorio_vazio = False

    diretorio_geral = list(Membro.objects(
        comunidade_id=escala.ministerio.comunidade_id
    ).order_by("nome"))
    # Placeholder em 0 -- "nao sugerir ninguem", nunca um Membro.id real (ver
    # StatusForm.troca_sugestao_membro_id).
    _choices_sugestao = [(0, "Ninguem em especial")] + [(m.id, m.nome) for m in diretorio_geral]

    # So um AVISO (nunca bloqueia) de que a pessoa provavelmente esta
    # indisponivel na data da escala, segundo os ciclos que ela tiver
    # cadastrados (ver CicloDisponibilidade) -- sem data definida na escala
    # nao ha o que comparar, entao fica vazio de proposito.
    avisos_por_membro = {}
    if escala.data:
        for m in diretorio_geral:
            avisos = avisos_disponibilidade(m, escala.data)
            if avisos:
                avisos_por_membro[m.id] = avisos

    def _rotulo_com_aviso(membro):
        avisos = avisos_por_membro.get(membro.id)
        if not avisos:
            return membro.nome
        return f"{membro.nome} (indisponivel: {', '.join(avisos)})"

    if eh_dono:
        # Convidado so le a grade (ver template) -- monta os forms de escrita
        # so pra quem pode escrever, poupa consultas desnecessarias pro convidado.
        diretorio = diretorio_geral
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
                    (m.id, _rotulo_com_aviso(m)) for m in diretorio
                ]
                formularios_membro[funcao.id] = form_membro
            else:
                if funcao.membro_id in avisos_por_membro:
                    avisos_por_funcao[funcao.id] = avisos_por_membro[funcao.membro_id]

                mover_form = MoverForm()
                mover_form.destino_funcao_id.choices = [
                    (f.id, f.nome) for f in destinos_possiveis if f.id != funcao.id
                ]
                formularios_mover[funcao.id] = mover_form
                status_form = StatusForm(status=funcao.status or STATUS_PADRAO)
                status_form.troca_sugestao_membro_id.choices = _choices_sugestao
                formularios_status[funcao.id] = status_form

                if funcao.status == "troca_solicitada":
                    aprovar_form = TrocaAprovarForm(membro_id=funcao.troca_sugestao_membro_id or 0)
                    aprovar_form.membro_id.choices = [(0, "Selecione quem assume")] + [
                        (m.id, m.nome) for m in diretorio
                    ]
                    formularios_aprovar_troca[funcao.id] = aprovar_form
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
                status_form = StatusForm(status=funcao.status or STATUS_PADRAO)
                status_form.troca_sugestao_membro_id.choices = _choices_sugestao
                formularios_status[funcao.id] = status_form

    return render_template(
        "escala/detalhe.html",
        escala=escala,
        eh_dono=eh_dono,
        diretorio_vazio=diretorio_vazio,
        formularios_membro=formularios_membro,
        formularios_mover=formularios_mover,
        formularios_status=formularios_status,
        formularios_editar_funcao=formularios_editar_funcao,
        formularios_aprovar_troca=formularios_aprovar_troca,
        avisos_por_funcao=avisos_por_funcao,
        formulario_nova_funcao=FuncaoForm(),
        formulario_novo_subcabecalho=FuncaoForm(),
        formulario_novo_item_repertorio=ItemRepertorioForm(),
        formulario_ensaio=EnsaioForm(prefix="ensaio"),
        formulario_anexo=_form_anexo(escala),
        formulario_item_banco=_form_item_banco(escala),
        formulario_observacoes=ObservacoesRepertorioForm(observacoes_repertorio=escala.observacoes_repertorio),
        anexos=_anexos_visiveis(escala, eh_dono),
        ensaios=escala.ensaios,
        hoje=_hoje_brasilia(),
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
    nova_funcao.save()

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
    novo_subcabecalho.save()

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
    funcao.save()

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
    Anexo.objects(funcao_id=funcao.id).delete()
    funcao.delete()

    flash(f'Funcao "{nome}" removida de {escala_nome}.', "success")
    return redirect(url_for("escala.detalhe", escala_id=escala_id))


@bp.route("/<int:escala_id>/repertorio/adicionar", methods=["POST"])
@login_required
def adicionar_item_repertorio(escala_id):
    escala = _escala_do_usuario_ou_404(escala_id)
    form = ItemRepertorioForm()

    if not form.validate_on_submit():
        erros = [erro for lista in form.errors.values() for erro in lista]
        flash(erros[0] if erros else "Nao foi possivel adicionar a musica.", "danger")
        return redirect(url_for("escala.detalhe", escala_id=escala.id))

    maior_ordem = max([item.ordem for item in escala.repertorio], default=-1)
    item = ItemRepertorio(
        escala_id=escala.id,
        nome_musica=form.nome_musica.data.strip(),
        tom=(form.tom.data or "").strip() or None,
        link=(form.link.data or "").strip() or None,
        ordem=maior_ordem + 1,
    )
    item.save()

    flash(f'"{item.nome_musica}" adicionada ao repertorio.', "success")
    return redirect(url_for("escala.detalhe", escala_id=escala.id))


@bp.route("/repertorio/<int:item_id>/excluir", methods=["POST"])
@login_required
def excluir_item_repertorio(item_id):
    item = primeiro_ou_404(ItemRepertorio.objects(id=item_id))
    escala = _escala_do_usuario_ou_404(item.escala_id)
    form = AcaoForm()

    if not form.validate_on_submit():
        flash("Acao invalida.", "danger")
        return redirect(url_for("escala.detalhe", escala_id=escala.id))

    nome = item.nome_musica
    item.delete()

    flash(f'"{nome}" removida do repertorio.', "success")
    return redirect(url_for("escala.detalhe", escala_id=escala.id))


@bp.route("/funcao/<int:funcao_id>/adicionar", methods=["POST"])
@login_required
def adicionar_membro(funcao_id):
    funcao = _funcao_do_usuario_ou_404(funcao_id)
    comunidade_id = funcao.escala.ministerio.comunidade_id
    diretorio = list(Membro.objects(comunidade_id=comunidade_id).order_by("nome"))

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

    membro = Membro.objects(id=form.membro_id.data, comunidade_id=comunidade_id).first()
    if membro is None:
        flash("Pessoa invalida para esta comunidade.", "danger")
        return redirect(url_for("escala.detalhe", escala_id=funcao.escala_id))

    avisos_conflito = _avisos_conflito_horario(membro, funcao.escala, funcao_atual_id=funcao.id)

    funcao.membro_id = membro.id
    funcao.status = STATUS_PADRAO
    funcao.notificado_em = None
    funcao.eh_convidado = False
    _fixar_se_gerada_por_rodizio(funcao.escala)
    funcao.save()

    flash(f"{membro.nome} adicionado(a) em {funcao.nome}.", "success")
    for aviso in avisos_conflito:
        flash(aviso, "warning")
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

    usuarios = list(
        User.objects(
            MongoQ(name__icontains=termo) | MongoQ(username__icontains=termo) | MongoQ(email__icontains=termo)
        )
        .order_by("name")
        .limit(8)
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
    usuario = User.objects(id=usuario_id).first() if usuario_id else None
    if usuario is None:
        flash("Selecione um usuario valido na busca.", "danger")
        return redirect(url_for("escala.detalhe", escala_id=funcao.escala_id))

    membro = Membro.objects(comunidade_id=comunidade_id, email=usuario.email).first()
    if membro is None:
        membro = Membro(
            comunidade_id=comunidade_id,
            nome=usuario.name or usuario.username or usuario.email,
            email=usuario.email,
        )
        membro.save()

    avisos_conflito = _avisos_conflito_horario(membro, funcao.escala, funcao_atual_id=funcao.id)

    funcao.membro_id = membro.id
    funcao.status = STATUS_PADRAO
    funcao.notificado_em = None
    funcao.eh_convidado = True
    _fixar_se_gerada_por_rodizio(funcao.escala)
    funcao.save()

    flash(f"{membro.nome} adicionado(a) como convidado(a) em {funcao.nome}.", "success")
    for aviso in avisos_conflito:
        flash(aviso, "warning")
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
    funcao.save()

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
    origem.save()
    destino.save()

    flash(f"{origem.nome} e {destino.nome} atualizados.", "success")
    return redirect(url_for("escala.detalhe", escala_id=escala_id))


def _destino_apos_status(escala_id):
    """Volta pra "Minha escala" quando o status foi alterado de la (campo
    voltar); so aceita esse caminho interno, nunca um endereco externo."""
    voltar = request.form.get("voltar") or ""
    if voltar.startswith("/minha-escala") and "//" not in voltar:
        return redirect(voltar)
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
    funcao_bruta = primeiro_ou_404(Funcao.objects(id=funcao_id))
    eh_proprio_escalado = (
        funcao_bruta.membro_id is not None
        and funcao_bruta.membro.email
        and funcao_bruta.membro.email.lower() == (current_user.email or "").lower()
    )
    funcao = funcao_bruta if eh_proprio_escalado else _funcao_do_usuario_ou_404(funcao_id)
    escala_id = funcao.escala_id

    if funcao.membro_id is None:
        flash("Essa funcao nao tem ninguem escalado.", "danger")
        return _destino_apos_status(escala_id)

    comunidade_id = funcao.escala.ministerio.comunidade_id
    form = StatusForm()
    form.troca_sugestao_membro_id.choices = [(0, "Ninguem em especial")] + [
        (m.id, m.nome)
        for m in Membro.objects(comunidade_id=comunidade_id).order_by("nome")
    ]

    if not form.validate_on_submit():
        flash("Status invalido.", "danger")
        return _destino_apos_status(escala_id)

    status_anterior = funcao.status
    status_novo = form.status.data
    funcao.status = status_novo

    if status_novo == "troca_solicitada":
        funcao.troca_motivo = (form.troca_motivo.data or "").strip() or None
        funcao.troca_sugestao_membro_id = form.troca_sugestao_membro_id.data or None
    else:
        funcao.troca_motivo = None
        funcao.troca_sugestao_membro_id = None

    funcao.save()

    # So notifica lider/admin quando quem mudou foi o PROPRIO escalado (ver
    # _notificar_lideres_do_ministerio) -- se um lider mudou o status de
    # outra pessoa, a mudanca ja e obra dele mesmo.
    if eh_proprio_escalado and status_novo != status_anterior:
        rotulo = STATUS_LABELS.get(status_novo, status_novo)
        titulo = f"{funcao.membro.nome}: {rotulo} em {funcao.nome}"
        mensagem = f"{titulo} ({funcao.escala.nome})."
        if status_novo == "troca_solicitada":
            if funcao.troca_sugestao_membro_id:
                sugestao = Membro.objects(id=funcao.troca_sugestao_membro_id).first()
                if sugestao:
                    mensagem += f" Sugestao de substituto: {sugestao.nome}."
            if funcao.troca_motivo:
                mensagem += f" Motivo: {funcao.troca_motivo}"
        _notificar_lideres_do_ministerio(funcao.escala, titulo, mensagem, tipo=status_novo)

    return _destino_apos_status(escala_id)


@bp.route("/funcao/<int:funcao_id>/troca/aprovar", methods=["POST"])
@login_required
def aprovar_troca(funcao_id):
    """Lider/admin aprova a solicitacao de troca: reatribui a funcao pra
    quem foi escolhido no formulario (pre-preenchido com a sugestao de quem
    pediu, se houver -- ver detalhe() e forms.TrocaAprovarForm)."""
    funcao = _funcao_do_usuario_ou_404(funcao_id)
    escala_id = funcao.escala_id

    if funcao.status != "troca_solicitada":
        flash("Essa funcao nao tem uma troca pendente.", "danger")
        return redirect(url_for("escala.detalhe", escala_id=escala_id))

    comunidade_id = funcao.escala.ministerio.comunidade_id
    diretorio = list(Membro.objects(comunidade_id=comunidade_id).order_by("nome"))

    form = TrocaAprovarForm()
    form.membro_id.choices = [(0, "Selecione quem assume")] + [(m.id, m.nome) for m in diretorio]

    if not form.validate_on_submit() or not form.membro_id.data:
        flash("Selecione quem assume a funcao para aprovar a troca.", "danger")
        return redirect(url_for("escala.detalhe", escala_id=escala_id))

    novo_membro = Membro.objects(id=form.membro_id.data, comunidade_id=comunidade_id).first()
    if novo_membro is None:
        flash("Pessoa invalida para esta comunidade.", "danger")
        return redirect(url_for("escala.detalhe", escala_id=escala_id))

    membro_antigo_email = funcao.membro.email if funcao.membro else None
    nome_funcao, nome_escala, escala_id_notif = funcao.nome, funcao.escala.nome, funcao.escala_id

    funcao.membro_id = novo_membro.id
    funcao.status = STATUS_PADRAO
    funcao.notificado_em = None
    funcao.eh_convidado = False
    funcao.troca_motivo = None
    funcao.troca_sugestao_membro_id = None
    _fixar_se_gerada_por_rodizio(funcao.escala)
    funcao.save()

    if membro_antigo_email:
        usuario_antigo = User.objects(email=membro_antigo_email).first()
        if usuario_antigo:
            Notificacao(
                usuario_id=usuario_antigo.id,
                titulo=f"Troca aprovada: {nome_funcao}",
                mensagem=(
                    f"Sua troca em {nome_funcao} ({nome_escala}) foi aprovada. "
                    f"{novo_membro.nome} assume a partir de agora."
                ),
                escala_id=escala_id_notif,
                tipo="troca_aprovada",
            ).save()

    flash(f"Troca aprovada: {novo_membro.nome} assume {nome_funcao}.", "success")
    return redirect(url_for("escala.detalhe", escala_id=escala_id))


@bp.route("/funcao/<int:funcao_id>/troca/recusar", methods=["POST"])
@login_required
def recusar_troca(funcao_id):
    funcao = _funcao_do_usuario_ou_404(funcao_id)
    escala_id = funcao.escala_id

    if funcao.status != "troca_solicitada":
        flash("Essa funcao nao tem uma troca pendente.", "danger")
        return redirect(url_for("escala.detalhe", escala_id=escala_id))

    form = AcaoForm()
    if not form.validate_on_submit():
        flash("Acao invalida.", "danger")
        return redirect(url_for("escala.detalhe", escala_id=escala_id))

    membro_email = funcao.membro.email if funcao.membro else None
    nome_funcao, nome_escala, escala_id_notif = funcao.nome, funcao.escala.nome, funcao.escala_id

    funcao.status = STATUS_PADRAO
    funcao.troca_motivo = None
    funcao.troca_sugestao_membro_id = None
    funcao.save()

    if membro_email:
        usuario = User.objects(email=membro_email).first()
        if usuario:
            Notificacao(
                usuario_id=usuario.id,
                titulo=f"Troca recusada: {nome_funcao}",
                mensagem=f"Sua solicitacao de troca em {nome_funcao} ({nome_escala}) foi recusada.",
                escala_id=escala_id_notif,
                tipo="troca_recusada",
            ).save()

    flash("Solicitacao de troca recusada.", "success")
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
    resultado_vazio = {"email_ok": False, "sms_ok": False, "whatsapp_ok": False}
    resultados = {t["funcao_id"]: dict(resultado_vazio) for t in tarefas}
    if not tarefas:
        return resultados

    app_obj = current_app._get_current_object()

    def _enviar_para_uma_tarefa(tarefa):
        resultado = dict(resultado_vazio)
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
                try:
                    enviar_whatsapp_template(
                        destinatario=tarefa["telefone"],
                        nome_template=tarefa["wa_template"],
                        parametros=tarefa["wa_parametros"],
                    )
                    resultado["whatsapp_ok"] = True
                except WhatsappNaoEnviadoError:
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
    data_texto = escala.data.strftime("%d/%m/%Y") if escala.data else "data a definir"

    tarefas = [
        {
            "funcao_id": funcao.id,
            "email": funcao.membro.email,
            "telefone": funcao.membro.telefone,
            "mensagem": mensagem_para(escala, funcao, funcao.membro),
            "assunto": f"Voce foi escalado(a): {funcao.nome} - {escala.nome}",
            "wa_template": "pibachurch_escalado",
            "wa_parametros": [funcao.membro.nome, funcao.nome, escala.nome, data_texto],
        }
        for funcao in escalados
    ]
    resultados_por_funcao = _disparar_notificacoes_em_paralelo(tarefas)

    notificacoes_app = 0
    email_enviados = email_falhas = 0
    sms_enviados = sms_falhas = 0
    whatsapp_enviados = whatsapp_falhas = 0
    sem_contato = 0

    for funcao in escalados:
        membro = funcao.membro
        resultado = resultados_por_funcao[funcao.id]
        notificou_algum_canal = False

        if membro.email:
            # Se a pessoa tem conta no site, tambem aparece no sino dela ao logar --
            # isso e um EXTRA, nao substitui o e-mail.
            usuario_vinculado = User.objects(email=membro.email).first()
            if usuario_vinculado:
                Notificacao(
                    usuario_id=usuario_vinculado.id,
                    titulo=f"Voce foi escalado(a) para {funcao.nome}",
                    mensagem=f"{escala.nome} ({escala.departamento}) - {funcao.nome}.",
                    escala_id=escala.id,
                    tipo="escalado",
                ).save()
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

            if resultado["whatsapp_ok"]:
                whatsapp_enviados += 1
                notificou_algum_canal = True
            else:
                whatsapp_falhas += 1

        if not membro.email and not membro.telefone:
            sem_contato += 1

        if notificou_algum_canal:
            marcar_notificado(funcao)
            funcao.save()

    return {
        "escalados": len(escalados),
        "notificacoes_app": notificacoes_app,
        "email_enviados": email_enviados,
        "email_falhas": email_falhas,
        "sms_enviados": sms_enviados,
        "sms_falhas": sms_falhas,
        "whatsapp_enviados": whatsapp_enviados,
        "whatsapp_falhas": whatsapp_falhas,
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
    whatsapp_enviados = whatsapp_falhas = 0

    for funcao in escalados:
        membro = funcao.membro

        if membro.email:
            usuario_vinculado = User.objects(email=membro.email).first()
            if usuario_vinculado:
                Notificacao(
                    usuario_id=usuario_vinculado.id,
                    titulo=f"Mudanca de data: {escala.nome}",
                    mensagem=mensagem,
                    escala_id=escala.id,
                    tipo="alteracao",
                ).save()
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

            try:
                enviar_whatsapp_template(
                    destinatario=membro.telefone,
                    nome_template="pibachurch_alteracao",
                    parametros=[
                        escala.nome,
                        f"{data_antiga_texto}{horario_antigo_texto}",
                        f"{data_nova_texto}{horario_novo_texto}",
                    ],
                )
                whatsapp_enviados += 1
            except WhatsappNaoEnviadoError:
                whatsapp_falhas += 1

    return {
        "notificacoes_app": notificacoes_app,
        "email_enviados": email_enviados,
        "email_falhas": email_falhas,
        "sms_enviados": sms_enviados,
        "sms_falhas": sms_falhas,
        "whatsapp_enviados": whatsapp_enviados,
        "whatsapp_falhas": whatsapp_falhas,
    }


def enviar_notificacao_de_cancelamento(escala):
    """Avisa, um por um, quem ja estava escalado que o evento foi cancelado --
    chamada por cancelar_escala logo apos marcar Escala.cancelada=True. Mesmo
    padrao/canais de enviar_notificacao_de_alteracao (email/SMS/sino),
    so que com a mensagem e o tipo de notificacao diferentes."""
    escalados = [f for f in escala.funcoes if f.membro_id is not None]

    data_texto = escala.data.strftime("%d/%m/%Y") if escala.data else "sem data definida"
    mensagem = f'A escala "{escala.nome}" ({data_texto}) foi cancelada. Voce nao precisa comparecer.'

    notificacoes_app = 0
    email_enviados = email_falhas = 0
    sms_enviados = sms_falhas = 0
    whatsapp_enviados = whatsapp_falhas = 0

    for funcao in escalados:
        membro = funcao.membro

        if membro.email:
            usuario_vinculado = User.objects(email=membro.email).first()
            if usuario_vinculado:
                Notificacao(
                    usuario_id=usuario_vinculado.id,
                    titulo=f"Escala cancelada: {escala.nome}",
                    mensagem=mensagem,
                    escala_id=escala.id,
                    tipo="cancelamento",
                ).save()
                notificacoes_app += 1

            try:
                enviar_email(
                    destinatario=membro.email,
                    assunto=f"Escala cancelada: {escala.nome}",
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

            try:
                enviar_whatsapp_template(
                    destinatario=membro.telefone,
                    nome_template="pibachurch_cancelamento",
                    parametros=[escala.nome, data_texto],
                )
                whatsapp_enviados += 1
            except WhatsappNaoEnviadoError:
                whatsapp_falhas += 1

    return {
        "notificacoes_app": notificacoes_app,
        "email_enviados": email_enviados,
        "email_falhas": email_falhas,
        "sms_enviados": sms_enviados,
        "sms_falhas": sms_falhas,
        "whatsapp_enviados": whatsapp_enviados,
        "whatsapp_falhas": whatsapp_falhas,
    }


@bp.route("/<int:escala_id>/cancelar", methods=["POST"])
@login_required
def cancelar_escala(escala_id):
    """Diferente de excluir_escala (abaixo): o evento continua existindo,
    so marcado como cancelado -- fica no historico/calendario com um
    aviso, em vez de sumir. Trava plantao_fixado igual uma edicao manual
    (_fixar_se_gerada_por_rodizio) pra o sync do rodizio nao "descancelar"
    essa ocorrencia especifica no proximo tick."""
    escala = _escala_do_usuario_ou_404(escala_id)
    form = AcaoForm()

    if not form.validate_on_submit():
        flash("Acao invalida.", "danger")
        return redirect(url_for("escala.detalhe", escala_id=escala.id))

    if escala.cancelada:
        flash(f'"{escala.nome}" ja esta cancelada.', "danger")
        return redirect(url_for("escala.detalhe", escala_id=escala.id))

    escala.cancelada = True
    escala.cancelada_em = datetime.now(timezone.utc)
    _fixar_se_gerada_por_rodizio(escala)
    escala.save()

    resultado = enviar_notificacao_de_cancelamento(escala)
    partes = []
    if resultado["notificacoes_app"]:
        partes.append(f"{resultado['notificacoes_app']} notificacao(oes) no app")
    if resultado["email_enviados"]:
        partes.append(f"{resultado['email_enviados']} e-mail(s) enviado(s)")
    if resultado["sms_enviados"]:
        partes.append(f"{resultado['sms_enviados']} SMS enviado(s)")
    if resultado["whatsapp_enviados"]:
        partes.append(f"{resultado['whatsapp_enviados']} WhatsApp enviado(s)")
    aviso = f" Equipe avisada: {', '.join(partes)}." if partes else ""

    flash(f'Escala "{escala.nome}" cancelada.{aviso}', "success")
    return redirect(url_for("escala.detalhe", escala_id=escala.id))


@bp.route("/<int:escala_id>/reabrir", methods=["POST"])
@login_required
def reabrir_escala(escala_id):
    """Desfaz um cancelamento feito por engano -- volta ao normal, sem
    notificar ninguem automaticamente (diferente de cancelar_escala): quem
    ja tinha sido avisado do cancelamento precisa ser reconvidado/confirmado
    na mao, o lider decide como."""
    escala = _escala_do_usuario_ou_404(escala_id)
    form = AcaoForm()

    if not form.validate_on_submit():
        flash("Acao invalida.", "danger")
        return redirect(url_for("escala.detalhe", escala_id=escala.id))

    escala.cancelada = False
    escala.cancelada_em = None
    escala.save()

    flash(f'Escala "{escala.nome}" reaberta.', "success")
    return redirect(url_for("escala.detalhe", escala_id=escala.id))


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
    if resultado["whatsapp_enviados"]:
        partes.append(f"{resultado['whatsapp_enviados']} WhatsApp enviado(s)")
    if resultado["email_falhas"]:
        partes.append(f"{resultado['email_falhas']} e-mail(s) falharam")
    if resultado["sms_falhas"]:
        partes.append(f"{resultado['sms_falhas']} SMS falharam")
    if resultado["whatsapp_falhas"]:
        partes.append(f"{resultado['whatsapp_falhas']} WhatsApp falharam")
    if resultado["sem_contato"]:
        partes.append(f"{resultado['sem_contato']} sem e-mail/telefone cadastrado")

    houve_sucesso = bool(
        resultado["notificacoes_app"] or resultado["email_enviados"]
        or resultado["sms_enviados"] or resultado["whatsapp_enviados"]
    )
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
    delete_cascade(escala)

    flash(f'Escala "{nome}" excluida.', "success")
    return redirect(url_for("ministerio.detalhe", ministerio_id=ministerio_id))


# --- Ensaios (dias de ensaio de uma Escala, ver models.Ensaio) -------------

def _hoje_brasilia():
    # Mesmo offset fixo de main.routes (Brasilia sem horario de verao).
    return (datetime.now(timezone.utc) - timedelta(hours=3)).date()


def _ensaio_do_usuario_ou_404(ensaio_id):
    ensaio = primeiro_ou_404(Ensaio.objects(id=ensaio_id))
    escala = _escala_do_usuario_ou_404(ensaio.escala_id)
    return ensaio, escala


def _voltar_pros_ensaios(escala):
    return redirect(url_for("escala.detalhe", escala_id=escala.id) + "#ensaios")


def enviar_aviso_de_ensaio_cancelado(escala, ensaio):
    """Avisa quem esta escalado que UM ensaio foi cancelado (a escala segue
    de pe). Sino + e-mail + SMS; sem WhatsApp porque la so ha template
    aprovado pro cancelamento da escala inteira. Uma vez por pessoa, mesmo
    que ela esteja em mais de uma funcao."""
    membros = {}
    for funcao in escala.funcoes:
        if funcao.membro_id is not None and funcao.membro_id not in membros:
            membros[funcao.membro_id] = funcao.membro

    mensagem = (
        f'O ensaio de "{escala.nome}" em {ensaio.descricao_data} foi cancelado. '
        "Voce nao precisa comparecer nesse dia."
    )
    resultado = {"notificacoes_app": 0, "email_enviados": 0, "sms_enviados": 0}
    for membro in membros.values():
        if membro is None:
            continue
        if membro.email:
            usuario = User.objects(email=membro.email).first()
            if usuario:
                Notificacao(
                    usuario_id=usuario.id,
                    titulo=f"Ensaio cancelado: {escala.nome}",
                    mensagem=mensagem,
                    escala_id=escala.id,
                    tipo="ensaio_cancelado",
                ).save()
                resultado["notificacoes_app"] += 1
            try:
                enviar_email(destinatario=membro.email, assunto=f"Ensaio cancelado: {escala.nome}", corpo=mensagem)
                resultado["email_enviados"] += 1
            except EmailNaoEnviadoError:
                pass
        if membro.telefone:
            try:
                enviar_sms(destinatario=membro.telefone, corpo=mensagem)
                resultado["sms_enviados"] += 1
            except SmsNaoEnviadoError:
                pass
    return resultado


def _cancelar_ensaio(ensaio, escala):
    if ensaio.cancelado:
        flash("Esse ensaio ja esta cancelado.", "danger")
        return
    ensaio.cancelado = True
    ensaio.cancelado_em = datetime.now(timezone.utc)
    ensaio.save()

    resultado = enviar_aviso_de_ensaio_cancelado(escala, ensaio)
    partes = []
    if resultado["notificacoes_app"]:
        partes.append(f"{resultado['notificacoes_app']} no app")
    if resultado["email_enviados"]:
        partes.append(f"{resultado['email_enviados']} por e-mail")
    if resultado["sms_enviados"]:
        partes.append(f"{resultado['sms_enviados']} por SMS")
    aviso = f" Equipe avisada: {', '.join(partes)}." if partes else ""
    flash(f"Ensaio de {ensaio.descricao_data} cancelado.{aviso}", "success")


@bp.route("/<int:escala_id>/ensaios", methods=["POST"])
@login_required
def adicionar_ensaio(escala_id):
    escala = _escala_do_usuario_ou_404(escala_id)
    form = EnsaioForm(prefix="ensaio")
    if not form.validate_on_submit():
        erros = [erro for lista in form.errors.values() for erro in lista]
        flash(erros[0] if erros else "Nao foi possivel adicionar o ensaio.", "danger")
        return _voltar_pros_ensaios(escala)
    if form.horario.data and form.horario_fim.data and form.horario_fim.data <= form.horario.data:
        flash("O horario de fim do ensaio precisa ser depois do inicio.", "danger")
        return _voltar_pros_ensaios(escala)

    Ensaio(
        escala_id=escala.id,
        data=form.data.data,
        horario=form.horario.data,
        horario_fim=form.horario_fim.data,
        local=(form.local.data or "").strip() or None,
    ).save()
    flash("Ensaio adicionado.", "success")
    return _voltar_pros_ensaios(escala)


@bp.route("/ensaio/<int:ensaio_id>/cancelar", methods=["POST"])
@login_required
def cancelar_ensaio(ensaio_id):
    ensaio, escala = _ensaio_do_usuario_ou_404(ensaio_id)
    if not AcaoForm().validate_on_submit():
        flash("Acao invalida.", "danger")
        return _voltar_pros_ensaios(escala)
    _cancelar_ensaio(ensaio, escala)
    return _voltar_pros_ensaios(escala)


@bp.route("/<int:escala_id>/ensaios/cancelar", methods=["POST"])
@login_required
def cancelar_ensaio_escolhido(escala_id):
    """Mesma acao de cancelar_ensaio, a partir do seletor da secao "Cancelar"
    no fim da tela da escala (escolhe qual ensaio num <select>)."""
    escala = _escala_do_usuario_ou_404(escala_id)
    if not AcaoForm().validate_on_submit():
        flash("Acao invalida.", "danger")
        return _voltar_pros_ensaios(escala)
    try:
        ensaio_id = int(request.form.get("ensaio_id", ""))
    except ValueError:
        ensaio_id = None
    ensaio = Ensaio.objects(id=ensaio_id, escala_id=escala.id).first() if ensaio_id else None
    if ensaio is None:
        flash("Escolha qual ensaio cancelar.", "danger")
        return _voltar_pros_ensaios(escala)
    _cancelar_ensaio(ensaio, escala)
    return _voltar_pros_ensaios(escala)


@bp.route("/ensaio/<int:ensaio_id>/reabrir", methods=["POST"])
@login_required
def reabrir_ensaio(ensaio_id):
    ensaio, escala = _ensaio_do_usuario_ou_404(ensaio_id)
    if not AcaoForm().validate_on_submit():
        flash("Acao invalida.", "danger")
        return _voltar_pros_ensaios(escala)
    ensaio.cancelado = False
    ensaio.cancelado_em = None
    ensaio.save()
    flash(f"Ensaio de {ensaio.descricao_data} reaberto.", "success")
    return _voltar_pros_ensaios(escala)


@bp.route("/ensaio/<int:ensaio_id>/excluir", methods=["POST"])
@login_required
def excluir_ensaio(ensaio_id):
    ensaio, escala = _ensaio_do_usuario_ou_404(ensaio_id)
    if not AcaoForm().validate_on_submit():
        flash("Acao invalida.", "danger")
        return _voltar_pros_ensaios(escala)
    descricao = ensaio.descricao_data
    ensaio.delete()
    flash(f"Ensaio de {descricao} removido.", "success")
    return _voltar_pros_ensaios(escala)


# --- Materiais (anexos) da escala, ver models.Anexo ------------------------

def _funcoes_da_conta(escala):
    email = (current_user.email or "").lower()
    return [
        f for f in escala.funcoes
        if f.membro_id and f.membro and (f.membro.email or "").lower() == email
    ]


def _anexos_visiveis(escala, pode_gerenciar):
    """Lider ve todos; os demais veem os da equipe toda + os das proprias funcoes."""
    anexos = list(Anexo.objects(escala_id=escala.id).exclude("conteudo").order_by("criado_em"))
    if pode_gerenciar:
        return anexos
    minhas = {f.id for f in _funcoes_da_conta(escala)}
    return [a for a in anexos if a.funcao_id is None or a.funcao_id in minhas]


def _form_anexo(escala):
    form = AnexoForm(prefix="anexo")
    form.funcao_id.choices = [(0, "Toda a equipe")] + [
        (f.id, f.nome) for f in escala.funcoes if f.tipo != TIPO_SUBCABECALHO
    ]
    return form


def _voltar_pros_materiais(escala):
    return redirect(url_for("escala.detalhe", escala_id=escala.id) + "#materiais")


@bp.route("/<int:escala_id>/anexos", methods=["POST"])
@login_required
def adicionar_anexo(escala_id):
    # Limite so desta rota (o resto do site segue com 2 MB): ler o corpo
    # acima disso cai no handler de 413 (ver app/errors.py).
    request.max_content_length = TAMANHO_MAXIMO_ANEXO + 512 * 1024
    escala = _escala_do_usuario_ou_404(escala_id)
    form = _form_anexo(escala)
    if not form.validate_on_submit():
        erros = [erro for lista in form.errors.values() for erro in lista]
        flash(erros[0] if erros else "Nao foi possivel anexar o arquivo.", "danger")
        return _voltar_pros_materiais(escala)

    arquivo = form.arquivo.data
    nome = os.path.basename((arquivo.filename or "arquivo").replace("\\", "/"))[:200]
    extensao = nome.rsplit(".", 1)[-1].lower() if "." in nome else ""
    conteudo = arquivo.read()
    Anexo(
        escala_id=escala.id,
        funcao_id=form.funcao_id.data or None,
        nome_arquivo=nome,
        tipo=TIPOS_ANEXO[extensao],
        tamanho=len(conteudo),
        conteudo=conteudo,
        enviado_por_id=current_user.id,
    ).save()
    flash(f'"{nome}" anexado.', "success")
    return _voltar_pros_materiais(escala)


@bp.route("/anexo/<int:anexo_id>")
@login_required
def baixar_anexo(anexo_id):
    """Quem pode ver a escala, ou quem esta escalado nela, abre o arquivo."""
    anexo = primeiro_ou_404(Anexo.objects(id=anexo_id))
    _escala_da_equipe_ou_404(anexo.escala_id)
    resposta = send_file(
        io.BytesIO(anexo.conteudo),
        mimetype=anexo.tipo,
        as_attachment=not anexo.abre_no_navegador,
        download_name=anexo.nome_arquivo,
    )
    resposta.headers["X-Content-Type-Options"] = "nosniff"
    return resposta


@bp.route("/anexo/<int:anexo_id>/excluir", methods=["POST"])
@login_required
def excluir_anexo(anexo_id):
    anexo = primeiro_ou_404(Anexo.objects(id=anexo_id).exclude("conteudo"))
    escala = _escala_do_usuario_ou_404(anexo.escala_id)
    if not AcaoForm().validate_on_submit():
        flash("Acao invalida.", "danger")
        return _voltar_pros_materiais(escala)
    nome = anexo.nome_arquivo
    Anexo.objects(id=anexo.id).delete()
    flash(f'"{nome}" removido.', "success")
    return _voltar_pros_materiais(escala)


def _escala_da_equipe_ou_404(escala_id):
    """Leitura pra quem pode ver a escala OU esta escalado nela (Membro com o
    e-mail da conta) -- materiais e folhas do repertorio."""
    escala = primeiro_ou_404(Escala.objects(id=escala_id))
    if not _funcoes_da_conta(escala):
        _escala_visivel_ou_404(escala.id)
    return escala


# --- Repertorio da escala puxando do banco de musicas ----------------------

def _form_item_banco(escala):
    form = ItemDoBancoForm(prefix="banco")
    form.musica_id.choices = [
        (m.id, f"{m.nome}" + (f" - {m.artista}" if m.artista else ""))
        for m in Musica.objects(ministerio_id=escala.ministerio_id).only("id", "nome", "artista").order_by("nome")
    ]
    return form


@bp.route("/<int:escala_id>/repertorio/banco", methods=["POST"])
@login_required
def adicionar_musica_do_banco(escala_id):
    escala = _escala_do_usuario_ou_404(escala_id)
    form = _form_item_banco(escala)
    if not form.validate_on_submit():
        erros = [erro for lista in form.errors.values() for erro in lista]
        flash(erros[0] if erros else "Escolha uma musica do repertorio.", "danger")
        return redirect(url_for("escala.detalhe", escala_id=escala.id) + "#repertorio")
    musica = Musica.objects(id=form.musica_id.data, ministerio_id=escala.ministerio_id).first()
    if musica is None:
        flash("Musica nao encontrada no repertorio deste ministerio.", "danger")
        return redirect(url_for("escala.detalhe", escala_id=escala.id) + "#repertorio")
    maior_ordem = max([item.ordem for item in escala.repertorio], default=-1)
    ItemRepertorio(
        escala_id=escala.id,
        musica_id=musica.id,
        nome_musica=musica.nome,
        tom=(form.tom.data or "").strip() or musica.tom,
        link=musica.link,
        momento=(form.momento.data or "").strip() or None,
        ordem=maior_ordem + 1,
    ).save()
    flash(f'"{musica.nome}" adicionada ao repertorio.', "success")
    return redirect(url_for("escala.detalhe", escala_id=escala.id) + "#repertorio")


@bp.route("/<int:escala_id>/repertorio/observacoes", methods=["POST"])
@login_required
def salvar_observacoes_repertorio(escala_id):
    escala = _escala_do_usuario_ou_404(escala_id)
    form = ObservacoesRepertorioForm()
    if form.validate_on_submit():
        escala.observacoes_repertorio = (form.observacoes_repertorio.data or "").strip() or None
        escala.save()
        flash("Observacoes do repertorio salvas.", "success")
    else:
        flash("Nao foi possivel salvar as observacoes.", "danger")
    return redirect(url_for("escala.detalhe", escala_id=escala.id) + "#repertorio")


@bp.route("/<int:escala_id>/repertorio/<any(projecao, cifras):tipo>")
@login_required
def folha_repertorio(escala_id, tipo):
    """Folha pronta pra imprimir/salvar em PDF, montada do banco de musicas:
    "projecao" = letras em blocos, sem cifra (equipe de midia/projecao);
    "cifras" = versao do louvor, com acordes (quem toca/canta)."""
    escala = _escala_da_equipe_ou_404(escala_id)
    itens = []
    for item in escala.repertorio:
        musica = item.musica
        itens.append({
            "item": item,
            "musica": musica,
            "tom": item.tom or (musica.tom if musica else None),
            "blocos": blocos_da_letra(musica.letra_projecao) if musica else [],
            "cifra": musica.cifra_louvor if musica else None,
        })
    return render_template(
        "escala/folha_repertorio.html",
        escala=escala,
        tipo=tipo,
        itens=itens,
    )
