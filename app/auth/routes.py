"""Controller (C do MVC): rotas do modulo auth."""
from flask import render_template, redirect, url_for, flash, request, current_app, jsonify, session
from flask_login import login_user, logout_user, login_required, current_user
from authlib.integrations.base_client.errors import OAuthError
from app.extensions import db, oauth
from app.auth import bp
from app.auth.forms import LoginForm, RegisterForm, ReenviarConfirmacaoForm
from app.auth.models import User
from app.emailing import enviar_email, EmailNaoEnviadoError


def _redirecionar_apos_login():
    """Depois de login/registro/Google, volta pro link que o usuario estava
    tentando acessar antes de autenticar (ex: aceitar um convite, ver
    app/convites/routes.py::ver_convite) -- cai no dashboard se nao havia
    nenhum destino guardado. `pop` de proposito: o destino so vale uma vez."""
    destino = session.pop("proximo_apos_login", None)
    return redirect(destino or url_for("main.dashboard"))


def _enviar_email_de_confirmacao(user):
    """Gera um token novo (invalida qualquer link antigo) e envia o e-mail de
    confirmacao. Falha de envio nunca quebra a requisicao (mesmo padrao de
    app/convites/routes.py::_enviar_email_de_convite) -- a conta ja foi
    criada/o token ja foi salvo, so avisa que o e-mail pode nao ter chegado e
    mostra o link pra copiar manualmente."""
    user.gerar_token_confirmacao()
    db.session.commit()

    link = url_for("auth.confirmar_email", token=user.token_confirmacao, _external=True)
    corpo = (
        f"Falta pouco! Confirme seu e-mail pra ativar sua conta no Swerdne Piba.\n\n"
        f"Acesse o link abaixo (valido por {24}h):\n{link}\n\n"
        "Se voce nao pediu esse cadastro, pode ignorar este e-mail."
    )
    try:
        enviar_email(user.email, "Confirme seu e-mail", corpo)
    except EmailNaoEnviadoError:
        flash(
            f"Nao conseguimos enviar o e-mail de confirmacao agora. "
            f"Voce pode usar este link diretamente: {link}",
            "danger",
        )


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
            if not user.email_confirmado:
                return render_template(
                    "auth/verifique_email.html",
                    email=user.email,
                    reenviar_form=ReenviarConfirmacaoForm(email=user.email),
                )
            login_user(user, remember=form.remember.data)
            return _redirecionar_apos_login()
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

        _enviar_email_de_confirmacao(user)

        return render_template(
            "auth/verifique_email.html",
            email=user.email,
            reenviar_form=ReenviarConfirmacaoForm(email=user.email),
            eh_cadastro_novo=True,
        )
    return render_template("auth/register.html", form=form)


@bp.route("/confirmar-email/<token>")
def confirmar_email(token):
    user = User.query.filter_by(token_confirmacao=token).first()

    if user is None:
        flash("Link de confirmacao invalido. Se ja confirmou seu e-mail, so fazer login.", "danger")
        return redirect(url_for("auth.login"))

    if not user.token_confirmacao_valido(token):
        return render_template(
            "auth/verifique_email.html",
            email=user.email,
            reenviar_form=ReenviarConfirmacaoForm(email=user.email),
            link_expirado=True,
        )

    user.email_confirmado = True
    user.token_confirmacao = None
    user.token_confirmacao_expira_em = None
    db.session.commit()

    login_user(user)
    flash("E-mail confirmado com sucesso! Sua conta esta ativa.", "success")
    return _redirecionar_apos_login()


@bp.route("/reenviar-confirmacao", methods=["POST"])
def reenviar_confirmacao():
    form = ReenviarConfirmacaoForm()

    if not form.validate_on_submit():
        flash("Informe um e-mail valido.", "danger")
        return redirect(url_for("auth.login"))

    user = User.query.filter_by(email=form.email.data).first()

    if user is None:
        flash("Nao encontramos uma conta com esse e-mail.", "danger")
        return redirect(url_for("auth.login"))

    if user.email_confirmado:
        flash("Esse e-mail ja esta confirmado. Voce ja pode fazer login.", "success")
        return redirect(url_for("auth.login"))

    _enviar_email_de_confirmacao(user)
    flash("Reenviamos o e-mail de confirmacao.", "success")
    return render_template(
        "auth/verifique_email.html",
        email=user.email,
        reenviar_form=ReenviarConfirmacaoForm(email=user.email),
    )


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
    # Log temporario de diagnostico -- confirma qual client_id/client_secret o
    # processo esta de fato enxergando em runtime (mascarado), pra descartar
    # Environment Group sobrepondo, servico errado no Render, ou deploy que
    # nao pegou a variavel nova. Remover junto com o print de OAuthError abaixo.
    cid = current_app.config.get("GOOGLE_CLIENT_ID") or ""
    csec = current_app.config.get("GOOGLE_CLIENT_SECRET") or ""
    print(f"[google_login] redirect_uri={redirect_uri!r} "
          f"client_id_fim={cid[-10:]!r} "
          f"client_secret_len={len(csec)} client_secret_fim={csec[-4:]!r}", flush=True)
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
        except OAuthError as erro:
            # Log temporario de diagnostico -- sem isso o motivo exato (invalid_client,
            # invalid_grant, redirect_uri_mismatch etc.) nao aparece em lugar nenhum,
            # so a mensagem generica que o usuario ve. Remover depois de identificar a causa.
            print(f"[google_callback] OAuthError: {erro!r} | error={getattr(erro, 'error', None)!r} "
                  f"description={getattr(erro, 'description', None)!r}", flush=True)
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
