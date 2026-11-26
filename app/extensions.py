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


def endereco_do_visitante():
    """IP real de quem pede, pro rate limit. Atras do Azure o remote_addr e o
    do proxy (igual pra todo mundo: "5 por hora" virava 5 por hora do site
    inteiro). Vale so o ULTIMO item do X-Forwarded-For, que e o que o Azure
    acrescenta -- os anteriores o visitante consegue inventar. O Azure manda
    "ip:porta", e a porta muda a cada conexao, entao sai."""
    from flask import request

    ip = (request.headers.get("X-Forwarded-For") or "").split(",")[-1].strip()
    if ip.startswith("["):  # [ipv6]:porta
        ip = ip[1:].split("]")[0]
    elif ip.count(":") == 1:  # ipv4:porta
        ip = ip.split(":")[0]
    return ip or get_remote_address()


limiter = Limiter(key_func=endereco_do_visitante)
