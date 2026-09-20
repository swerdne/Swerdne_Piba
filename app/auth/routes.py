"""Controller (C do MVC): rotas do modulo auth."""
import secrets
from datetime import datetime, timedelta

from flask import render_template, redirect, url_for, flash, request, current_app, jsonify, session
from flask_login import login_user, logout_user, login_required, current_user
from authlib.integrations.base_client.errors import OAuthError
from app.extensions import db, oauth, limiter
from app.auth import bp
from app.auth.forms import LoginForm, RegisterForm, EsqueciSenhaForm, RedefinirSenhaForm
from app.auth.models import User
from app.emailing import enviar_email, EmailNaoEnviadoError

# Validade do link de redefinicao de senha -- curto de proposito (e um link
# que da controle total da conta pra quem clicar, mais sensivel que o de
# convite/confirmacao de e-mail).
_VALIDADE_TOKEN_REDEFINICAO = timedelta(hours=1)

# datetime.utcnow() (naive) de proposito aqui, nao datetime.now(timezone.utc)
# como o resto do projeto -- a coluna e um DateTime sem timezone=True, entao
# o valor lido de volta do banco (em redefinir_senha, numa request separada
# da que gerou o token) vem naive. Comparar naive com aware derruba com
# TypeError; manter os dois lados naive evita esse problema.


def _notificar_senha_alterada(user):
    """Avisa por e-mail sempre que a senha muda -- por qualquer via (aqui ou
    em main.routes.salvar_senha). Nao e uma confirmacao (a troca ja
    aconteceu), e um alerta de seguranca: se nao foi a propria pessoa, ela
    sabe que precisa agir. Falha de envio nunca quebra a troca (mesmo padrao
    de app/emailing.py em todo o projeto)."""
    try:
        enviar_email(
            user.email,
            "Sua senha foi alterada",
            "A senha da sua conta Pibachurch acabou de ser alterada. "
            "Se foi voce, pode ignorar este e-mail. Se nao foi voce, "
            "redefina sua senha imediatamente pelo link 'Esqueci minha senha' na tela de login.",
        )
    except EmailNaoEnviadoError:
        pass


def _redirecionar_apos_login():
    """Depois de login/registro/Google, volta pro link que o usuario estava
    tentando acessar antes de autenticar (ex: aceitar um convite, ver
    app/convites/routes.py::ver_convite) -- cai no dashboard se nao havia
    nenhum destino guardado. `pop` de proposito: o destino so vale uma vez."""
    destino = session.pop("proximo_apos_login", None)
    return redirect(destino or url_for("main.dashboard"))


# Usuario fake devolvido pelo "Google simulado" no cenario de sucesso.
MOCK_GOOGLE_USER = {
    "sub": "mock-google-id-123",
    "email": "usuario.teste@example.com",
    "name": "Usuario de Teste",
    "picture": "https://i.pravatar.cc/150?u=mock-google-id-123",
}


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user and user.check_password(form.password.data):
            login_user(user, remember=form.remember.data)
            return _redirecionar_apos_login()
        flash("Credenciais invalidas.", "danger")
    return render_template("auth/login.html", form=form)


@bp.route("/register", methods=["GET", "POST"])
@limiter.limit("5 per hour", methods=["POST"])
def register():
    form = RegisterForm()
    if form.validate_on_submit():
        # Sem confirmacao de e-mail: a conta ja nasce ativa e loga direto,
        # igual ao Google (que tambem nao passa por esse fluxo).
        user = User(username=form.username.data, email=form.email.data, email_confirmado=True)
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()

        login_user(user)
        return _redirecionar_apos_login()
    return render_template("auth/register.html", form=form)


@bp.route("/esqueci-senha", methods=["GET", "POST"])
@limiter.limit("5 per hour", methods=["POST"])
def esqueci_senha():
    form = EsqueciSenhaForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        # So gera token se a conta existe E tem senha (conta so-Google nao
        # tem senha pra redefinir por aqui -- ela define a primeira senha
        # direto na aba Configuracoes, ja logada). A mensagem de sucesso e
        # SEMPRE a mesma independente do resultado, pra nao revelar por
        # tentativa e erro quais e-mails tem conta (enumeration attack).
        if user and user.password_hash:
            user.token_redefinicao_senha = secrets.token_urlsafe(32)
            user.token_redefinicao_expira_em = datetime.utcnow() + _VALIDADE_TOKEN_REDEFINICAO
            db.session.commit()

            link = url_for("auth.redefinir_senha", token=user.token_redefinicao_senha, _external=True)
            try:
                enviar_email(
                    user.email,
                    "Redefinicao de senha",
                    f"Recebemos um pedido pra redefinir a senha da sua conta Pibachurch.\n\n"
                    f"Clique no link abaixo pra escolher uma nova senha (valido por 1 hora):\n{link}\n\n"
                    "Se voce nao pediu isso, pode ignorar este e-mail -- sua senha continua a mesma.",
                )
            except EmailNaoEnviadoError:
                pass

        flash("Se esse e-mail tiver uma conta com senha, enviamos um link de redefinicao.", "success")
        return redirect(url_for("auth.login"))
    return render_template("auth/esqueci_senha.html", form=form)


