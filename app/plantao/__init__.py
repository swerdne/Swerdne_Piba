"""Blueprint: Plantao (escala de rodizio dinamico dentro de um Ministerio)."""
from flask import Blueprint

bp = Blueprint("plantao", __name__)

from . import routes  # noqa: E402
