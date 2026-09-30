"""Formularios Flask-WTF do modulo escala."""
from flask_wtf import FlaskForm
from wtforms import StringField, SelectField, SubmitField, DateField, TimeField, TextAreaField
from wtforms.validators import DataRequired, Length, Optional

from app.escala.models import DEPARTAMENTOS, CORES_DISPONIVEIS

# "" (vazio) = usa a cor padrao do departamento (Escala.cor_selecionada fica
# None) -- sempre a 1a opcao, pra nao forcar o usuario a escolher uma cor.
_CHOICES_COR = [("", "Cor do departamento (padrao)")] + [(chave, chave.capitalize()) for chave in CORES_DISPONIVEIS]


class EscalaForm(FlaskForm):
    nome = StringField("Nome da escala", validators=[DataRequired(), Length(max=80)])
    departamento = SelectField(
        "Departamento",
        choices=[(d, d) for d in DEPARTAMENTOS.keys()],
        validators=[DataRequired()],
    )
    data = DateField("Data do ensaio/evento", validators=[Optional()])
    horario = TimeField("Horario de inicio", validators=[Optional()])
    horario_fim = TimeField("Horario de fim", validators=[Optional()])
    cor = SelectField("Cor na lista e no calendario", choices=_CHOICES_COR, validators=[Optional()])
    submit = SubmitField("Criar escala")


class EditarEscalaForm(FlaskForm):
    nome = StringField("Nome da escala", validators=[DataRequired(), Length(max=80)])
    data = DateField("Data do ensaio/evento", validators=[Optional()])
    horario = TimeField("Horario de inicio", validators=[Optional()])
    horario_fim = TimeField("Horario de fim", validators=[Optional()])
    cor = SelectField("Cor na lista e no calendario", choices=_CHOICES_COR, validators=[Optional()])
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
    # Preenchidos so quando status == "troca_solicitada" (ver
    # escala.routes::atualizar_status) -- Optional() nos dois porque sugerir
    # substituto e explicar o motivo sao opcionais pra quem pede a troca.
    troca_motivo = TextAreaField("Motivo (opcional)", validators=[Optional(), Length(max=500)])
    troca_sugestao_membro_id = SelectField(
        "Sugerir substituto (opcional)", coerce=int, validators=[Optional()]
    )


class TrocaAprovarForm(FlaskForm):
    """Usado pelo lider/admin pra aprovar uma solicitacao de troca (ver
    escala.routes::aprovar_troca) -- escolhe quem assume a funcao. Vem
    pre-preenchido com a sugestao de quem pediu a troca, se houver, mas o
    lider pode trocar por qualquer outra pessoa do diretorio."""
    membro_id = SelectField("Quem assume a funcao", coerce=int, validators=[DataRequired()])
    submit = SubmitField("Aprovar troca")


class AcaoForm(FlaskForm):
    """Form vazio, usado so para validar o token CSRF em acoes simples (remover/notificar)."""
    pass


class FuncaoForm(FlaskForm):
    nome = StringField("Nome da funcao", validators=[DataRequired(), Length(max=80)])
    submit = SubmitField("Salvar")


class ItemRepertorioForm(FlaskForm):
    nome_musica = StringField("Nome da musica", validators=[DataRequired(), Length(max=150)])
    tom = StringField("Tom", validators=[Optional(), Length(max=10)])
    link = StringField("Link (cifra, video...)", validators=[Optional(), Length(max=500)])
    submit = SubmitField("Adicionar")
