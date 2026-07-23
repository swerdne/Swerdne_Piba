"""Formularios Flask-WTF do modulo plantao."""
from flask_wtf import FlaskForm
from wtforms import StringField, SelectField, DateField, TimeField, SubmitField
from wtforms.validators import DataRequired, Length, Optional

from app.escala.models import DEPARTAMENTOS
from app.plantao.models import RECORRENCIAS


class TurnoPlantaoForm(FlaskForm):
    nome = StringField("Nome do turno", validators=[DataRequired(), Length(max=80)])
    departamento = SelectField(
        "Departamento",
        choices=[(d, d) for d in DEPARTAMENTOS.keys()],
        validators=[DataRequired()],
    )
    nome_funcao = StringField(
        "Nome do papel gerado em cada ocorrencia",
        validators=[DataRequired(), Length(max=80)],
        default="Responsavel",
    )
    data_inicio = DateField("Data de inicio do rodizio", validators=[DataRequired()])
    horario = TimeField("Horario de inicio de cada plantao", validators=[Optional()])
    recorrencia = SelectField(
        "Recorrencia",
        choices=[("diaria", "Diaria"), ("semanal", "Semanal"), ("mensal", "Mensal")],
        validators=[DataRequired()],
    )
    submit = SubmitField("Salvar")

    def validate_recorrencia(self, field):
        if field.data not in RECORRENCIAS:
            raise ValueError("Recorrencia invalida.")


class AdicionarMembroFilaForm(FlaskForm):
    membro_id = SelectField("Pessoa", coerce=int, validators=[DataRequired()])
    submit = SubmitField("Adicionar a fila")


class AcaoForm(FlaskForm):
    """Form vazio, usado so para validar o token CSRF em acoes simples."""
    pass
