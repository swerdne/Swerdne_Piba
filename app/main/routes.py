"""Controller (C do MVC): rotas do modulo main."""
import re
import time
from datetime import datetime, timedelta, timezone

from flask import render_template, redirect, url_for, flash, request, jsonify, current_app, abort, make_response
from flask_login import login_required, current_user

from app.extensions import limiter
from app.main import bp
from app.main.forms import FotoPerfilForm, TemaForm, AcaoForm, TrocarSenhaForm, NomeForm, PrivacidadeForm
from app.main.themes import THEMES, obter_tema
from app.notificacoes import Notificacao
from app.db_utils import por_requisicao, precarregar
from app.imagens import ImagemArmazenada, salvar_imagem, remover_imagem
from app.auth.routes import _notificar_senha_alterada
from app.comunidade.models import Comunidade, UsuarioComunidade
from app.ministerio.models import Ministerio
from app.escala.models import Membro, Escala, Funcao, Ensaio, Anexo, PresencaEnsaio, STATUS_LABELS, STATUS_CORES, eh_funcao_de_projecao
from app.escala.forms import StatusForm
from app.escala.checkin import checkin_ligado, local_do_checkin, situacao_do_dia, situacao_do_ensaio, status_sem_presente


# Icone por tipo de notificacao no sino do Dashboard -- fallback pra
# notificacoes antigas (tipo=None, de antes desse campo existir).
_ICONE_POR_TIPO = {
    "escalado": "fa-user-plus",
    "alteracao": "fa-clock-rotate-left",
    "confirmado": "fa-circle-check",
    "presente": "fa-clipboard-check",
    "nao_notificado": "fa-circle-question",
    "troca_solicitada": "fa-rotate",
    "troca_aprovada": "fa-check-double",
    "troca_recusada": "fa-circle-xmark",
    "faltas_seguidas": "fa-user-clock",
    "cancelamento": "fa-ban",
    "ensaio_cancelado": "fa-calendar-xmark",
    "novo_membro": "fa-user-plus",
    "adicionado_grupo": "fa-people-group",
    "repertorio_compartilhado": "fa-folder-open",
    "musica_aprovada": "fa-star",
}
_ICONE_PADRAO = "fa-bell"


def _agrupar_notificacoes(notificacoes):
    """Agrupa notificacoes (ja ordenadas por mais recente primeiro) por
    Escala, preservando a ordem geral de recencia -- a posicao de cada grupo
    e ditada pela notificacao mais recente dele (a 1a do grupo que aparece
    na lista). Notificacoes sem escala_id (antigas, de antes desse campo
    existir, ou algo geral no futuro) formam grupo de 1 item cada, nunca se
    misturam entre si nem com uma Escala."""
    precarregar(notificacoes, "escala", "escala_id", Escala)
    grupos_por_chave = {}
    ordem = []
    for n in notificacoes:
        chave = ("escala", n.escala_id) if n.escala_id else ("solo", n.id)
        if chave not in grupos_por_chave:
            grupos_por_chave[chave] = {"escala": n.escala, "itens": []}
            ordem.append(chave)
        grupos_por_chave[chave]["itens"].append(n)
    return [grupos_por_chave[chave] for chave in ordem]


_MESES = [
    "janeiro", "fevereiro", "marco", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
]

# Brasilia nao tem horario de verao desde 2019 -- offset fixo evita depender
# do pacote tzdata (ausente no Windows por padrao) so pra uma saudacao.
_OFFSET_BRASILIA = timedelta(hours=-3)


def _agora_brasilia():
    return datetime.now(timezone.utc) + _OFFSET_BRASILIA


def _saudacao(hora):
    if 5 <= hora < 12:
        return "Bom dia"
    if 12 <= hora < 18:
        return "Boa tarde"
    return "Boa noite"


def _proxima_escala_do_usuario(usuario, hoje):
    """Proxima Escala (nao cancelada, de hoje em diante) em que alguma Funcao
    esta atribuida a um Membro com o e-mail da conta -- mesmo vinculo
    conta<->diretorio usado em comunidade.routes.index."""
    funcoes = _funcoes_da_conta(usuario)
    if not funcoes:
        return None, None
    funcao_por_escala = {f.escala_id: f.nome for f in funcoes}
    escala = (
        Escala.objects(id__in=list(funcao_por_escala), data__gte=hoje, cancelada__ne=True)
        .order_by("data", "horario")
        .first()
    )
    if escala is None:
        return None, None
    return escala, funcao_por_escala[escala.id]



def _funcoes_da_conta(usuario):
    """Funcoes (escala_id, nome) em que a conta esta escalada -- uma
    consulta por requisicao, usada por varias secoes do Inicio."""
    ids_membro = Membro.ids_da_conta(usuario.email)
    if not ids_membro:
        return []
    return por_requisicao(("funcoes_da_conta", usuario.id),
                          lambda: list(Funcao.objects(membro_id__in=ids_membro).only("escala_id", "nome")))


