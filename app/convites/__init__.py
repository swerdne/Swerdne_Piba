"""Blueprint: Convite (aceitar/recusar convite de papel numa Comunidade/Ministerio).

O ENVIO de convite mora nos blueprints donos do escopo (comunidade.routes,
ministerio.routes) -- este modulo cuida so do lado de quem RECEBE o convite
(link por e-mail, tela de aceitar/recusar), que e generico o suficiente
(qualquer escopo) pra nao pertencer a nenhum dos dois."""
from flask import Blueprint

bp = Blueprint("convites", __name__)

from . import routes  # noqa: E402
