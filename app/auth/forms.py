"""Formularios Flask-WTF do modulo auth."""
from flask import current_app
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, SubmitField
from wtforms.validators import DataRequired, Email, Length, EqualTo, ValidationError

from app.auth.models import User
from app.auth.dominio_email import dominio_aceita_email


def normalizar_email(valor):
    """E-mail sem espaco nas pontas e em minusculas. No iPhone o teclado
    poe a 1a letra em maiuscula ("Fulano@...") e o preenchimento automatico
    as vezes deixa um espaco no fim -- com a comparacao exata, "Esqueci
    minha senha" nao achava a conta e o e-mail nunca saia."""
    return valor.strip().lower() if isinstance(valor, str) else valor


# Campo de e-mail de verdade no celular: teclado com @, sem maiuscula
# automatica nem corretor.
_ATRIBUTOS_EMAIL = {"type": "email", "autocapitalize": "none", "autocorrect": "off",
                    "spellcheck": "false", "autocomplete": "email", "inputmode": "email"}


def _campo_email():
    return StringField("E-mail", validators=[DataRequired(), Email()],
                       filters=[normalizar_email], render_kw=dict(_ATRIBUTOS_EMAIL))


class LoginForm(FlaskForm):
    email = _campo_email()
    password = PasswordField("Senha", validators=[DataRequired()])
    # Marcado por padrao: desmarcar so faz sentido em aparelho compartilhado.
    remember = BooleanField("Lembrar de mim", default=True)
    submit = SubmitField("Entrar")


class EsqueciSenhaForm(FlaskForm):
    email = _campo_email()
    submit = SubmitField("Enviar link de redefinicao")


class RedefinirSenhaForm(FlaskForm):
    nova_senha = PasswordField("Nova senha", validators=[DataRequired(), Length(min=8)])
    confirmar_senha = PasswordField(
        "Confirme a nova senha",
        validators=[DataRequired(), EqualTo("nova_senha", message="As senhas devem coincidir.")],
    )
    submit = SubmitField("Redefinir senha")


class RegisterForm(FlaskForm):
    username = StringField("Usuario", validators=[DataRequired(), Length(min=3, max=80)])
    email = _campo_email()
    password = PasswordField("Senha", validators=[DataRequired(), Length(min=8)])
    confirm = PasswordField(
        "Confirme a senha",
        validators=[DataRequired(), EqualTo("password", message="As senhas devem coincidir.")],
    )
    submit = SubmitField("Cadastrar")

    def validate_username(self, field):
        if User.objects(username=field.data).first():
            raise ValidationError("Este nome de usuario ja esta em uso.")

    def validate_email(self, field):
        if User.objects(email__iexact=field.data).first():
            raise ValidationError(
                "Este e-mail ja esta cadastrado. Faca login ou use 'Entrar com o Google'."
            )

        if current_app.config.get("VALIDAR_DOMINIO_EMAIL", True):
            dominio = field.data.rsplit("@", 1)[-1]
            if not dominio_aceita_email(dominio):
                raise ValidationError(
                    "Nao conseguimos confirmar que esse dominio de e-mail existe. Confira se digitou certo."
                )