def _ids_escalas_do_usuario(usuario):
    return list({f.escala_id for f in _funcoes_da_conta(usuario)})


def _agenda_do_usuario(usuario, hoje, dias=30, limite=6):
    """Proximos ensaios (inclusive os cancelados, pra avisar) e escalas
    canceladas das escalas em que a conta esta escalada, nos proximos
    `dias` -- a secao "Ensaios e avisos" da tela Inicio."""
    ids_escalas = _ids_escalas_do_usuario(usuario)
    if not ids_escalas:
        return []
    ate = hoje + timedelta(days=dias)
    ensaios = list(
        Ensaio.objects(escala_id__in=ids_escalas, data__gte=hoje, data__lte=ate).order_by("data", "horario")
    )
    escalas = {
        e.id: e for e in Escala.objects(id__in=list({x.escala_id for x in ensaios}))
    } if ensaios else {}
    itens = []
    for ensaio in ensaios:
        escala = escalas.get(ensaio.escala_id)
        if escala is None or escala.cancelada:
            continue
        detalhe = ensaio.descricao_data + (f" · {ensaio.local}" if ensaio.local else "")
        itens.append({
            "data": ensaio.data,
            "ordem": ensaio.horario,
            "titulo": f"Ensaio · {escala.nome}",
            "detalhe": detalhe,
            "url": url_for("escala.detalhe", escala_id=escala.id) + "#ensaios",
            "cancelado": ensaio.cancelado,
            "rotulo_cancelado": "Cancelado",
        })
    for escala in Escala.objects(id__in=ids_escalas, cancelada=True, data__gte=hoje, data__lte=ate):
        itens.append({
            "data": escala.data,
            "ordem": escala.horario,
            "titulo": escala.nome,
            "detalhe": f"{escala.data.strftime('%d/%m')} · {escala.departamento}",
            "url": url_for("escala.detalhe", escala_id=escala.id),
            "cancelado": True,
            "rotulo_cancelado": "Cancelada",
        })
    itens.sort(key=lambda i: (i["data"], i["ordem"] or datetime.min.time()))
    return itens[:limite]

def _comunidades_do_usuario(usuario):
    """Mesma regra de comunidade.routes.index (admin x participa), achatada
    numa lista so pro resumo do Dashboard."""
    if usuario.eh_super_admin:
        donas = list(Comunidade.objects.order_by("nome"))
    else:
        ids_admin = [
            row.comunidade_id for row in
            UsuarioComunidade.objects(usuario_id=usuario.id, papel="admin")
        ]
        donas = list(Comunidade.objects(id__in=ids_admin).order_by("nome")) if ids_admin else []

    ids_dono = {c.id for c in donas}
    ids_membro = set(Membro.da_conta(usuario.email).distinct("comunidade_id"))
    ids_membro |= {
        row.comunidade_id for row in
        UsuarioComunidade.objects(usuario_id=usuario.id, papel="membro")
    }
    ids_membro -= ids_dono
    participa = list(Comunidade.objects(id__in=list(ids_membro)).order_by("nome")) if ids_membro else []

    qtd_ministerios = {}
    if donas:
        for m in Ministerio.objects(comunidade_id__in=list(ids_dono)).only("comunidade_id"):
            qtd_ministerios[m.comunidade_id] = qtd_ministerios.get(m.comunidade_id, 0) + 1

    itens = []
    for c in donas:
        qtd = qtd_ministerios.get(c.id, 0)
        itens.append({
            "comunidade": c,
            "subtitulo": f"{qtd} ministerio{'s' if qtd != 1 else ''}",
            "url": url_for("comunidade.detalhe", comunidade_id=c.id),
        })
    for c in participa:
        itens.append({
            "comunidade": c,
            "subtitulo": "Membro",
            "url": url_for("comunidade.escalados", comunidade_id=c.id),
        })
    return itens


@bp.route("/")
def index():
    return redirect(url_for("main.dashboard"))


@bp.route("/service-worker.js")
def service_worker():
    """Serve o arquivo de static/js/ na raiz do site -- o escopo padrao de um
    service worker e o diretorio de onde ele e servido, entao precisa estar
    em / (nao em /static/js/) pra conseguir controlar paginas como /dashboard
    e /comunidade/<id> (exigido pro Chrome considerar o PWA instalavel)."""
    return current_app.send_static_file("js/service-worker.js")


