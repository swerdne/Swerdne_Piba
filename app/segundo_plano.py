"""Trabalho que nao precisa segurar a resposta da tela (avisos por
WhatsApp/e-mail/SMS, baixar audio do WhatsApp...)."""
import threading

from flask import current_app


def em_segundo_plano(funcao, *args, rotulo="Tarefa em segundo plano"):
    """Roda `funcao(*args)` numa thread, sem atrasar a resposta. Em teste
    roda na hora (o teste ve o resultado sem esperar thread).

    Com um request de mentira apontando pro URL_PUBLICA (nao so app
    context): varias tarefas montam links com url_for, que fora de um
    request quebra. Mesmo contexto na hora e em thread, pra o teste pegar
    isso. Passe ids (nao objetos do banco) e busque de novo dentro da
    tarefa: a thread nao deve reaproveitar objetos da requisicao."""
    app = current_app._get_current_object()
    base = app.config.get("URL_PUBLICA") or "http://localhost"

    def trabalho():
        with app.test_request_context("/", base_url=base):
            try:
                funcao(*args)
            except Exception:
                app.logger.exception("%s falhou", rotulo)

    if app.testing:
        trabalho()
    else:
        threading.Thread(target=trabalho, daemon=True).start()
