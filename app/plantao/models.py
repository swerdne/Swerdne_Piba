"""Models (M do MVC): Escala de Plantao.

Rodizio dinamico por deslocamento (round-robin com offset): a fila de membros
de um turno e fixa, mas quem esta escalado num periodo N e sempre CALCULADO
pela formula (nunca decidido "do nada"). A formula em si (membro_do_periodo)
nao persiste nada -- quem persiste e o motor de sincronizacao (ver
app/plantao/sincronizacao.py), que materializa o resultado da formula em
Escala/Funcao reais (as mesmas do modulo app/escala), pra aparecer no
calendario/lista do Ministerio e usar a notificacao 24h/16h ja existente.
"""
import calendar
from datetime import date, datetime, timedelta, timezone

from app.extensions import db

RECORRENCIAS = ["diaria", "semanal", "mensal"]

JANELAS_NOTIFICACAO = {"24h": 24, "16h": 16}


def _somar_meses(data_base, n):
    """Soma `n` meses a `data_base`, ajustando o dia se o mes destino for mais curto
    (ex: dia 31 + 1 mes num mes de 30 dias vira dia 30)."""
    mes_total = data_base.month - 1 + n
    ano = data_base.year + mes_total // 12
    mes = mes_total % 12 + 1
    ultimo_dia_do_mes = calendar.monthrange(ano, mes)[1]
    dia = min(data_base.day, ultimo_dia_do_mes)
    return date(ano, mes, dia)


def _diferenca_em_meses(data_base, data):
    """Em que periodo mensal (contado a partir de data_base) a `data` cai."""
    meses = (data.year - data_base.year) * 12 + (data.month - data_base.month)
    dia_ancora = min(data_base.day, calendar.monthrange(data.year, data.month)[1])
    if data.day < dia_ancora:
        meses -= 1
    return meses


def data_do_periodo(turno, periodo):
    """Data em que o periodo N desse turno comeca."""
    if turno.recorrencia == "diaria":
        return turno.data_inicio + timedelta(days=periodo)
    if turno.recorrencia == "semanal":
        return turno.data_inicio + timedelta(weeks=periodo)
    if turno.recorrencia == "mensal":
        return _somar_meses(turno.data_inicio, periodo)
    raise ValueError(f"Recorrencia desconhecida: {turno.recorrencia}")


def periodo_da_data(turno, data):
    """Em qual periodo (indice N) essa data cai, dada a recorrencia do turno."""
    if turno.recorrencia == "diaria":
        return (data - turno.data_inicio).days
    if turno.recorrencia == "semanal":
        return (data - turno.data_inicio).days // 7
    if turno.recorrencia == "mensal":
        return _diferenca_em_meses(turno.data_inicio, data)
    raise ValueError(f"Recorrencia desconhecida: {turno.recorrencia}")


class TurnoPlantao(db.Model):
    """Um turno de plantao (ex: "Plantao Manha"): pertence a um Ministerio e
    tem uma fila ordenada de membros que se revezam por rodizio.

    E a REGRA do rodizio (fila, offset, recorrencia, departamento) -- nunca
    guarda quem esta escalado em cada data, isso mora nas Escala geradas por
    app/plantao/sincronizacao.py::sincronizar_turno.
    """

    __tablename__ = "turnos_plantao"

    id = db.Column(db.Integer, primary_key=True)
    ministerio_id = db.Column(db.Integer, db.ForeignKey("ministerios.id"), nullable=False)
    nome = db.Column(db.String(80), nullable=False)
    # Departamento (mesmas chaves de app.escala.models.DEPARTAMENTOS) -- usado
    # so pra herdar a cor no calendario do Ministerio, mesmo esquema da Escala
    # Rapida (ver Escala.cor). Nao seleciona funcoes padrao, diferente da
    # Escala Rapida: cada periodo gerado tem sempre 1 unica funcao (nome_funcao).
    departamento = db.Column(db.String(40), nullable=False)
    nome_funcao = db.Column(db.String(80), nullable=False, default="Responsavel", server_default="Responsavel")
    data_inicio = db.Column(db.Date, nullable=False)
    horario = db.Column(db.Time, nullable=True)
    recorrencia = db.Column(db.String(10), nullable=False)
    offset = db.Column(db.Integer, nullable=False, default=0)
    criado_em = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    ministerio = db.relationship(
        "Ministerio", backref=db.backref("turnos_plantao", cascade="all, delete-orphan")
    )

    @property
    def fila_ordenada(self):
        return [item.membro for item in self.fila]

    @property
    def cor(self):
        from app.escala.models import DEPARTAMENTO_CORES
        return DEPARTAMENTO_CORES.get(self.departamento, "bg-gray-500")

    def __repr__(self):
        return f"<TurnoPlantao {self.nome} do ministerio {self.ministerio_id}>"


class MembroTurno(db.Model):
    """Uma posicao na fila de rodizio de um turno -- referencia o MESMO Membro
    do diretorio da comunidade (ver app/escala/models.py::Membro), nao um
    cadastro separado."""

    __tablename__ = "turno_plantao_membros"

    id = db.Column(db.Integer, primary_key=True)
    turno_id = db.Column(db.Integer, db.ForeignKey("turnos_plantao.id"), nullable=False)
    membro_id = db.Column(db.Integer, db.ForeignKey("escala_membros.id"), nullable=False)
    posicao = db.Column(db.Integer, nullable=False)

    turno = db.relationship(
        "TurnoPlantao",
        backref=db.backref("fila", cascade="all, delete-orphan", order_by="MembroTurno.posicao"),
    )
    membro = db.relationship("Membro")

    def __repr__(self):
        return f"<MembroTurno {self.membro_id} pos={self.posicao} do turno {self.turno_id}>"


def membro_do_periodo(turno, periodo):
    """A formula PURA do rodizio: membros[(offset + periodo) % tamanho].

    Uso exclusivo de app/plantao/sincronizacao.py pra decidir o valor de um
    periodo ainda NAO fixado. NAO representa "quem esta escalado agora" --
    isso e sempre lido de Escala/Funcao materializadas (que podem ter
    divergido da formula por causa de plantao_fixado). Nao chame esta funcao
    pra descobrir a atribuicao atual de um periodo especifico.
    """
    fila = turno.fila_ordenada
    if not fila:
        return None
    return fila[(turno.offset + periodo) % len(fila)]