@bp.route("/local/buscar")
@login_required
@limiter.limit("20 per minute")
def buscar_local():
    """Busca de endereco da tela "Local do check-in" (JSON). Feita aqui no
    servidor (nao direto do navegador) pra identificar o app no
    OpenStreetMap, como a politica de uso deles pede."""
    from app.escala.local_checkin import buscar_endereco

    resultados = buscar_endereco(request.args.get("q"))
    if resultados is None:
        return jsonify({"ok": False, "mensagem": "A busca de endereços não respondeu. Tente de novo ou use a sua localização."}), 502
    return jsonify({"ok": True, "resultados": resultados})


# --- Paginas publicas: privacidade, termos e exclusao de dados -----------------
# Sem login (a Meta exige esses links no app do WhatsApp, e robos de revisao
# abrem sem conta). Texto em templates/main/legal/; contato = EMAIL_CONTATO.
_PAGINAS_LEGAIS = {
    "privacidade": "Política de Privacidade",
    "termos": "Termos de Uso",
    "exclusao_de_dados": "Exclusão de dados",
}
_LEGAL_ATUALIZADO_EM = "3 de outubro de 2026"


def _pagina_legal(secao):
    return render_template("main/legal.html", secao=secao, titulo=_PAGINAS_LEGAIS[secao],
                           atualizado_em=_LEGAL_ATUALIZADO_EM)


@bp.route("/privacidade")
def privacidade():
    return _pagina_legal("privacidade")


@bp.route("/termos")
def termos():
    return _pagina_legal("termos")


@bp.route("/exclusao-de-dados")
def exclusao_de_dados():
    return _pagina_legal("exclusao_de_dados")


@bp.route("/imagem/<imagem_id>")
def imagem(imagem_id):
    """Serve uma imagem enviada (ver app/imagens.py). O id e um uuid4
    aleatorio e nunca reaproveitado -- da pra cachear pra sempre."""
    registro = ImagemArmazenada.objects(id=imagem_id).first()
    if registro is None:
        abort(404)
    resposta = make_response(registro.conteudo)
    resposta.headers["Content-Type"] = registro.tipo
    resposta.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    resposta.headers["X-Content-Type-Options"] = "nosniff"
    return resposta


@bp.route("/healthz")
def healthz():
    """Endpoint publico e leve pra ping externo de keep-alive (cron-job.org,
    UptimeRobot etc.). Faz uma consulta real no banco de proposito -- so
    manter o servidor acordado nao basta, o banco tambem precisa responder.
    O banco do app e o MongoDB (o Postgres antigo nao e mais usado)."""
    import mongoengine

    mongoengine.get_db().command("ping")
    return "ok", 200


@bp.route("/dashboard")
@login_required
def dashboard():
    nome_completo = current_user.name or current_user.username or current_user.email.split("@")[0]
    primeiro_nome = nome_completo.split(" ")[0]

    foto_form = FotoPerfilForm()
    tema_form = TemaForm(tema=current_user.theme)
    senha_form = TrocarSenhaForm()
    nome_form = NomeForm(nome=nome_completo)
    privacidade_form = PrivacidadeForm(exige_aprovacao_grupos=current_user.exige_aprovacao_grupos)
    acao_form = AcaoForm()

    notificacoes = list(
        Notificacao.objects(usuario_id=current_user.id)
        .order_by("-criada_em")
        .limit(20)
    )
    notificacoes_nao_lidas = sum(1 for n in notificacoes if not n.lida)
    grupos_notificacoes = _agrupar_notificacoes(notificacoes)

    agora = _agora_brasilia()
    proxima_escala, funcao_proxima = _proxima_escala_do_usuario(current_user, agora.date())
    proxima_escala_info = None
    if proxima_escala is not None:
        partes = [f"{proxima_escala.data.day:02d} de {_MESES[proxima_escala.data.month - 1]}"]
        if proxima_escala.horario:
            partes.append(proxima_escala.horario.strftime("%H:%M"))
        partes.append(proxima_escala.departamento)
        proximo_ensaio = (
            Ensaio.objects(escala_id=proxima_escala.id, data__gte=agora.date(), cancelado__ne=True)
            .order_by("data", "horario").first()
        )
        proxima_escala_info = {
            "escala": proxima_escala,
            "detalhes": " · ".join(partes),
            "funcao": funcao_proxima,
            "proximo_ensaio": proximo_ensaio,
        }

    return render_template(
        "main/dashboard.html",
        repertorios_compartilhados=_repertorios_compartilhados(current_user),
        saudacao=_saudacao(agora.hour),
        proxima_escala=proxima_escala_info,
        agenda=_agenda_do_usuario(current_user, agora.date()),
        comunidades=_comunidades_do_usuario(current_user),
        primeiro_nome=primeiro_nome,
        nome_completo=nome_completo,
        email=current_user.email,
        foto_perfil=current_user.foto_perfil,
        eh_conta_google=bool(current_user.google_id),
        tema=obter_tema(current_user.theme),
        temas=THEMES,
        tema_atual=current_user.theme,
        foto_form=foto_form,
        tema_form=tema_form,
        senha_form=senha_form,
        tem_senha=bool(current_user.password_hash),
        nome_form=nome_form,
        privacidade_form=privacidade_form,
        acao_form=acao_form,
        notificacoes=notificacoes,
        notificacoes_nao_lidas=notificacoes_nao_lidas,
        grupos_notificacoes=grupos_notificacoes,
        icone_por_tipo=_ICONE_POR_TIPO,
        icone_padrao=_ICONE_PADRAO,
    )


