"""Formularios Flask-WTF do modulo main."""
from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed, FileRequired, FileSize
from wtforms import StringField, TextAreaField, SubmitField, RadioField
from wtforms.validators import DataRequired, Length

from app.main.themes import THEMES


class ItemForm(FlaskForm):
    titulo = StringField("Titulo", validators=[DataRequired(), Length(max=120)])
    descricao = TextAreaField("Descricao")
    submit = SubmitField("Salvar")


class FotoPerfilForm(FlaskForm):
    foto = FileField(
        "Foto de perfil",
        validators=[
            FileRequired(message="Escolha uma imagem."),
            FileAllowed(["jpg", "jpeg", "png"], "Envie apenas arquivos JPG ou PNG."),
            FileSize(max_size=2 * 1024 * 1024, message="A imagem deve ter no maximo 2 MB."),
        ],
    )
    submit = SubmitField("Salvar foto")


class TemaForm(FlaskForm):
    tema = RadioField(
        "Tema",
        choices=[(chave, dado["label"]) for chave, dado in THEMES.items()],
        validators=[DataRequired()],
    )
    submit = SubmitField("Salvar tema")


class AcaoForm(FlaskForm):
    """Form vazio (so CSRF) -- mesmo padrao usado em outros blueprints pra
    acoes simples de POST (ver comunidade/ministerio/escala/plantao)."""
    pass
