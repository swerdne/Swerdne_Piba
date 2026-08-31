"""Formularios Flask-WTF do modulo comunidade."""
from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed, FileSize
from wtforms import StringField, TextAreaField, SubmitField, DateField
from wtforms.validators import DataRequired, Length, Optional, Email


class ComunidadeForm(FlaskForm):
    nome = StringField("Nome da comunidade", validators=[DataRequired(), Length(max=120)])
    descricao = TextAreaField("Descricao", validators=[Optional(), Length(max=2000)])
    imagem = FileField(
        "Logo (opcional)",
        validators=[
            Optional(),
            FileAllowed(["jpg", "jpeg", "png"], "Envie apenas arquivos JPG ou PNG."),
            FileSize(max_size=2 * 1024 * 1024, message="A imagem deve ter no maximo 2 MB."),
        ],
    )
    submit = SubmitField("Salvar")


class MembroDiretorioForm(FlaskForm):
    nome = StringField("Nome", validators=[DataRequired(), Length(max=120)])
    telefone = StringField("Telefone", validators=[Optional(), Length(max=30)])
    email = StringField("E-mail", validators=[Optional(), Email(), Length(max=120)])
    submit = SubmitField("Adicionar ao diretorio")


class CicloDisponibilidadeForm(FlaskForm):
    """So o cabecalho do ciclo -- os segmentos (nome/duracao/indisponivel,
    quantidade variavel) sao lidos direto de request.form em
    comunidade.routes.nova_disponibilidade (indexados segmento_nome_<i> etc,
    ver o JS de adicionar/remover linha em comunidade/disponibilidade.html)."""
    nome = StringField("Nome do ciclo", validators=[DataRequired(), Length(max=80)])
    data_inicio = DateField("Data de inicio (ancora do ciclo)", validators=[DataRequired()])
    submit = SubmitField("Salvar ciclo")


class AcaoForm(FlaskForm):
    """Form vazio, usado so para validar o token CSRF em acoes simples (excluir)."""
    pass