def _repertorios_compartilhados(usuario, limite=6):
    """Pastas de musicas que alguem enviou pra esta conta (de qualquer
    comunidade/ministerio -- ver ministerio.routes.compartilhar_pasta). As
    ainda nao abertas primeiro, marcadas como novas; depois as mais recentes."""
    from app.auth.models import User
    from app.escala.models import PastaMusicas

    lista = []
    for pasta in PastaMusicas.objects(compartilhada_com__usuario_id=usuario.id):
        meu = pasta.compartilhamento_de(usuario.id)
        if meu is not None:
            lista.append({"pasta": pasta, "envio": meu, "novo": meu.visto_em is None})
    lista.sort(key=lambda r: (not r["novo"], -(r["envio"].enviado_em.timestamp() if r["envio"].enviado_em else 0)))
    lista = lista[:limite]
    remetentes = {u.id: u for u in User.objects(id__in=[r["envio"].enviado_por_id for r in lista])}
    for r in lista:
        quem = remetentes.get(r["envio"].enviado_por_id)
        r["remetente"] = (quem.name or quem.username or quem.email) if quem else "alguem"
    return lista


@bp.route("/notificacoes/marcar-lidas", methods=["POST"])
@login_required
def marcar_notificacoes_lidas():
    Notificacao.objects(usuario_id=current_user.id, lida=False).update(set__lida=True)
    return redirect(url_for("main.dashboard"))


@bp.route("/tutorial/<chave>/visto", methods=["POST"])
@login_required
def tutorial_visto(chave):
    """Chamado via fetch pelo tutorial guiado (spotlight, ver
    app/tutoriais.py) quando a pessoa pula ou termina -- marca pra nao
    comecar sozinho de novo pra essa conta. Sem redirect: acao de fundo."""
    from app.tutoriais import TUTORIAIS

    if chave not in TUTORIAIS:
        abort(404)
    form = AcaoForm()
    if not form.validate_on_submit():
        return jsonify({"ok": False}), 400
    if not current_user.viu_tutorial(chave):
        # $addToSet: dois tutoriais concluidos ao mesmo tempo (duas abas) nao se sobrescrevem.
        current_user.update(add_to_set__tutoriais_vistos=chave)
        current_user.tutoriais_vistos = list(current_user.tutoriais_vistos or []) + [chave]
    return jsonify({"ok": True})


@bp.route("/perfil/foto", methods=["POST"])
@login_required
def salvar_foto_perfil():
    form = FotoPerfilForm()

    if not form.validate_on_submit():
        erros = [erro for lista in form.errors.values() for erro in lista]
        flash(erros[0] if erros else "Nao foi possivel enviar a foto.", "danger")
        return redirect(url_for("main.dashboard") + "#config")

    foto_antiga = current_user.foto_perfil
    current_user.foto_perfil = salvar_imagem(form.foto.data)
    current_user.save()
    remover_imagem(foto_antiga)

    flash("Foto de perfil atualizada!", "success")
    return redirect(url_for("main.dashboard") + "#config")


@bp.route("/perfil/tema", methods=["POST"])
@login_required
def salvar_tema():
    form = TemaForm()

    if not form.validate_on_submit() or form.tema.data not in THEMES:
        flash("Nao foi possivel salvar o tema escolhido.", "danger")
        return redirect(url_for("main.dashboard") + "#config")

    current_user.theme = form.tema.data
    current_user.save()

    flash("Tema atualizado!", "success")
    return redirect(url_for("main.dashboard") + "#config")


@bp.route("/perfil/privacidade", methods=["POST"])
@login_required
def salvar_privacidade():
    """Liga/desliga User.exige_aprovacao_grupos -- so muda como FUTURAS
    adicoes a Comunidade/Ministerio funcionam (direto ou por convite, ver
    app/convites/adicao.py); nunca tira a pessoa de grupo nenhum."""
    form = PrivacidadeForm()

    if not form.validate_on_submit():
        flash("Nao foi possivel salvar a preferencia de privacidade.", "danger")
        return redirect(url_for("main.dashboard") + "#config")

    current_user.exige_aprovacao_grupos = bool(form.exige_aprovacao_grupos.data)
    current_user.save()

    if current_user.exige_aprovacao_grupos:
        flash("Pronto! A partir de agora, voce so entra em grupos depois de aceitar o convite.", "success")
    else:
        flash("Pronto! Admins e lideres podem adicionar voce direto aos grupos.", "success")
    return redirect(url_for("main.dashboard") + "#config")


