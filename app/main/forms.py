"""Formularios Flask-WTF do modulo main."""
from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed, FileRequired, FileSize
from wtforms import BooleanField, StringField, TextAreaField, SubmitField, RadioField, PasswordField, DateField
from wtforms.validators import DataRequired, Length, EqualTo, Optional, ValidationError

from app.main.themes import THEMES
from app.telefones import validar_telefone


class ItemForm(FlaskForm):
    titulo = StringField("Título", validators=[DataRequired(), Length(max=120)])
    descricao = TextAreaField("Descrição")
    submit = SubmitField("Salvar")


class FotoPerfilForm(FlaskForm):
    foto = FileField(
        "Foto de perfil",
        validators=[
            FileRequired(message="Escolha uma imagem."),
            FileAllowed(["jpg", "jpeg", "png"], "Envie apenas arquivos JPG ou PNG."),
            FileSize(max_size=2 * 1024 * 1024, message="A imagem deve ter no máximo 2 MB."),
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


class PrivacidadeForm(FlaskForm):
    exige_aprovacao_grupos = BooleanField("Exigir minha aprovação antes de ser adicionado(a) a um grupo")
    telefone_visivel_lider = BooleanField("Líderes dos meus ministérios podem ver meu telefone")
    submit = SubmitField("Salvar privacidade")


class TelefoneForm(FlaskForm):
    telefone = StringField(
        "Telefone (WhatsApp)",
        validators=[Optional(), Length(max=30), validar_telefone],
    )
    submit = SubmitField("Salvar telefone")


class NomeForm(FlaskForm):
    nome = StringField("Nome de exibição", validators=[DataRequired(), Length(max=120)])
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


class IndisponibilidadeForm(FlaskForm):
    """Perfil > Datas indisponiveis (escala.models.Indisponibilidade)."""
    data_inicio = DateField("De", validators=[DataRequired(message="Escolha a data.")])
    data_fim = DateField("Até (opcional)", validators=[Optional()])
    motivo = StringField("Motivo (opcional)", validators=[Optional(), Length(max=120)])

    def validate_data_fim(self, campo):
        if campo.data and self.data_inicio.data and campo.data < self.data_inicio.data:
            raise ValidationError("A data final não pode ser antes da inicial.")


class LembretesForm(FlaskForm):
    """Perfil > Lembretes: por onde chegam os lembretes automaticos das escalas."""
    lembrete_whatsapp = BooleanField("WhatsApp e SMS")
    lembrete_email = BooleanField("E-mail")
    lembrete_1h_whatsapp = BooleanField("Também no lembrete de 1 hora antes")
    submit = SubmitField("Salvar lembretes")
