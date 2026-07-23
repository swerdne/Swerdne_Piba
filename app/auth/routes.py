"""Controller (C do MVC): rotas do modulo auth."""
from flask import render_template, redirect, url_for, flash, request, current_app
from flask_login import login_user, logout_user, login_required
from authlib.integrations.base_client.errors import OAuthError
from app.extensions import db, oauth
from app.auth import bp
from app.auth.forms import LoginForm, RegisterForm
from app.auth.models import User

# Usuario fake devolvido pelo "Google simulado" no cenario de sucesso.
MOCK_GOOGLE_USER = {
    "sub": "mock-google-id-123",
    "email": "usuario.teste@example.com",
    "name": "Usuario de Teste",
    "picture": "https://i.pravatar.cc/150?u=mock-google-id-123",
}


@bp.route("/login", methods=["GET", "POST"])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user and user.check_password(form.password.data):
            login_user(user, remember=form.remember.data)
            return redirect(url_for("main.dashboard"))
        flash("Credenciais invalidas.", "danger")
    return render_template("auth/login.html", form=form)


@bp.route("/register", methods=["GET", "POST"])
def register():
    form = RegisterForm()
    if form.validate_on_submit():
        user = User(username=form.username.data, email=form.email.data)
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        login_user(user)
        flash("Conta criada com sucesso! Bem-vindo(a).", "success")
        return redirect(url_for("main.dashboard"))
    return render_template("auth/register.html", form=form)


@bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("main.index"))


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
            user = User(google_id=google_id, email=email, name=name, foto_perfil=foto_perfil)
            db.session.add(user)
        else:
            user.google_id = google_id
            user.name = user.name or name
            user.foto_perfil = foto_perfil
    else:
        user.name = name or user.name
        user.foto_perfil = foto_perfil

    db.session.commit()

    login_user(user)
    flash("Login com Google realizado com sucesso!", "success")
    return redirect(url_for("main.dashboard"))
