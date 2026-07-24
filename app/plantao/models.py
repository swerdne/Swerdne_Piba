"""Models (M do MVC): Escala de Plantao.

Rodizio dinamico por deslocamento (round-robin com offset): a fila de membros
de um turno e fixa, mas quem esta escalado num periodo N e sempre CALCULADO
pela formula (nunca decidido "do nada"). A formula em si (membro_do_periodo)
nao persiste nada -- quem persiste e o motor de sincronizacao (ver
app/plantao/sincronizacao.py), que materializa o resultado da formula em
Escala/Funcao reais (as mesmas do modulo app/escala), pra aparecer no
calendario/lista do Ministerio e usar a notificacao 24h/16h ja existente.

A recorrencia (quais datas contam como "periodo N") segue a mesma logica do
Google Agenda: intervalo livre ("a cada N dias/semanas/meses/anos"), dias da
semana especificos quando semanal, 3 modos quando mensal (dia fixo do mes /
ultimo dia-da-semana / enesimo dia-da-semana -- todos derivados de
data_inicio, nunca armazenados separado) e termino por nunca/data/numero de
ocorrencias.
"""
import calendar
from datetime import date, datetime, timedelta, timezone

from app.extensions import db

UNIDADES_RECORRENCIA = ["dia", "semana", "mes", "ano"]
MODOS_MENSAIS = ["dia_fixo", "enesimo_dia_semana", "ultimo_dia_semana"]
TERMINOS = ["nunca", "data", "ocorrencias"]

NOMES_DIA_SEMANA_ABREV = ["seg", "ter", "qua", "qui", "sex", "sab", "dom"]
NOMES_DIA_SEMANA_EXTENSO = [
    "segunda-feira", "terca-feira", "quarta-feira", "quinta-feira",
    "sexta-feira", "sabado", "domingo",
]
ORDINAIS = {1: "1a", 2: "2a", 3: "3a", 4: "4a", 5: "5a"}

JANELAS_NOTIFICACAO = {"24h": 24, "16h": 16}


# --- Matematica pura de calendario (compartilhada pelos modos mensal/anual) ----

def _ano_mes_alvo(data_base, n):
    """Pra qual (ano, mes) vamos se somarmos `n` meses a data_base -- so o
    rollover de ano/mes, sem decidir o dia (usado tanto por _somar_meses
    quanto pelos helpers de enesimo/ultimo dia da semana, pra nao duplicar a
    conta de virada de ano em 3 lugares)."""
    mes_total = data_base.month - 1 + n
    ano = data_base.year + mes_total // 12
    mes = mes_total % 12 + 1
    return ano, mes


def _somar_meses(data_base, n):
    """Soma `n` meses a `data_base`, ajustando o dia se o mes destino for mais curto
    (ex: dia 31 + 1 mes num mes de 30 dias vira dia 30)."""
    ano, mes = _ano_mes_alvo(data_base, n)
    ultimo_dia_do_mes = calendar.monthrange(ano, mes)[1]
    dia = min(data_base.day, ultimo_dia_do_mes)
    return date(ano, mes, dia)


def _diferenca_em_meses(data_base, data):
    """Em quantos meses (contados a partir de data_base) a `data` cai."""
    meses = (data.year - data_base.year) * 12 + (data.month - data_base.month)
    dia_ancora = min(data_base.day, calendar.monthrange(data.year, data.month)[1])
    if data.day < dia_ancora:
        meses -= 1
    return meses


def _ordinal_do_dia_semana_no_mes(data):
    """1-based: essa e a 1a, 2a, 3a... ocorrencia desse dia da semana no mes de `data`?"""
    return (data.day - 1) // 7 + 1


def _nth_dia_semana_do_mes(ano, mes, dia_semana, ordinal):
    """Data do `ordinal`-esimo (1-based) `dia_semana` (0=segunda) do mes/ano
    informado, ou None se esse mes nao tiver essa ocorrencia (ex: nem todo
    mes tem uma 5a terca-feira)."""
    primeiro_dia = date(ano, mes, 1)
    deslocamento = (dia_semana - primeiro_dia.weekday()) % 7
    primeira_ocorrencia = primeiro_dia + timedelta(days=deslocamento)
    candidata = primeira_ocorrencia + timedelta(days=7 * (ordinal - 1))
    return candidata if candidata.month == mes else None


