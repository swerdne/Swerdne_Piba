"""Model (M do MVC): entidade User (MongoDB, ver app/db_utils.py)."""
import mongoengine
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from app.extensions import login_manager
from app.db_utils import SequentialIdDocument


class User(UserMixin, SequentialIdDocument):
    meta = {"collection": "users"}
    _nome_sequencia = "usuarios"

    # Comuns a qualquer forma de cadastro
    email = mongoengine.StringField(required=True, unique=True, max_length=120)
    name = mongoengine.StringField(max_length=120)
    foto_perfil = mongoengine.StringField(max_length=500)

    # Especificos do cadastro tradicional (email/senha). sparse=True: sem
    # isso, o indice unico rejeitaria a segunda conta sem username (varias
    # contas via Google nunca tem esse campo, ver google_callback).
    username = mongoengine.StringField(unique=True, sparse=True, max_length=80)
    password_hash = mongoengine.StringField(max_length=255)

    # Especifico do login social (Google OAuth)
    google_id = mongoengine.StringField(unique=True, sparse=True, max_length=255)

    # Preferencia de aparencia do dashboard (ver app/main/themes.py)
    theme = mongoengine.StringField(default="indigo", max_length=20)

    # Tutoriais guiados (spotlight) ja vistos -- chaves de app/tutoriais.py
    # ("comunidade", "ministerio", "escala", "banco"). Cada um comeca sozinho
    # uma vez so, pra conta inteira (nao repete por comunidade/escala).
    tutoriais_vistos = mongoengine.ListField(mongoengine.StringField(max_length=40))
    # Flag do 1o tutorial (so da Comunidade), antes de tutoriais_vistos.
    # Sem uso: o tutorial da Comunidade foi refeito e aparece de novo uma vez.
    tutorial_comunidade_visto = mongoengine.BooleanField(default=False)

    # Preferencia de privacidade (aba Configuracoes): desligada (padrao),
    # admin/lider adiciona a conta direto numa Comunidade/Ministerio, sem
    # aceite; ligada, toda adicao vira um Convite que a pessoa aceita ou
    # recusa. So vale pra adicoes futuras -- nunca remove de grupo nenhum.
    # Ver app/convites/adicao.py.
    exige_aprovacao_grupos = mongoengine.BooleanField(default=False)

    # Acesso total a plataforma (gerencia qualquer Comunidade/Ministerio,
    # bypassa toda checagem de posse/papel) -- NUNCA atribuivel por convite
    # comum (ver app/convites/CLAUDE.md), so pelo comando
    # `flask criar-super-admin <email>` (app/__init__.py), que exige acesso
    # ao servidor/terminal.
    eh_super_admin = mongoengine.BooleanField(default=False)

    # Ex-confirmacao de e-mail por link (removida -- cadastro tradicional
    # agora loga direto, igual Google). Campo mantido sem uso ativo (mesma
    # razao de antes no Postgres); sempre True em conta nova (ver
    # auth/routes.py::register e google_callback, que passam o valor
    # explicito -- o default aqui so importa se algum dia pararem de passar).
    email_confirmado = mongoengine.BooleanField(default=False)
    token_confirmacao = mongoengine.StringField(unique=True, sparse=True, max_length=64)
    token_confirmacao_expira_em = mongoengine.DateTimeField()

    # Redefinicao de senha por link de e-mail ("esqueci minha senha", ver
    # app/auth/routes.py::esqueci_senha/redefinir_senha) -- token de uso
    # unico, expira sozinho (checado na hora de validar, nao precisa de job).
    # Campo separado de token_confirmacao de proposito: sao fluxos
    # diferentes (confirmar posse do e-mail vs provar que ainda tem acesso a
    # ele pra trocar a senha), nao faz sentido reaproveitar o mesmo.
    token_redefinicao_senha = mongoengine.StringField(unique=True, sparse=True, max_length=64)
    token_redefinicao_expira_em = mongoengine.DateTimeField()

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        # Usuarios criados via Google nao possuem password_hash
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    def viu_tutorial(self, chave):
        return chave in (self.tutoriais_vistos or [])

    def __repr__(self):
        return f"<User {self.username}>"


@login_manager.user_loader
def load_user(user_id):
    return User.objects(id=int(user_id)).first()
