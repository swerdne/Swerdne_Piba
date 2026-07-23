"""Agendador de notificacoes automaticas da Escala (24h/16h antes).

Roda em background DENTRO do processo do Flask (nao existe worker/cron
separado neste projeto ainda) -- so dispara enquanto o servidor estiver
no ar no horario exato da janela de verificacao.

Unico agendador do projeto: alem de notificar, cada tick primeiro sincroniza
todo Turno de Rodizio (ver app/plantao/sincronizacao.py) -- materializa as
proximas ocorrencias geradas por rodizio em Escala/Funcao reais, que dai
seguem pelo MESMO fluxo de notificacao abaixo. Nao existe mais um scheduler
separado para o plantao.
"""
import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger(__name__)

INTERVALO_VERIFICACAO_MINUTOS = 15
_JANELA = timedelta(minutes=15)


def _verificar_e_notificar(app):
    from app.extensions import db
    from app.escala.models import Escala
    from app.escala.routes import enviar_notificacoes_da_escala
    from app.plantao.sincronizacao import sincronizar_todos_os_turnos_ativos

    with app.app_context():
        sincronizar_todos_os_turnos_ativos()

        agora = datetime.now()
        escalas = Escala.query.filter(Escala.data.isnot(None)).all()

        for escala in escalas:
            data_hora = escala.data_hora
            if data_hora is None:
                continue

            faltam = data_hora - agora

            if escala.notificado_24h_em is None and abs(faltam - timedelta(hours=24)) <= _JANELA:
                logger.info("Notificacao automatica (24h antes): escala %s", escala.id)
                enviar_notificacoes_da_escala(escala)
                escala.notificado_24h_em = agora
                db.session.commit()

            if escala.notificado_16h_em is None and abs(faltam - timedelta(hours=16)) <= _JANELA:
                logger.info("Notificacao automatica (16h antes): escala %s", escala.id)
                enviar_notificacoes_da_escala(escala)
                escala.notificado_16h_em = agora
                db.session.commit()


def iniciar_agendador(app):
    """Inicia o agendador em background. Chamado uma vez pela Application Factory."""
    scheduler = BackgroundScheduler(timezone="America/Sao_Paulo")
    scheduler.add_job(
        func=lambda: _verificar_e_notificar(app),
        trigger="interval",
        minutes=INTERVALO_VERIFICACAO_MINUTOS,
        id="notificar_escalas_automaticamente",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Agendador de notificacoes automaticas iniciado (a cada %s min).",
                INTERVALO_VERIFICACAO_MINUTOS)
    return scheduler
