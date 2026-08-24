"""Instancias das extensoes Flask, sem vincular ao app (evita import circular)."""
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from authlib.integrations.flask_client import OAuth
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = "Faca login para acessar esta pagina."
oauth = OAuth()

# Protecao contra forca bruta (login/cadastro/reenvio de confirmacao) -- ver
# app/auth/routes.py pelos limites especificos de cada rota. Armazenamento em
# memoria por padrao: funciona bem com o processo unico atual (mesma
# ressalva ja documentada pro scheduler em app/escala/agendador.py -- nao ha
# ainda protecao contra multiplos workers/processos duplicando o contador).
limiter = Limiter(key_func=get_remote_address)