@bp.route("/perfil/senha", methods=["POST"])
@login_required
@limiter.limit("10 per hour", methods=["POST"])
def salvar_senha():
    form = TrocarSenhaForm()

    if not form.validate_on_submit():
        erros = [erro for lista in form.errors.values() for erro in lista]
        flash(erros[0] if erros else "Nao foi possivel salvar a senha.", "danger")
        return redirect(url_for("main.dashboard") + "#config")

    # Conta so-Google (sem password_hash) nao tem senha atual pra conferir --
    # esse POST esta "definindo" a primeira senha, nao "trocando" uma existente.
    tinha_senha = bool(current_user.password_hash)
    if tinha_senha and not current_user.check_password(form.senha_atual.data or ""):
        flash("Senha atual incorreta.", "danger")
        return redirect(url_for("main.dashboard") + "#config")

    current_user.set_password(form.nova_senha.data)
    current_user.save()

    _notificar_senha_alterada(current_user)
    flash("Senha atualizada!" if tinha_senha else "Senha definida! Agora voce tambem pode entrar com e-mail e senha.", "success")
    return redirect(url_for("main.dashboard") + "#config")


@bp.route("/perfil/nome", methods=["POST"])
@login_required
def salvar_nome():
    form = NomeForm()

    if not form.validate_on_submit():
        flash("Informe um nome valido.", "danger")
        return redirect(url_for("main.dashboard") + "#config")

    current_user.name = form.nome.data.strip()
    current_user.save()

    flash("Nome atualizado!", "success")
    return redirect(url_for("main.dashboard") + "#config")


@bp.route("/perfil/dados")
@login_required
def baixar_dados():
    """Exportacao dos proprios dados da conta em JSON -- reforca a
    transparencia sobre privacidade (ver regra de seguranca do chatbot).
    Nunca inclui password_hash (segredo) nem as colunas mortas de
    confirmacao por token (email_confirmado/token_confirmacao, sem uso
    ativo -- ver comentario em User, app/auth/models.py)."""
    dados = {
        "id": current_user.id,
        "email": current_user.email,
        "nome": current_user.name,
        "usuario": current_user.username,
        "foto_perfil": current_user.foto_perfil,
        "tema": current_user.theme,
        "exige_aprovacao_para_grupos": bool(current_user.exige_aprovacao_grupos),
        "login_google_vinculado": bool(current_user.google_id),
        "login_senha_vinculado": bool(current_user.password_hash),
    }
    resposta = jsonify(dados)
    resposta.headers["Content-Disposition"] = "attachment; filename=meus-dados.json"
    return resposta


@bp.route("/perfil/google/desconectar", methods=["POST"])
@login_required
def desconectar_google():
    form = AcaoForm()
    if not form.validate_on_submit():
        flash("Nao foi possivel desconectar sua conta do Google.", "danger")
        return redirect(url_for("main.dashboard") + "#config")

    if not current_user.google_id:
        flash("Sua conta ja nao esta conectada ao Google.", "danger")
        return redirect(url_for("main.dashboard") + "#config")

    # Sem senha, desconectar o Google tiraria TODO acesso a conta -- nao ha
    # mais nenhuma forma de login. A tela ja esconde esse botao nesse caso,
    # mas confere de novo aqui (defesa em profundidade, POST pode ser
    # montado a mao fora da tela).
    if not current_user.password_hash:
        flash("Defina uma senha antes de desconectar o Google, senao voce perde o acesso a conta.", "danger")
        return redirect(url_for("main.dashboard") + "#config")

    current_user.google_id = None
    current_user.save()

    flash("Conta do Google desconectada.", "success")
    return redirect(url_for("main.dashboard") + "#config")


# --- Chatbot ---------------------------------------------------------------

