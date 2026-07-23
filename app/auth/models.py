"""Model (M do MVC): entidade User."""
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from app.extensions import db, login_manager


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

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        # Usuarios criados via Google nao possuem password_hash
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f"<User {self.username}>"


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))