def _ultimo_dia_semana_do_mes(ano, mes, dia_semana):
    """Data da ULTIMA ocorrencia de `dia_semana` (0=segunda) no mes/ano
    informado -- sempre existe, diferente do enesimo."""
    ultimo_dia_do_mes = calendar.monthrange(ano, mes)[1]
    ultimo_dia = date(ano, mes, ultimo_dia_do_mes)
    deslocamento = (ultimo_dia.weekday() - dia_semana) % 7
    return ultimo_dia - timedelta(days=deslocamento)


def opcoes_modo_mensal(data_referencia):
    """Opcoes de modo mensal disponiveis pra uma data de inicio, com rotulo
    ja formatado -- igual ao seletor do Google Agenda: as opcoes sao
    CALCULADAS a partir da data escolhida (o usuario so escolhe ENTRE elas,
    nao escolhe livremente um ordinal/dia da semana desvinculado). Omite
    "enesimo_dia_semana" quando a ocorrencia e a 5a do mes (ordinal raro,
    geraria uma recorrencia que pula quase todo mes -- mesmo comportamento
    do Google Agenda real, que so oferece "dia fixo"/"ultimo" nesse caso)."""
    dia_semana = NOMES_DIA_SEMANA_EXTENSO[data_referencia.weekday()]
    ordinal = _ordinal_do_dia_semana_no_mes(data_referencia)
    opcoes = [("dia_fixo", f"Mensalmente no dia {data_referencia.day}")]
    if ordinal < 5:
        rotulo_ordinal = ORDINAIS.get(ordinal, f"{ordinal}a")
        opcoes.append(("enesimo_dia_semana", f"Mensalmente na {rotulo_ordinal} {dia_semana}"))
    opcoes.append(("ultimo_dia_semana", f"Mensalmente na ultima {dia_semana}"))
    return opcoes


def opcoes_modo_mensal_completas(data_referencia):
    """Igual a opcoes_modo_mensal, mas SEMPRE com as 3 opcoes (nunca omite
    "enesimo_dia_semana") -- usada pra montar as choices do form no servidor,
    pra as 3 opcoes sempre existirem no HTML renderizado. O JS do template
    (ver plantao/nova.html) e quem esconde a opcao "enesimo" ao vivo quando a
    data escolhida pelo usuario cai numa 5a ocorrencia (e troca a selecao pra
    "ultimo_dia_semana" se estiver marcada); sem as 3 sempre no DOM, o JS
    precisaria criar/remover elementos dinamicamente pra cobrir esse caso.
    """
    dia_semana = NOMES_DIA_SEMANA_EXTENSO[data_referencia.weekday()]
    opcoes = dict(opcoes_modo_mensal(data_referencia))
    opcoes.setdefault("enesimo_dia_semana", f"Mensalmente na 5a {dia_semana}")
    return [
        ("dia_fixo", opcoes["dia_fixo"]),
        ("enesimo_dia_semana", opcoes["enesimo_dia_semana"]),
        ("ultimo_dia_semana", opcoes["ultimo_dia_semana"]),
    ]


# --- Motor de recorrencia --------------------------------------------------

def _validar_termino(turno, periodo, data):
    """Levanta ValueError se esse periodo/data ja passou do termino
    configurado da recorrencia (data especifica ou numero de ocorrencias)."""
    if turno.termino_tipo == "data" and data > turno.termino_data:
        raise ValueError(f"A recorrencia deste turno termina antes do periodo {periodo}.")
    if turno.termino_tipo == "ocorrencias" and periodo >= turno.termino_ocorrencias:
        raise ValueError(f"A recorrencia deste turno termina antes do periodo {periodo}.")