_REGRAS_CHAT = [
    (re.compile(r"login|entrar|logar", re.I),
     "Voce pode entrar com e-mail e senha, ou pelo botao \"Entrar com o Google\" na tela de login."),
    (re.compile(r"senha", re.I),
     "Da pra trocar sua senha na aba Configuracoes do Dashboard. Quem entrou so pelo Google "
     "tambem pode definir uma senha ali, pra passar a entrar com e-mail e senha tambem. Esqueceu "
     "a senha? Tem o link \"Esqueci minha senha\" na tela de login, que manda um link por e-mail "
     "pra redefinir -- e voce recebe um aviso por e-mail toda vez que a senha muda, por seguranca."),
    (re.compile(r"foto|avatar|imagem de perfil", re.I),
     "Voce envia sua foto de perfil na aba Configuracoes do Dashboard. Aceitamos JPG e PNG de ate 2 MB."),
    (re.compile(r"tema|cor do painel|apar[eê]ncia", re.I),
     "Da pra trocar o tema do painel (Indigo, Escuro, Verde ou Laranja) na aba Configuracoes."),
    (re.compile(r"cadastr|registr|criar conta", re.I),
     "Para criar uma conta, use o formulario de Cadastro ou entre direto com sua conta do Google."),
    (re.compile(r"google", re.I),
     "O login com Google usa OAuth: voce autoriza o acesso e a gente cria sua conta com seu e-mail e foto automaticamente."),

    # --- Disponibilidade (antes do tutorial, que pegaria "como funciona") -
    (re.compile(r"disponibilidade|ciclo de (trabalho|folga)|indispon[ií]vel|turno externo", re.I),
     "Da pra cadastrar um ciclo de disponibilidade pra cada membro (ex.: 4 dias trabalhando / 4 de folga) "
     "no Diretorio de Membros da Comunidade. E so um aviso na hora de montar a escala -- nunca bloqueia, "
     "quem decide continua sendo voce."),

    # --- Tutorial guiado -----------------------------------------------
    (re.compile(r"tutorial|passo a passo|primeiros passos|como (funciona|usar|come[cç]ar)", re.I),
     "O tutorial guiado aparece sozinho na primeira vez que voce entra numa Comunidade, "
     "destacando os principais botoes da tela. Pra rever quando quiser, clique no icone de "
     "interrogacao (?) no topo da tela da Comunidade."),

    # --- Hierarquia de papeis (antes de "ministerio"/"convit", que pegariam
    # "lider de ministerio"/"quem e admin" primeiro) ----------------------
    (re.compile(r"hierarquia|super ?admin|l[ií]der de minist[eé]rio|n[ií]ve(l|is) de acesso|quem pode (editar|gerenciar|excluir)", re.I),
     "A hierarquia vai do maior pro menor alcance: Super Admin (acesso total, so criado via terminal) > "
     "Admin da Comunidade (gerencia ministerios, membros e convites) > Lider de Ministerio (gerencia escalas "
     "e rodizio so do seu ministerio) > Membro (participa e visualiza, sem poder administrativo). Ha ainda o "
     "Convidado, vinculado so a uma escala especifica, sem precisar de conta."),

    # --- Calendario (antes de "escala", que pegaria "ver o mes das escalas") -
    (re.compile(r"calend[aá]rio|visao mensal|ver o mes", re.I),
     "O Ministerio tem uma visao de Calendario com todas as escalas do mes, coloridas por departamento -- "
     "otimo pra enxergar rodizios e escalas manuais juntos de uma vez."),

    # --- Estrutura do sistema (mais especifico antes do generico) ------
    (re.compile(r"rod[ií]zio|plant[aã]o|fila de equipes|turno", re.I),
     "O Rodizio cria uma fila de equipes que se revezam automaticamente numa recorrencia "
     "(semanal, mensal...). Uma vez configurado, ele gera as escalas sozinho pros proximos meses -- "
     "acesse pela tela do Ministerio."),
    (re.compile(r"escalados|quem est[aá] escalado", re.I),
     "O relatorio \"Ver escalados\" (na tela da Comunidade) mostra todo mundo escalado em "
     "qualquer Ministerio, com filtros por data e departamento."),
    (re.compile(r"escala r[aá]pida|nova escala|criar (uma )?escala", re.I),
     "Pra criar uma Escala Rapida, entre num Ministerio e clique em \"Nova escala\" -- escolha "
     "o departamento (Louvor, Midia, Kids...) e as funcoes sugeridas ja aparecem prontas pra voce "
     "escalar as pessoas."),
    (re.compile(r"\bescala(s)?\b", re.I),
     "Uma Escala e um evento com pessoas atribuidas a funcoes especificas -- pode ser criada "
     "manualmente (\"Escala Rapida\") ou gerada automaticamente por um Rodizio."),
    (re.compile(r"membro|diret[oó]rio", re.I),
     "O Diretorio de Membros (dentro da Comunidade) e a lista de todo mundo que pode ser "
     "escalado -- nome, telefone e e-mail, sem precisar ter conta no sistema."),
    (re.compile(r"convit|convidar|papel de admin|quem [eé] admin", re.I),
     "Voce convida outras pessoas por e-mail na tela \"Papeis e convites\" da Comunidade -- "
     "da pra definir se a pessoa entra como admin ou so como membro."),
    (re.compile(r"minist[eé]rio", re.I),
     "Um Ministerio e uma area da sua Comunidade (Louvor, Midia, Kids...) -- e dentro dele que "
     "as escalas de verdade sao criadas e organizadas."),
    (re.compile(r"comunidade", re.I),
     "Uma Comunidade e a organizacao raiz do sistema (sua igreja ou grupo). Dentro dela voce "
     "cria Ministerios, convida pessoas e monta escalas. Crie uma nova em \"Nova comunidade\"."),
    (re.compile(r"notifica[cç][aã]o|avis[ao]|lembrete", re.I),
     "O sistema notifica automaticamente por e-mail, SMS e sino no site 24h e 16h antes de cada "
     "evento escalado -- nao precisa configurar nada, ja vem ligado."),

    (re.compile(r"chat|voce e real|\bia\b|intelig[eê]ncia artificial", re.I),
     "Por enquanto sou um assistente simulado (respostas por regras). Em breve vou ser conectado a uma IA de verdade."),

    # --- Seguranca e privacidade dos dados -------------------------------
    (re.compile(r"seguran[cç]a|privacidade|dados (seguros|protegidos)|vazament|criptograf", re.I),
     "Levamos seguranca a serio: senhas nunca sao guardadas em texto puro (sao criptografadas), a conexao "
     "e sempre HTTPS, e ha protecao contra tentativas repetidas de login. Os dados da sua Comunidade so sao "
     "visiveis pra quem tem papel/convite ativo nela."),

    # --- Atalho de navegacao ----------------------------------------------
    (re.compile(r"voltar (pro|para o) in[ií]cio|atalho|logo (clic|no topo)", re.I),
     "O logo pequeno no cabecalho de qualquer tela leva direto pro Dashboard, de qualquer profundidade -- "
     "complementa a seta \"Voltar\", que so sobe 1 nivel por vez."),

    # --- Marca ------------------------------------------------------------
    (re.compile(r"pibachurch|swerdne|quem (fez|criou|desenvolveu)", re.I),
     "O TyBenson e um sistema de gestao pra igrejas e comunidades -- escalas, ministerios, convites e "
     "notificacoes automaticas, tudo num so lugar."),

    # --- Pequena conversa ---------------------------------------------------
    (re.compile(r"\b(obrigad[oa]|valeu|vlw)\b", re.I),
     "Disponha! Se precisar de mais alguma coisa e so perguntar."),
    (re.compile(r"\bsair\b|logout|deslogar", re.I),
     "Pra sair da conta, use o botao \"Sair\" na aba Configuracoes do Dashboard."),
    (re.compile(r"^(oi|ol[aá]|e a[ií]|bom dia|boa tarde|boa noite)\b", re.I),
     "Oi! Posso ajudar com login, cadastro, comunidades, ministerios, escalas, rodizio, convites, "
     "disponibilidade, calendario ou o tutorial guiado. O que voce quer saber?"),
    (re.compile(r"\bajuda\b|\bmenu\b|o que (voce|vc) (faz|sabe)", re.I),
     "Posso te explicar: login e cadastro, foto de perfil, temas, comunidades, ministerios, escalas, "
     "rodizio/plantao, convites e hierarquia de papeis, diretorio de membros, disponibilidade, calendario, "
     "notificacoes e o tutorial guiado. E so perguntar sobre qualquer um desses assuntos."),
]

