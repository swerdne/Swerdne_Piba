"""Model (M do MVC): entidade User."""
import secrets
from datetime import datetime, timedelta, timezone

from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from app.extensions import db, login_manager

HORAS_VALIDADE_TOKEN_CONFIRMACAO = 24


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)

    # Comuns a qualquer forma de cadastro
    email = db.Column(db.String(120), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=True)
    foto_perfil = db.Column(db.String(500), nullable=True)

    # Especificos do cadastro tradicional (email/senha)
    username = db.Column(db.String(80), unique=True, nullable=True)
    password_hash = db.Column(db.String(255), nullable=True)

    # Especifico do login social (Google OAuth)
    google_id = db.Column(db.String(255), unique=True, nullable=True)

    # Preferencia de aparencia do dashboard (ver app/main/themes.py)
    theme = db.Column(db.String(20), nullable=False, default="indigo", server_default="indigo")

    # Tutorial guiado (spotlight) mostrado na primeira vez que a conta entra
    # numa tela de detalhe de Comunidade -- ver app/comunidade/routes.py e
    # app/static/js/tutorial.js. Uma vez so, pra conta inteira (nao repete
    # por comunidade).
    tutorial_comunidade_visto = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())

    # Acesso total a plataforma (gerencia qualquer Comunidade/Ministerio,
    # bypassa toda checagem de posse/papel) -- NUNCA atribuivel por convite
    # comum (ver app/convites/CLAUDE.md), so pelo comando
    # `flask criar-super-admin <email>` (app/__init__.py), que exige acesso
    # ao servidor/terminal.
    eh_super_admin = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())

    # Confirmacao de e-mail (cadastro tradicional) -- ver app/auth/CLAUDE.md.
    # default=False (Python/ORM) pro cadastro tradicional exigir confirmacao;
    # server_default=true() (SQL) so pra migracao dar como confirmadas as
    # contas que ja existiam antes dessa coluna existir (nunca teriam como
    # confirmar retroativamente). Contas Google sao marcadas confirmadas no
    # momento da criacao (o proprio Google ja validou a posse do e-mail).
    email_confirmado = db.Column(db.Boolean, nullable=False, default=False, server_default=db.true())
    token_confirmacao = db.Column(db.String(64), unique=True, nullable=True)
    token_confirmacao_expira_em = db.Column(db.DateTime, nullable=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        # Usuarios criados via Google nao possuem password_hash
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    def gerar_token_confirmacao(self):
        """Gera um novo token de confirmacao de e-mail, valido por
        HORAS_VALIDADE_TOKEN_CONFIRMACAO horas -- usado tanto no cadastro
        quanto no reenvio (troca o token anterior, invalidando links velhos)."""
        self.token_confirmacao = secrets.token_urlsafe(32)
        self.token_confirmacao_expira_em = datetime.now(timezone.utc) + timedelta(
            hours=HORAS_VALIDADE_TOKEN_CONFIRMACAO
        )
        return self.token_confirmacao

    def token_confirmacao_valido(self, token):
        return (
            self.token_confirmacao is not None
            and secrets.compare_digest(self.token_confirmacao, token)
            and self.token_confirmacao_expira_em is not None
            and self.token_confirmacao_expira_em.replace(tzinfo=timezone.utc) > datetime.now(timezone.utc)
        )

    def __repr__(self):
        return f"<User {self.username}>"


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))
