"""Formularios Flask-WTF do modulo main."""
from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed, FileRequired, FileSize
from wtforms import StringField, TextAreaField, SubmitField, RadioField, PasswordField
from wtforms.validators import DataRequired, Length, EqualTo

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


class NomeForm(FlaskForm):
    nome = StringField("Nome de exibicao", validators=[DataRequired(), Length(max=120)])
    submit = SubmitField("Salvar nome")


class TrocarSenhaForm(FlaskForm):
    # senha_atual sem DataRequired de proposito -- conta criada so via Google
    # nao tem senha ainda (ver User.password_hash), entao "definir senha pela
    # primeira vez" nao tem o que conferir. A rota decide se exige esse campo
    # (User.password_hash existente) e confere o valor com check_password.
    senha_atual = PasswordField("Senha atual")
    nova_senha = PasswordField("Nova senha", validators=[DataRequired(), Length(min=8)])
    confirmar_senha = PasswordField(
        "Confirme a nova senha",
        validators=[DataRequired(), EqualTo("nova_senha", message="As senhas devem coincidir.")],
    )
    submit = SubmitField("Salvar senha")


class AcaoForm(FlaskForm):
    """Form vazio (so CSRF) -- mesmo padrao usado em outros blueprints pra
    acoes simples de POST (ver comunidade/ministerio/escala/plantao)."""
    pass