_RESPOSTA_PADRAO = (
    "Ainda estou aprendendo sobre isso. Tente perguntar sobre login, cadastro, comunidades, "
    "ministerios, escalas, rodizio, convites, hierarquia de papeis, disponibilidade, calendario, "
    "notificacoes, seguranca ou o tutorial guiado."
)


def _responder_mock(mensagem, historico):
    # `historico` ainda nao influencia a resposta simulada, mas ja fica na
    # assinatura porque a integracao real de IA vai precisar dele como contexto.
    del historico
    for padrao, resposta in _REGRAS_CHAT:
        if padrao.search(mensagem):
            return resposta
    return _RESPOSTA_PADRAO


@bp.route("/chat", methods=["POST"])
@login_required
def chat():
    dados = request.get_json(silent=True) or {}
    mensagem = (dados.get("mensagem") or "").strip()
    historico = dados.get("historico") or []  # [{"autor": "usuario"|"bot", "texto": "..."}]

    if not mensagem:
        return jsonify({"erro": "Mensagem vazia."}), 400

    if current_app.config["MOCK_CHATBOT"]:
        time.sleep(0.5)  # simula a latencia de uma chamada real de IA
        resposta = _responder_mock(mensagem, historico)
    else:
        # TODO: plugar aqui a chamada real a API de IA (Anthropic/OpenAI).
        # `historico` + `mensagem` devem ser enviados como o contexto da conversa.
        resposta = "O chatbot com IA real ainda nao foi configurado neste ambiente."

    return jsonify({"resposta": resposta})


