"""Formularios Flask-WTF do modulo auth."""
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, SubmitField
from wtforms.validators import DataRequired, Email, Length, EqualTo, ValidationError

from app.auth.models import User


class LoginForm(FlaskForm):
    email = StringField("E-mail", validators=[DataRequired(), Email()])
    password = PasswordField("Senha", validators=[DataRequired()])
    remember = BooleanField("Lembrar de mim")
    submit = SubmitField("Entrar")


class RegisterForm(FlaskForm):
    username = StringField("Usuario", validators=[DataRequired(), Length(min=3, max=80)])
    email = StringField("E-mail", validators=[DataRequired(), Email()])
    password = PasswordField("Senha", validators=[DataRequired(), Length(min=6)])
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