def _data_periodo_semanal(turno, periodo):
    """Formula fechada O(1) pra recorrencia semanal com varios dias da
    semana: a 1a "semana ativa" (a semana de data_inicio) so conta os dias
    >= data_inicio (nao gera ocorrencia antes do inicio); toda semana ativa
    seguinte (+intervalo semanas) sempre contribui len(dias) ocorrencias."""
    dias = turno.dias_semana_efetivos
    intervalo = turno.intervalo_recorrencia
    segunda0 = turno.data_inicio - timedelta(days=turno.data_inicio.weekday())
    candidatos_semana0 = [d for d in dias if segunda0 + timedelta(days=d) >= turno.data_inicio]
    c0 = len(candidatos_semana0)

    if periodo < c0:
        return segunda0 + timedelta(days=candidatos_semana0[periodo])

    ciclos, pos = divmod(periodo - c0, len(dias))
    semana_ativa = segunda0 + timedelta(weeks=(ciclos + 1) * intervalo)
    return semana_ativa + timedelta(days=dias[pos])


def _periodo_semanal_aproximado(turno, data):
    """Subestimativa barata (nunca overestima) de em que periodo uma data
    cai -- usada so como ponto de partida pra sincronizar_turno, que tolera
    comecar um pouco antes do real (custa so algumas iteracoes descartadas)."""
    dias = turno.dias_semana_efetivos
    intervalo = turno.intervalo_recorrencia
    segunda0 = turno.data_inicio - timedelta(days=turno.data_inicio.weekday())
    semanas_passadas = max(0, (data - segunda0).days // 7)
    ciclos = semanas_passadas // intervalo
    return max(0, (ciclos - 1) * len(dias))


def _data_periodo_mensal(turno, periodo):
    modo = turno.modo_mensal
    intervalo = turno.intervalo_recorrencia

    if modo == "dia_fixo":
        return _somar_meses(turno.data_inicio, periodo * intervalo)

    dia_semana_base = turno.data_inicio.weekday()

    if modo == "ultimo_dia_semana":
        ano, mes = _ano_mes_alvo(turno.data_inicio, periodo * intervalo)
        return _ultimo_dia_semana_do_mes(ano, mes, dia_semana_base)

    if modo == "enesimo_dia_semana":
        ordinal_base = _ordinal_do_dia_semana_no_mes(turno.data_inicio)
        k = 0
        contagem = 0
        while True:
            ano, mes = _ano_mes_alvo(turno.data_inicio, k * intervalo)
            candidata = _nth_dia_semana_do_mes(ano, mes, dia_semana_base, ordinal_base)
            if candidata is not None:
                if contagem == periodo:
                    return candidata
                contagem += 1
            k += 1

    raise ValueError(f"Modo mensal desconhecido: {modo}")


def data_do_periodo(turno, periodo):
    """Data em que o periodo N desse turno acontece, respeitando
    intervalo/unidade/dias_semana/modo_mensal. Levanta ValueError se esse
    periodo ja passou do termino configurado da recorrencia."""
    unidade = turno.unidade_recorrencia
    intervalo = turno.intervalo_recorrencia

    if unidade == "dia":
        data = turno.data_inicio + timedelta(days=periodo * intervalo)
    elif unidade == "semana":
        data = _data_periodo_semanal(turno, periodo)
    elif unidade == "mes":
        data = _data_periodo_mensal(turno, periodo)
    elif unidade == "ano":
        data = _somar_meses(turno.data_inicio, periodo * intervalo * 12)
    else:
        raise ValueError(f"Unidade de recorrencia desconhecida: {unidade}")

    _validar_termino(turno, periodo, data)
    return data


def periodo_da_data(turno, data):
    """ESTIMATIVA CONSERVADORA (sempre <= o periodo real, nunca overestima)
    de em que periodo uma data cai -- nao e mais um mapeamento exato.

    Usada so como ponto de partida barato por sincronizar_turno, que tolera
    uma subestimativa (custa so algumas iteracoes extras descartadas, nunca
    incorretude). Pra achar o periodo EXATO de uma data digitada pelo
    usuario (ex: registrar ausencia por data), use periodo_exato_da_data.
    """
    unidade = turno.unidade_recorrencia
    intervalo = turno.intervalo_recorrencia

    if unidade == "dia":
        return max(0, (data - turno.data_inicio).days // intervalo)
    if unidade == "semana":
        return _periodo_semanal_aproximado(turno, data)
    # mensal/anual: aproxima por diferenca de meses / passo, sempre <= o real
    meses_passados = _diferenca_em_meses(turno.data_inicio, data)
    passo = intervalo if unidade == "mes" else intervalo * 12
    return max(0, (meses_passados // passo) - 1)


def periodo_exato_da_data(turno, data):
    """Acha o indice do periodo cuja data() bate EXATAMENTE com `data`, ou
    levanta ValueError se essa data nao corresponde a nenhuma ocorrencia
    deste turno. Parte da estimativa conservadora e caminha pra frente --
    caminhada curta (limitada a ~1 ciclo), nao a historia inteira."""
    periodo = periodo_da_data(turno, data)
    while True:
        try:
            data_periodo = data_do_periodo(turno, periodo)
        except ValueError:
            raise ValueError("Essa data nao corresponde a uma ocorrencia deste turno.")
        if data_periodo == data:
            return periodo
        if data_periodo > data:
            raise ValueError("Essa data nao corresponde a uma ocorrencia deste turno.")
        periodo += 1


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

    # Recorrencia estilo Google Agenda -- ver docstring do modulo.
    intervalo_recorrencia = db.Column(db.Integer, nullable=False, default=1, server_default="1")
    unidade_recorrencia = db.Column(db.String(10), nullable=False)  # dia/semana/mes/ano
    dias_semana = db.Column(db.String(20), nullable=True)  # CSV "0,3" -- so unidade=semana
    modo_mensal = db.Column(db.String(20), nullable=True)  # dia_fixo/enesimo_dia_semana/ultimo_dia_semana -- so unidade=mes
    termino_tipo = db.Column(db.String(15), nullable=False, default="nunca", server_default="nunca")
    termino_data = db.Column(db.Date, nullable=True)
    termino_ocorrencias = db.Column(db.Integer, nullable=True)

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

    @property
    def dias_semana_efetivos(self):
        """Lista ordenada de inteiros (0=segunda..6=domingo). Cai no weekday
        de data_inicio se a coluna estiver vazia -- SEMPRE usar esta property
        no motor de geracao, nunca a coluna crua (evita ZeroDivisionError se
        vier vazia/None em runtime)."""
        if not self.dias_semana:
            return [self.data_inicio.weekday()]
        return sorted(int(d) for d in self.dias_semana.split(","))

    @property
    def descricao_recorrencia(self):
        """Texto humano da regra, ex: "A cada 2 semanas (seg, qui)",
        "Mensalmente na ultima quinta-feira, ate 31/12/2026"."""
        unidade_label = {"dia": "dia", "semana": "semana", "mes": "mes", "ano": "ano"}[self.unidade_recorrencia]
        if self.intervalo_recorrencia == 1:
            base = f"Toda(o) {unidade_label}"
        else:
            base = f"A cada {self.intervalo_recorrencia} {unidade_label}s"

        if self.unidade_recorrencia == "semana":
            dias_txt = ", ".join(NOMES_DIA_SEMANA_ABREV[d] for d in self.dias_semana_efetivos)
            base += f" ({dias_txt})"
        elif self.unidade_recorrencia == "mes":
            if self.modo_mensal == "dia_fixo":
                base += f", no dia {self.data_inicio.day}"
            elif self.modo_mensal == "ultimo_dia_semana":
                base += f", na ultima {NOMES_DIA_SEMANA_EXTENSO[self.data_inicio.weekday()]}"
            elif self.modo_mensal == "enesimo_dia_semana":
                ordinal = _ordinal_do_dia_semana_no_mes(self.data_inicio)
                base += f", na {ORDINAIS.get(ordinal, str(ordinal) + 'a')} {NOMES_DIA_SEMANA_EXTENSO[self.data_inicio.weekday()]}"

        if self.termino_tipo == "data" and self.termino_data:
            base += f", ate {self.termino_data.strftime('%d/%m/%Y')}"
        elif self.termino_tipo == "ocorrencias" and self.termino_ocorrencias:
            base += f", por {self.termino_ocorrencias} vezes"

        return base

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
