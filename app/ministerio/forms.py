"""Formularios Flask-WTF do modulo ministerio."""
from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed, FileSize
from wtforms import StringField, TextAreaField, SubmitField
from wtforms.validators import DataRequired, Length, Optional


class MinisterioForm(FlaskForm):
    nome = StringField("Nome do ministerio", validators=[DataRequired(), Length(max=120)])
    descricao = TextAreaField("Descricao", validators=[Optional(), Length(max=2000)])
    imagem = FileField(
        "Icone/imagem (opcional)",
        validators=[
            Optional(),
            FileAllowed(["jpg", "jpeg", "png"], "Envie apenas arquivos JPG ou PNG."),
            FileSize(max_size=2 * 1024 * 1024, message="A imagem deve ter no maximo 2 MB."),
        ],
    )
    submit = SubmitField("Salvar")
