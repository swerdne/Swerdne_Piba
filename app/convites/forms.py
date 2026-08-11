"""Formularios Flask-WTF do modulo convites."""
from flask_wtf import FlaskForm
from wtforms import StringField, SelectField, SubmitField
from wtforms.validators import DataRequired, Email, Length


class ConvidarForm(FlaskForm):
    """Choices de `papel` sao montadas pela rota (dependem de quem esta
    convidando -- ver comunidade.routes._papeis_convidaveis_na_comunidade e
    ministerio.routes._papeis_convidaveis_no_ministerio)."""
    email = StringField("E-mail", validators=[DataRequired(), Email(), Length(max=120)])
    papel = SelectField("Papel", choices=[], validators=[DataRequired()])
    submit = SubmitField("Enviar convite")


class AcaoForm(FlaskForm):
    """Form vazio, usado so para validar o token CSRF em acoes simples (aceitar/recusar/remover)."""
    pass
