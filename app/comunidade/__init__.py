"""Blueprint: Comunidade (camada organizacional acima da Escala Rapida)."""
from flask import Blueprint

bp = Blueprint("comunidade", __name__)

from . import routes  # noqa: E402
