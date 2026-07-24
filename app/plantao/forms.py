"""Formularios Flask-WTF do modulo plantao."""
from flask_wtf import FlaskForm
from wtforms import (
    StringField,
    SelectField,
    SelectMultipleField,
    RadioField,
    IntegerField,
    DateField,
    TimeField,
    SubmitField,
)
from wtforms.validators import DataRequired, Length, Optional, NumberRange, ValidationError
from wtforms.widgets import ListWidget, CheckboxInput

from app.escala.models import DEPARTAMENTOS
from app.plantao.models import UNIDADES_RECORRENCIA, MODOS_MENSAIS, TERMINOS

DIAS_SEMANA_CHOICES = [
    (0, "Segunda"), (1, "Terca"), (2, "Quarta"), (3, "Quinta"),
    (4, "Sexta"), (5, "Sabado"), (6, "Domingo"),
]


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

    # "Repetir a cada [N] [unidade]" -- estilo Google Agenda.
    intervalo_recorrencia = IntegerField(
        "Repetir a cada", default=1, validators=[DataRequired(), NumberRange(min=1)]
    )
    unidade_recorrencia = SelectField(
        "Unidade",
        choices=[("dia", "Dia(s)"), ("semana", "Semana(s)"), ("mes", "Mes(es)"), ("ano", "Ano(s)")],
        validators=[DataRequired()],
    )
    # So usado quando unidade_recorrencia == "semana". Vazio -> cai no
    # weekday de data_inicio (ver TurnoPlantao.dias_semana_efetivos).
    dias_semana = SelectMultipleField(
        "Dias da semana", choices=DIAS_SEMANA_CHOICES, coerce=int, validators=[Optional()],
        widget=ListWidget(prefix_label=False), option_widget=CheckboxInput(),
    )
    # So usado quando unidade_recorrencia == "mes". Choices montadas
    # dinamicamente pela rota a partir da data_inicio atual (ver routes.py) --
    # aqui so o default, pra o form nao quebrar antes da rota configurar.
    modo_mensal = RadioField("Repetir", choices=[], validators=[Optional()])

    termino_tipo = RadioField(
        "Termina",
        choices=[("nunca", "Nunca"), ("data", "Em uma data especifica"), ("ocorrencias", "Apos um numero de vezes")],
        default="nunca",
        validators=[DataRequired()],
    )
    termino_data = DateField("Data de termino", validators=[Optional()])
    termino_ocorrencias = IntegerField("Numero de ocorrencias", validators=[Optional(), NumberRange(min=1)])

    submit = SubmitField("Salvar")

    def validate_unidade_recorrencia(self, field):
        if field.data not in UNIDADES_RECORRENCIA:
            raise ValidationError("Unidade de recorrencia invalida.")

    def validate_modo_mensal(self, field):
        if self.unidade_recorrencia.data == "mes" and field.data not in MODOS_MENSAIS:
            raise ValidationError("Escolha como a recorrencia mensal se repete.")

    def validate_termino_tipo(self, field):
        if field.data not in TERMINOS:
            raise ValidationError("Opcao de termino invalida.")

    def validate_termino_data(self, field):
        if self.termino_tipo.data == "data" and not field.data:
            raise ValidationError("Escolha a data em que a recorrencia termina.")

    def validate_termino_ocorrencias(self, field):
        if self.termino_tipo.data == "ocorrencias" and not field.data:
            raise ValidationError("Informe apos quantas ocorrencias a recorrencia termina.")


class AdicionarMembroFilaForm(FlaskForm):
    membro_id = SelectField("Pessoa", coerce=int, validators=[DataRequired()])
    submit = SubmitField("Adicionar a fila")


class AcaoForm(FlaskForm):
    """Form vazio, usado so para validar o token CSRF em acoes simples."""
    pass
