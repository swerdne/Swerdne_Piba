"""Paginas de erro estilizadas (404, 403, 500 e fallback generico pra outros codigos)."""
from flask import render_template
from werkzeug.exceptions import HTTPException

from .extensions import db

_FRASES_404 = [
    "Parece que essa escala se perdeu no caminho...",
    "Procuramos em todos os ministerios e essa pagina nao esta escalada pra hoje.",
    "Essa rota nao apareceu na lista de presenca.",
    "Nem o rodizio automatico encontrou essa pagina por aqui.",
]

_FRASES_403 = [
    "Essa area e reservada pra quem tem papel liberado por aqui.",
    "Parece que voce ainda nao foi convidado pra essa parte.",
    "So quem esta escalado nesse ministerio entra por aqui.",
]

_FRASES_500 = [
    "Alguem esqueceu de notificar o servidor a tempo -- ja estamos resolvendo.",
    "Deu um branco aqui do nosso lado, igual quando esquece a letra do louvor.",
    "O sistema pediu uma pausa e ja volta pro proximo turno.",
    "Nosso servidor tambem tem dias dificeis. Ja fomos avisados.",
]

_FRASES_GENERICO = [
    "Algo saiu diferente do que estava na escala.",
]


def registrar_error_handlers(app):
    @app.errorhandler(404)
    def erro_404(error):
        return render_template(
            "errors/erro.html",
            codigo=404,
            titulo="Pagina nao encontrada",
            frases=_FRASES_404,
            icone="fa-compass",
        ), 404

    @app.errorhandler(403)
    def erro_403(error):
        return render_template(
            "errors/erro.html",
            codigo=403,
            titulo="Sem permissao",
            frases=_FRASES_403,
            icone="fa-lock",
        ), 403

    @app.errorhandler(500)
    def erro_500(error):
        # A excecao original pode ter deixado a sessao do banco num estado
        # pendente de rollback -- sem isso, ate o carregamento do usuario
        # logado (current_user, usado pelo tema via context processor) pode
        # falhar de novo so de tentar renderizar essa propria pagina.
        db.session.rollback()
        return render_template(
            "errors/erro.html",
            codigo=500,
            titulo="Algo deu errado no servidor",
            frases=_FRASES_500,
            icone="fa-triangle-exclamation",
        ), 500

    @app.errorhandler(HTTPException)
    def erro_http_generico(error):
        return render_template(
            "errors/erro.html",
            codigo=error.code,
            titulo=error.name,
            frases=_FRASES_GENERICO,
            icone="fa-circle-exclamation",
        ), error.code
