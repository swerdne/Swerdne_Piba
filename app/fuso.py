"""Hora de Brasilia, sem depender do fuso do servidor.

Escala.data/horario sao gravados como hora LOCAL de Brasilia (naive). O
servidor do Azure roda em UTC: comparar com datetime.now() deixava o
agendador 3h adiantado (avisos de 24h/16h saiam 27h/19h antes) e o rodizio
achando que um evento ja tinha passado 3h antes da hora. Offset fixo de -3h,
mesmo criterio do resto do projeto (Brasil sem horario de verao desde 2019).
"""
from datetime import datetime, timedelta, timezone

OFFSET_BRASILIA = timedelta(hours=-3)


def agora_brasilia():
    """datetime naive na hora de Brasilia -- comparavel com Escala.data_hora."""
    return (datetime.now(timezone.utc) + OFFSET_BRASILIA).replace(tzinfo=None)


def hoje_brasilia():
    return agora_brasilia().date()
