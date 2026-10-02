"""Paginas de erro estilizadas (404, 403, 500 e fallback generico pra outros codigos)."""
from urllib.parse import urlsplit

from flask import render_template, flash, redirect, request, url_for
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

_FRASES_429 = [
    "Calma, uma coisa de cada vez -- tenta de novo daqui a pouco.",
    "Muitas tentativas seguidas. Espera um minuto e tenta outra vez.",
]

# Fallback de ultimo recurso pro erro 500: nao estende base.html nem usa o
# context processor de tema (que consulta o banco via current_user) -- se o
# banco estiver de fato fora do ar, erro.html tambem falharia ao renderizar,
# e sem isso o usuario cairia na tela crua e sem estilo padrao do Werkzeug.
_PAGINA_500_MINIMA = """<!DOCTYPE html>
<html lang="pt-br">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Erro 500 · TyBenson</title>
<style>
  body { margin:0; min-height:100vh; display:flex; align-items:center; justify-content:center;
         background:#0f172a; color:#e5e7eb; font-family:ui-sans-serif,system-ui,sans-serif; padding:24px; }
  .caixa { max-width:28rem; text-align:center; }
  .codigo { font-size:.75rem; font-weight:600; color:#818cf8; text-transform:uppercase; letter-spacing:.05em; }
  h1 { margin:.5rem 0 0; font-size:1.5rem; font-weight:700; color:#f9fafb; }
  p { margin-top:.75rem; color:#9ca3af; }
  a { display:inline-flex; margin-top:2rem; background:#4f46e5; color:#fff; text-decoration:none;
      font-size:.875rem; font-weight:600; padding:.625rem 1.25rem; border-radius:.5rem; }
</style>
</head>
<body>
  <div class="caixa">
    <p class="codigo">Erro 500</p>
    <h1>Algo deu errado no servidor</h1>
    <p>Nosso servidor tambem tem dias dificeis. Ja fomos avisados.</p>
    <a href="/">Voltar para o inicio</a>
  </div>
</body>
</html>"""


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
        # A excecao original pode ter deixado a sessao do SQLAlchemy (ainda
        # usada pelo /healthz e enquanto o Postgres nao e desligado de vez,
        # ver plano da migracao pra Mongo) num estado pendente de rollback --
        # limpeza defensiva, mesmo que a maioria das requisicoes hoje em dia
        # nao toque mais o Postgres (User/Comunidade/Escala/etc. ja sao
        # MongoEngine). Se o banco estiver de fato inacessivel, o proprio
        # rollback() pode levantar -- sem o try/except, isso derruba essa
        # pagina de erro tambem, e o usuario cai na tela crua e sem estilo
        # do Werkzeug em vez desta aqui.
        try:
            db.session.rollback()
        except Exception:
            pass
        try:
            return render_template(
                "errors/erro.html",
                codigo=500,
                titulo="Algo deu errado no servidor",
                frases=_FRASES_500,
                icone="fa-triangle-exclamation",
            ), 500
        except Exception:
            # erro.html estende base.html -- se ALGO falhar ao renderizar
            # (motivo qualquer, nao mais especificamente o Postgres), cai
            # aqui, na versao minima que nao depende de nenhum banco.
            return _PAGINA_500_MINIMA, 500

    @app.errorhandler(429)
    def erro_429(error):
        return render_template(
            "errors/erro.html",
            codigo=429,
            titulo="Muitas tentativas",
            frases=_FRASES_429,
            icone="fa-hourglass-half",
        ), 429

    @app.errorhandler(413)
    def arquivo_grande_demais(error):
        """Upload acima de MAX_CONTENT_LENGTH: o Flask recusa a requisicao
        inteira antes do formulario validar, entao a mensagem de tamanho do
        FileSize nunca chegava a aparecer -- caia na pagina de erro. Volta
        pra mesma tela com o aviso (so referrer do proprio site)."""
        if request.path.endswith("/anexos"):
            flash("O arquivo deve ter no maximo 10 MB.", "danger")
        else:
            flash("A imagem deve ter no maximo 2 MB.", "danger")
        destino = url_for("main.dashboard")
        origem = urlsplit(request.referrer or "")
        if origem.path and origem.netloc in ("", request.host):
            destino = origem.path + ("?" + origem.query if origem.query else "")
        if destino.rstrip("/").endswith("/dashboard"):
            destino += "#config"
        return redirect(destino)

    @app.errorhandler(HTTPException)
    def erro_http_generico(error):
        return render_template(
            "errors/erro.html",
            codigo=error.code,
            titulo=error.name,
            frases=_FRASES_GENERICO,
            icone="fa-circle-exclamation",
        ), error.code
