"""Blueprint: Ministerio (area de escalas dentro de uma Comunidade)."""
from flask import Blueprint

bp = Blueprint("ministerio", __name__)

from . import routes  # noqa: E402