@bp.route("/minha-escala")
@login_required
def minha_escala():
    """Visao pessoal de cada dia em que a conta esta escalada (Membro com o
    mesmo e-mail): funcao(oes), status, ensaios, repertorio e os materiais
    da equipe + os da propria funcao -- sem a escala inteira de todo mundo.
    Navega entre os dias pela barra de datas (?escala=<id>)."""
    hoje = _agora_brasilia().date()
    ids_membro = Membro.ids_da_conta(current_user.email)
    funcoes = list(Funcao.objects(membro_id__in=ids_membro)) if ids_membro else []
    funcoes_por_escala = {}
    for funcao in funcoes:
        funcoes_por_escala.setdefault(funcao.escala_id, []).append(funcao)
    escalas = list(Escala.objects(id__in=list(funcoes_por_escala))) if funcoes_por_escala else []

    sem_data = datetime.max.date()
    proximas = sorted(
        (e for e in escalas if e.data is None or e.data >= hoje),
        key=lambda e: (e.data or sem_data, e.horario or datetime.min.time()),
    )
    anteriores = sorted(
        (e for e in escalas if e.data is not None and e.data < hoje),
        key=lambda e: (e.data, e.horario or datetime.min.time()),
        reverse=True,
    )[:12]
    ver_anteriores = request.args.get("anteriores") == "1"
    dias = anteriores if ver_anteriores else proximas

    escolhida_id = request.args.get("escala", type=int)
    selecionada = next((e for e in escalas if e.id == escolhida_id), None) or (dias[0] if dias else None)

    contexto = {}
    if selecionada is not None:
        minhas_funcoes = sorted(funcoes_por_escala[selecionada.id], key=lambda f: f.ordem)
        ids_minhas = {f.id for f in minhas_funcoes}
        nomes_funcao = {f.id: f.nome for f in minhas_funcoes}
        anexos = [
            a for a in Anexo.objects(escala_id=selecionada.id).exclude("conteudo").order_by("criado_em")
            if a.funcao_id is None or a.funcao_id in ids_minhas
        ]
        ministerio = selecionada.ministerio
        sugestoes = [(0, "Ninguem em especial")] + [
            (m.id, m.nome) for m in Membro.objects(comunidade_id=ministerio.comunidade_id).order_by("nome")
        ]
        formularios_status = {}
        for funcao in minhas_funcoes:
            form = status_sem_presente(StatusForm(status=funcao.status or "nao_notificado"), funcao.status, selecionada)
            form.troca_sugestao_membro_id.choices = sugestoes
            formularios_status[funcao.id] = form
        com_checkin = [f for f in minhas_funcoes if f.checkin_em]
        ensaios = selecionada.ensaios
        checkin_ensaio_ligado = checkin_ligado(selecionada, "ensaio")
        meus_membros = {f.membro_id for f in minhas_funcoes}
        presencas_ensaio = {
            p.ensaio_id: p for p in PresencaEnsaio.objects(escala_id=selecionada.id, membro_id__in=list(meus_membros))
        } if checkin_ensaio_ligado else {}
        contexto = {
            "minhas_funcoes": minhas_funcoes,
            "formularios_status": formularios_status,
            "ensaios": ensaios,
            "checkin_escala_ligado": checkin_ligado(selecionada, "escala"),
            "checkin_ensaio_ligado": checkin_ensaio_ligado,
            "presencas_ensaio": presencas_ensaio,
            "motivo_ensaio": {e.id: situacao_do_ensaio(e, selecionada, hoje) for e in ensaios} if checkin_ensaio_ligado else {},
            "anexos": anexos,
            "nomes_funcao": nomes_funcao,
            "repertorio": selecionada.repertorio,
            "ministerio": ministerio,
            # Check-in por localizacao (app/escala/checkin.py)
            "local_checkin": local_do_checkin(ministerio),
            "motivo_sem_checkin": situacao_do_dia(selecionada, hoje),
            "checkin_feito": com_checkin[0] if com_checkin else None,
            "presente_sem_checkin": not com_checkin and any(f.status == "presente" for f in minhas_funcoes),
            # Cada funcao recebe a sua versao do repertorio: projecao/midia
            # fica com a letra; quem toca/canta, com as cifras.
            "folhas_repertorio": sorted({
                "projecao" if eh_funcao_de_projecao(f.nome) else "cifras" for f in minhas_funcoes
            }, reverse=True),
        }

    return render_template(
        "main/minha_escala.html",
        dias=dias,
        ver_anteriores=ver_anteriores,
        tem_anteriores=bool(anteriores),
        selecionada=selecionada,
        hoje=hoje,
        meses=_MESES,
        status_labels=STATUS_LABELS,
        status_cores=STATUS_CORES,
        acao_form=AcaoForm(),
        **contexto,
    )
