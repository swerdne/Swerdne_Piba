"""Configuracao do gunicorn, lida sozinha quando o Azure roda `gunicorn ...`
na pasta do app (opcoes passadas na linha de comando tem prioridade).

1 processo de proposito: o agendador (app/escala/agendador.py) roda dentro
dele, e 2+ processos mandariam cada aviso em dobro. As threads deixam o
mesmo processo atender varias pessoas ao mesmo tempo -- quase todo o tempo de
uma tela e esperando o MongoDB responder, e sem elas uma tela lenta segurava
todo mundo na fila.
"""
workers = 1
worker_class = "gthread"
threads = 8
timeout = 120
keepalive = 5
