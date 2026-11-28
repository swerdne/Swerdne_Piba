from flask import Blueprint

bp = Blueprint("escala", __name__)

from . import routes  # noqa: E402  (importado no fim para evitar ciclo)
from . import qr  # noqa: E402,F401  (rotas do check-in por QR)