@bp.route("/redefinir-senha/<token>", methods=["GET", "POST"])
@limiter.limit("10 per hour", methods=["POST"])
def redefinir_senha(token):
    user = User.query.filter_by(token_redefinicao_senha=token).first()
    token_valido = bool(
        user and user.token_redefinicao_expira_em and user.token_redefinicao_expira_em >= datetime.utcnow()
    )

    if not token_valido:
        flash("Esse link de redefinicao e invalido ou ja expirou. Solicite um novo.", "danger")
        return redirect(url_for("auth.esqueci_senha"))

    form = RedefinirSenhaForm()
    if form.validate_on_submit():
        user.set_password(form.nova_senha.data)
        # Uso unico: sem isso, o mesmo link continuaria valido por 1h mesmo
        # apos ja ter sido usado pra trocar a senha.
        user.token_redefinicao_senha = None
        user.token_redefinicao_expira_em = None
        db.session.commit()

        _notificar_senha_alterada(user)
        flash("Senha redefinida! Faca login com a nova senha.", "success")
        return redirect(url_for("auth.login"))
    return render_template("auth/redefinir_senha.html", form=form, token=token)


@bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("main.index"))


@bp.route("/sessao-atual")
def sessao_atual():
    """Endpoint leve pra JS detectar troca/perda de sessao NESTA aba (ver
    static/js/main.js) -- o cookie de sessao e compartilhado por todo o
    navegador, entao logar com outra conta numa aba troca a sessao de todas
    as abas silenciosamente. Sem @login_required de proposito: precisa
    responder tambem quando a sessao virou anonima (logout/expirou em outra
    aba), nao so quando trocou de usuario."""
    usuario_id = current_user.id if current_user.is_authenticated else None
    return jsonify({"usuario_id": usuario_id})


@bp.route("/google")
def google_login():
    """Inicia o fluxo OAuth redirecionando o usuario para o Google."""
    if current_app.config["MOCK_GOOGLE_OAUTH"]:
        # Em vez do Google real, mostra uma tela local com os cenarios de teste
        return render_template("auth/google_mock.html")

    redirect_uri = url_for("auth.google_callback", _external=True)
    return oauth.google.authorize_redirect(redirect_uri)


@bp.route("/google/callback")
def google_callback():
    """Recebe o retorno do Google, cria/atualiza o usuario e efetua o login."""
    if current_app.config["MOCK_GOOGLE_OAUTH"]:
        cenario = request.args.get("cenario", "sucesso")

        if cenario == "negado":
            # Simula o usuario cancelando/negando o consentimento no Google
            flash("Nao foi possivel concluir o login com o Google. Tente novamente.", "danger")
            return redirect(url_for("auth.login"))

        if cenario == "timeout":
            # Simula timeout/token expirado/falha de rede com o Google
            flash("Nao foi possivel obter os dados da sua conta Google. Tente novamente.", "danger")
            return redirect(url_for("auth.login"))

        info = MOCK_GOOGLE_USER  # cenario == "sucesso"
    else:
        try:
            token = oauth.google.authorize_access_token()
        except OAuthError:
            # Usuario cancelou o consentimento, ou a sessao expirou/o link foi reaproveitado
            flash("Nao foi possivel concluir o login com o Google. Tente novamente.", "danger")
            return redirect(url_for("auth.login"))

        info = token.get("userinfo")
        if info is None:
            flash("Nao foi possivel obter os dados da sua conta Google. Tente novamente.", "danger")
            return redirect(url_for("auth.login"))

    google_id = info["sub"]
    email = info["email"]
    name = info.get("name")
    foto_perfil = info.get("picture")

    user = User.query.filter_by(google_id=google_id).first()
    if user is None:
        # Se ja existe uma conta tradicional com o mesmo e-mail, vincula o Google a ela
        user = User.query.filter_by(email=email).first()
        if user is None:
            # O Google ja validou a posse do e-mail -- nao precisa do fluxo de confirmacao.
            user = User(google_id=google_id, email=email, name=name, foto_perfil=foto_perfil, email_confirmado=True)
            db.session.add(user)
        else:
            user.google_id = google_id
            user.name = user.name or name
            user.foto_perfil = foto_perfil
            user.email_confirmado = True
    else:
        user.name = name or user.name
        user.foto_perfil = foto_perfil

    db.session.commit()

    login_user(user)
    flash("Login com Google realizado com sucesso!", "success")
    return _redirecionar_apos_login()
