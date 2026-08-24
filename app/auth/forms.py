"""Formularios Flask-WTF do modulo auth."""
from flask import current_app
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, HiddenField, SubmitField
from wtforms.validators import DataRequired, Email, Length, EqualTo, ValidationError

from app.auth.models import User
from app.auth.dominio_email import dominio_aceita_email


class LoginForm(FlaskForm):
    email = StringField("E-mail", validators=[DataRequired(), Email()])
    password = PasswordField("Senha", validators=[DataRequired()])
    remember = BooleanField("Lembrar de mim")
    submit = SubmitField("Entrar")


class RegisterForm(FlaskForm):
    username = StringField("Usuario", validators=[DataRequired(), Length(min=3, max=80)])
    email = StringField("E-mail", validators=[DataRequired(), Email()])
    password = PasswordField("Senha", validators=[DataRequired(), Length(min=8)])
    confirm = PasswordField(
        "Confirme a senha",
        validators=[DataRequired(), EqualTo("password", message="As senhas devem coincidir.")],
    )
    submit = SubmitField("Cadastrar")

    def validate_username(self, field):
        if User.query.filter_by(username=field.data).first():
            raise ValidationError("Este nome de usuario ja esta em uso.")

    def validate_email(self, field):
        if User.query.filter_by(email=field.data).first():
            raise ValidationError(
                "Este e-mail ja esta cadastrado. Faca login ou use 'Entrar com o Google'."
            )

        if current_app.config.get("VALIDAR_DOMINIO_EMAIL", True):
            dominio = field.data.rsplit("@", 1)[-1]
            if not dominio_aceita_email(dominio):
                raise ValidationError(
                    "Nao conseguimos confirmar que esse dominio de e-mail existe. Confira se digitou certo."
                )


class ReenviarConfirmacaoForm(FlaskForm):
    """E-mail vem oculto/pre-preenchido -- a pessoa ja digitou no
    cadastro/login, aqui e so um botao de 'reenviar' (ver app/auth/routes.py)."""
    email = HiddenField(validators=[DataRequired(), Email()])
    submit = SubmitField("Reenviar e-mail de confirmacao")
