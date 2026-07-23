"""Formularios Flask-WTF do modulo escala."""
from flask_wtf import FlaskForm
from wtforms import StringField, SelectField, SubmitField, DateField, TimeField
from wtforms.validators import DataRequired, Length, Optional

from app.escala.models import DEPARTAMENTOS


class EscalaForm(FlaskForm):
    nome = StringField("Nome da escala", validators=[DataRequired(), Length(max=80)])
    departamento = SelectField(
        "Departamento",
        choices=[(d, d) for d in DEPARTAMENTOS.keys()],
        validators=[DataRequired()],
    )
    data = DateField("Data do ensaio/evento", validators=[Optional()])
    horario = TimeField("Horario do ensaio/evento", validators=[Optional()])
    submit = SubmitField("Criar escala")


class EditarEscalaForm(FlaskForm):
    nome = StringField("Nome da escala", validators=[DataRequired(), Length(max=80)])
    data = DateField("Data do ensaio/evento", validators=[Optional()])
    horario = TimeField("Horario do ensaio/evento", validators=[Optional()])
    submit = SubmitField("Salvar")


class SelecionarMembroForm(FlaskForm):
    """Escala alguem ja cadastrado no diretorio da comunidade (ver app/comunidade)."""
    membro_id = SelectField("Pessoa", coerce=int, validators=[DataRequired()])
    submit = SubmitField("Adicionar")


class MoverForm(FlaskForm):
    destino_funcao_id = SelectField("Mover para", coerce=int, validators=[DataRequired()])
    submit = SubmitField("Mover")


class StatusForm(FlaskForm):
    status = SelectField(
        "Status",
        choices=[
            ("nao_notificado", "Nao notificado"),
            ("confirmado", "Confirmado"),
            ("presente", "Presente"),
            ("troca_solicitada", "Troca solicitada"),
        ],
        validators=[DataRequired()],
    )


class AcaoForm(FlaskForm):
    """Form vazio, usado so para validar o token CSRF em acoes simples (remover/notificar)."""
    pass


class FuncaoForm(FlaskForm):
    nome = StringField("Nome da funcao", validators=[DataRequired(), Length(max=80)])
    submit = SubmitField("Salvar")
