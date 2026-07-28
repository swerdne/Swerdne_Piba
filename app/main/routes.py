"""Controller (C do MVC): rotas do modulo main."""
import os
import re
import time
import uuid

from flask import render_template, redirect, url_for, flash, request, jsonify, current_app
from flask_login import login_required, current_user
from sqlalchemy import text
from werkzeug.utils import secure_filename

from app.extensions import db
from app.main import bp
from app.main.forms import FotoPerfilForm, TemaForm
from app.main.themes import THEMES, obter_tema
from app.notificacoes import Notificacao


@bp.route("/")
def index():
    return redirect(url_for("main.dashboard"))


@bp.route("/healthz")
def healthz():
    """Endpoint publico e leve pra ping externo de keep-alive (cron-job.org,
    UptimeRobot etc.). Faz uma consulta real no banco de proposito -- so
    manter o servidor Flask acordado nao evita o Postgres (Neon) hibernar
    por inatividade, os dois hibernam de forma independente."""
    db.session.execute(text("SELECT 1"))
    return "ok", 200


@bp.route("/dashboard")
@login_required
def dashboard():
    nome_completo = current_user.name or current_user.username or current_user.email.split("@")[0]
    primeiro_nome = nome_completo.split(" ")[0]

    foto_form = FotoPerfilForm()
    tema_form = TemaForm(tema=current_user.theme)

    notificacoes = (
        Notificacao.query.filter_by(usuario_id=current_user.id)
        .order_by(Notificacao.criada_em.desc())
        .limit(20)
        .all()
    )
    notificacoes_nao_lidas = sum(1 for n in notificacoes if not n.lida)

    return render_template(
        "main/dashboard.html",
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
        notificacoes=notificacoes,
        notificacoes_nao_lidas=notificacoes_nao_lidas,
    )


@bp.route("/notificacoes/marcar-lidas", methods=["POST"])
@login_required
def marcar_notificacoes_lidas():
    Notificacao.query.filter_by(usuario_id=current_user.id, lida=False).update({"lida": True})
    db.session.commit()
    return redirect(url_for("main.dashboard"))


@bp.route("/perfil/foto", methods=["POST"])
@login_required
def salvar_foto_perfil():
    form = FotoPerfilForm()

    if not form.validate_on_submit():
        erros = [erro for lista in form.errors.values() for erro in lista]
        flash(erros[0] if erros else "Nao foi possivel enviar a foto.", "danger")
        return redirect(url_for("main.dashboard") + "#config")

    arquivo = form.foto.data
    extensao = arquivo.filename.rsplit(".", 1)[1].lower()
    nome_arquivo = secure_filename(f"user_{current_user.id}_{uuid.uuid4().hex}.{extensao}")

    upload_folder = current_app.config["UPLOAD_FOLDER"]
    os.makedirs(upload_folder, exist_ok=True)
    arquivo.save(os.path.join(upload_folder, nome_arquivo))

    # Remove o avatar local anterior (se houver) para nao acumular arquivos orfaos.
    foto_antiga = current_user.foto_perfil
    if foto_antiga and foto_antiga.startswith("/static/uploads/avatars/"):
        caminho_antigo = os.path.join("app", foto_antiga.lstrip("/"))
        if os.path.isfile(caminho_antigo):
            try:
                os.remove(caminho_antigo)
            except OSError:
                pass

    current_user.foto_perfil = f"/static/uploads/avatars/{nome_arquivo}"
    db.session.commit()

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
    db.session.commit()

    flash("Tema atualizado!", "success")
    return redirect(url_for("main.dashboard") + "#config")


# --- Chatbot ---------------------------------------------------------------

_REGRAS_CHAT = [
    (re.compile(r"login|entrar|logar", re.I),
     "Voce pode entrar com e-mail e senha, ou pelo botao \"Entrar com o Google\" na tela de login."),
    (re.compile(r"senha", re.I),
     "A troca de senha ainda nao esta disponivel na interface, mas ja esta no nosso radar."),
    (re.compile(r"foto|avatar|imagem", re.I),
     "Voce envia sua foto de perfil na aba Configuracoes do Dashboard. Aceitamos JPG e PNG de ate 2 MB."),
    (re.compile(r"tema|cor|apar[eê]ncia", re.I),
     "Da pra trocar o tema do painel (Indigo, Escuro, Verde ou Laranja) na aba Configuracoes."),
    (re.compile(r"cadastr|registr|criar conta", re.I),
     "Para criar uma conta, use o formulario de Cadastro ou entre direto com sua conta do Google."),
    (re.compile(r"google", re.I),
     "O login com Google usa OAuth: voce autoriza o acesso e a gente cria sua conta com seu e-mail e foto automaticamente."),
    (re.compile(r"chat|voce e real|ia|intelig[eê]ncia", re.I),
     "Por enquanto sou um assistente simulado (respostas por regras). Em breve vou ser conectado a uma IA de verdade."),
]

_RESPOSTA_PADRAO = (
    "Ainda estou aprendendo sobre isso. Tente perguntar sobre login, cadastro, "
    "foto de perfil ou temas do painel."
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
