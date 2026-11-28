"""Formularios Flask-WTF do modulo ministerio."""
from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed, FileSize
from wtforms import StringField, TextAreaField, SubmitField, SelectField, SelectMultipleField, DateField, TimeField
from wtforms.validators import DataRequired, Length, Optional
from wtforms.widgets import ListWidget, CheckboxInput

# Mesma convencao de app/plantao/forms.py::DIAS_SEMANA_CHOICES (0=segunda..
# 6=domingo) -- duplicado aqui em vez de importado pra nao inverter a
# dependencia natural entre os modulos (ministerio e mais "de baixo" que
# plantao, que referencia ministerio_id).
DIAS_SEMANA_CHOICES = [
    (0, "Segunda"), (1, "Terça"), (2, "Quarta"), (3, "Quinta"),
    (4, "Sexta"), (5, "Sábado"), (6, "Domingo"),
]


class MinisterioForm(FlaskForm):
    nome = StringField("Nome do ministério", validators=[DataRequired(), Length(max=120)])
    descricao = TextAreaField("Descrição", validators=[Optional(), Length(max=2000)])
    # So um lembrete visual mostrado depois na tela de configurar o Rodizio
    # (ver Ministerio.dias_culto_efetivos) -- nunca obrigatorio.
    dias_culto = SelectMultipleField(
        "Dias que costuma ter culto", choices=DIAS_SEMANA_CHOICES, coerce=int, validators=[Optional()],
        widget=ListWidget(prefix_label=False), option_widget=CheckboxInput(),
    )
    imagem = FileField(
        "Icone/imagem (opcional)",
        validators=[
            Optional(),
            FileAllowed(["jpg", "jpeg", "png"], "Envie apenas arquivos JPG ou PNG."),
            FileSize(max_size=2 * 1024 * 1024, message="A imagem deve ter no máximo 2 MB."),
        ],
    )
    submit = SubmitField("Salvar")


class LembreteForm(FlaskForm):
    """Quando sai o lembrete automatico principal das escalas do ministerio
    (ver ministerio.routes.lembrete e escala.models.momento_do_lembrete)."""
    dias_antes = SelectField(
        "Quantos dias antes do evento",
        choices=[(1, "1 dia antes (véspera)")] + [(n, f"{n} dias antes") for n in range(2, 8)],
        coerce=int, default=1,
    )
    horario = TimeField("Horário do envio", validators=[Optional()])
    submit = SubmitField("Salvar lembrete")


class AcaoForm(FlaskForm):
    """Form vazio, usado so para validar o token CSRF em acoes simples (excluir)."""
    pass


class CriancaForm(FlaskForm):
    nome = StringField("Nome da criança", validators=[DataRequired(), Length(max=120)])
    data_nascimento = DateField("Data de nascimento (opcional)", validators=[Optional()])
    responsavel_nome = StringField("Nome do responsável", validators=[DataRequired(), Length(max=120)])
    responsavel_telefone = StringField("Telefone do responsável", validators=[Optional(), Length(max=30)])
    observacoes = TextAreaField(
        "Observações (alergias, necessidades especiais...)", validators=[Optional(), Length(max=1000)]
    )
    submit = SubmitField("Cadastrar")


class CheckoutForm(FlaskForm):
    """Confere o codigo de seguranca entregue ao responsavel na entrada
    antes de liberar a crianca (ver ministerio.routes.fazer_checkout)."""
    codigo_seguranca = StringField("Código de segurança", validators=[DataRequired(), Length(max=6)])
    submit = SubmitField("Confirmar saída")
