"""Models (M do MVC): Escala Rapida (MongoDB, ver app/db_utils.py).

Cada Escala e um EVENTO especifico (nome, departamento, data e horario),
pertencente a um usuario. Departamentos sao independentes entre si (uma
escala de Louvor nao tem nenhuma ligacao com uma de Midia ou Kids).
"""
import re
import unicodedata
from datetime import datetime, timezone

import mongoengine
from app.db_utils import PureDateField, PureTimeField, SequentialIdDocument, delete_cascade, relacao_em_cache

STATUS_PADRAO = "nao_notificado"

STATUS_LABELS = {
    "nao_notificado": "Nao notificado",
    "confirmado": "Confirmado",
    "presente": "Presente",
    "troca_solicitada": "Troca solicitada",
}

STATUS_CORES = {
    "nao_notificado": "bg-orange-500",
    "confirmado": "bg-green-500",
    "presente": "bg-blue-500",
    "troca_solicitada": "bg-red-500",
}

# Cor de identificacao de cada departamento (usada em listagens/calendario) --
# cor PADRAO de uma Escala quando ela nao tem cor_selecionada propria.
DEPARTAMENTO_CORES = {
    "Louvor": "bg-orange-500",
    "Midia": "bg-blue-500",
    "Kids": "bg-emerald-500",
    "Coreografia": "bg-pink-500",
}

# Paleta de cores que o usuario pode escolher manualmente pra UMA Escala
# especifica (Escala.cor_selecionada guarda a CHAVE, nunca a classe Tailwind
# direto, pra widget/forms nao precisarem montar string -- ver Escala.cor).
# Classes sempre como string literal completa (nunca concatenada) pro scanner
# estatico do Tailwind conseguir achar.
CORES_DISPONIVEIS = {
    "laranja": "bg-orange-500",
    "azul": "bg-blue-500",
    "verde": "bg-emerald-500",
    "rosa": "bg-pink-500",
    "roxo": "bg-purple-500",
    "amarelo": "bg-yellow-500",
    "vermelho": "bg-red-500",
    "ciano": "bg-cyan-500",
}

# Departamento -> funcoes padrao sugeridas ao criar uma escala nova (template).
# O usuario pode adicionar, renomear ou excluir livremente depois.
DEPARTAMENTOS = {
    "Louvor": [
        "Backing Vocal",
        "Baixo",
        "Bateria",
        "Guitarra",
        "Ministro de Louvor",
        "Teclado",
        "Violao",
    ],
    "Midia": [
        "Fotografia",
        "Transmissao/Live",
        "Som",
        "Projecao de Slides",
    ],
    "Kids": [
        "Sala Bercario",
        "Sala Infantil",
        "Recepcao Kids",
    ],
    "Coreografia": [
        "Coreografo(a)",
        "Dancarino(a) 1",
        "Dancarino(a) 2",
        "Dancarino(a) 3",
        "Dancarino(a) 4",
    ],
}

# Mensagem de notificacao adaptada por departamento. {funcao}/{escala}/{data}
# sao preenchidos na hora do envio. "_padrao" cobre departamentos futuros.
MENSAGENS_POR_DEPARTAMENTO = {
    "Louvor": (
        "Ola {membro}, voce foi escalado(a) para {funcao} em {escala} ({data}). "
        "Prepare-se espiritualmente e confirme sua disponibilidade com a lideranca."
    ),
    "Midia": (
        "Ola {membro}, voce foi escalado(a) para {funcao} em {escala} ({data}). "
        "Chegue com antecedencia para testar os equipamentos e confirme sua disponibilidade."
    ),
    "Kids": (
        "Ola {membro}, voce foi escalado(a) para {funcao} em {escala} ({data}). "
        "Lembre-se de chegar cedo para acolher as criancas e confirme sua disponibilidade."
    ),
    "Coreografia": (
        "Ola {membro}, voce foi escalado(a) para {funcao} em {escala} ({data}). "
        "Chegue com antecedencia para o aquecimento e confirme sua disponibilidade com a lideranca."
    ),
    "_padrao": (
        "Ola {membro}, voce foi escalado(a) para {funcao} em {escala} ({data}). "
        "Confirme sua disponibilidade com a lideranca."
    ),
}


class Membro(SequentialIdDocument):
    """Pessoa do diretorio de uma comunidade, reaproveitavel entre escalas/funcoes.

    Cadastrada uma vez em "Gerenciar membros" da comunidade; escalar uma funcao
    significa escolher uma pessoa ja existente neste diretorio (nao criar uma
    nova a cada escalacao).
    """

    meta = {"collection": "escala_membros", "indexes": ["comunidade_id", "email"]}
    _nome_sequencia = "escala_membros"

    comunidade_id = mongoengine.IntField(required=True)
    nome = mongoengine.StringField(required=True, max_length=120)
    telefone = mongoengine.StringField(max_length=30)
    email = mongoengine.StringField(max_length=120)

    @property
    def comunidade(self):
        from app.comunidade.models import Comunidade
        return Comunidade.objects(id=self.comunidade_id).first()

    @property
    def ciclos_disponibilidade(self):
        return list(CicloDisponibilidade.objects(membro_id=self.id))

    @property
    def iniciais(self):
        partes = self.nome.split()
        letras = "".join(p[0] for p in partes[:2])
        return letras.upper() or "?"

    def cascade_children(self):
        return [CicloDisponibilidade.objects(membro_id=self.id)]

    def __repr__(self):
        return f"<Membro {self.nome}>"


class CicloDisponibilidade(SequentialIdDocument):
    """Ciclo recorrente que descreve quando um Membro costuma estar
    indisponivel pra servir -- pensado pra turno de trabalho externo (fora
    da igreja) que roda em ciclo (ex: 4 dias trabalho / 4 dias folga, ou 4
    turnos de 1 dia cada). So um AVISO na hora de escalar (ver
    avisos_disponibilidade abaixo, usado em escala.routes.detalhe) -- nunca
    bloqueia a escalacao, porque a previsao pode falhar (troca de turno,
    folga combinada com o empregador etc.); quem decide continua sendo
    quem esta montando a escala.

    Generico de proposito (nao amarrado a "4 cores" nem a nenhuma empresa
    especifica): quem cadastra define os SegmentoCiclo (nome livre, duracao
    em dias, se conta como indisponivel) e a partir de que data eles comecam
    a se repetir. Um Membro pode ter mais de 1 ciclo (ex: mais de um
    vinculo) -- todos sao checados, nao ha exclusividade forcada.
    """

    meta = {"collection": "escala_ciclos_disponibilidade", "indexes": ["membro_id"]}
    _nome_sequencia = "escala_ciclos_disponibilidade"

    membro_id = mongoengine.IntField(required=True)
    nome = mongoengine.StringField(required=True, max_length=80)
    data_inicio = PureDateField(required=True)

    @property
    def membro(self):
        return Membro.objects(id=self.membro_id).first()

    @property
    def segmentos(self):
        return list(SegmentoCiclo.objects(ciclo_id=self.id).order_by("ordem"))

    def cascade_children(self):
        return [SegmentoCiclo.objects(ciclo_id=self.id)]

    def segmento_na_data(self, data, segmentos=None):
        """Devolve o SegmentoCiclo (ja cadastrado, ver segmentos abaixo) em
        que `data` cai, ou None se o ciclo ainda nao tem nenhum segmento.
        `segmentos` (ja ordenados) pode vir pre-carregado, ver
        avisos_disponibilidade_em_lote."""
        if segmentos is None:
            segmentos = self.segmentos
        total = sum(s.duracao_dias for s in segmentos)
        if not segmentos or total <= 0:
            return None

        # % em Python sempre devolve um resultado nao-negativo pra divisor
        # positivo -- funciona igual pra datas antes ou depois de
        # data_inicio, sem precisar tratar os dois casos separado.
        posicao = (data - self.data_inicio).days % total

        acumulado = 0
        for segmento in segmentos:
            acumulado += segmento.duracao_dias
            if posicao < acumulado:
                return segmento
        return None  # inalcancavel se total > 0, so por seguranca

    def __repr__(self):
        return f"<CicloDisponibilidade {self.nome!r} do membro {self.membro_id}>"


class SegmentoCiclo(SequentialIdDocument):
    """Um pedaco do ciclo (ex.: 'Trabalho', 4 dias, indisponivel=True --
    ou 'Folga', 4 dias, indisponivel=False). A ordem determina a sequencia
    em que os pedacos se repetem a partir de CicloDisponibilidade.data_inicio."""

    meta = {"collection": "escala_ciclo_segmentos"}
    _nome_sequencia = "escala_ciclo_segmentos"

    ciclo_id = mongoengine.IntField(required=True)
    ordem = mongoengine.IntField(required=True)
    nome = mongoengine.StringField(required=True, max_length=40)
    duracao_dias = mongoengine.IntField(required=True)
    indisponivel = mongoengine.BooleanField(default=True)

    @property
    def ciclo(self):
        return CicloDisponibilidade.objects(id=self.ciclo_id).first()

    def __repr__(self):
        return f"<SegmentoCiclo {self.nome!r} ({self.duracao_dias}d)>"


def avisos_disponibilidade(membro, data):
    """Nomes dos segmentos que marcam `membro` como indisponivel em `data`,
    entre todos os ciclos cadastrados pra ele -- lista vazia se disponivel,
    sem ciclo cadastrado, ou sem data pra checar (Escala sem data definida).
    So informativo, ver CicloDisponibilidade acima."""
    if data is None:
        return []
    avisos = []
    for ciclo in membro.ciclos_disponibilidade:
        segmento = ciclo.segmento_na_data(data)
        if segmento is not None and segmento.indisponivel:
            avisos.append(segmento.nome)
    return avisos


def avisos_disponibilidade_em_lote(membros, data):
    """Mesmo resultado de avisos_disponibilidade, mas pra varios membros de
    uma vez: {membro_id: [avisos]} so com quem tem algum aviso. Duas
    consultas no total (ciclos + segmentos), em vez de 1+ por membro -- com
    o diretorio inteiro de uma comunidade isso era a maior parte das
    consultas da tela da Escala."""
    if data is None or not membros:
        return {}
    ciclos = list(CicloDisponibilidade.objects(membro_id__in=[m.id for m in membros]))
    if not ciclos:
        return {}
    segmentos_por_ciclo = {}
    for segmento in SegmentoCiclo.objects(ciclo_id__in=[c.id for c in ciclos]).order_by("ordem"):
        segmentos_por_ciclo.setdefault(segmento.ciclo_id, []).append(segmento)

    avisos_por_membro = {}
    for ciclo in ciclos:
        segmento = ciclo.segmento_na_data(data, segmentos_por_ciclo.get(ciclo.id, []))
        if segmento is not None and segmento.indisponivel:
            avisos_por_membro.setdefault(ciclo.membro_id, []).append(segmento.nome)
    return avisos_por_membro


class Escala(SequentialIdDocument):
    """Um evento de escala (ensaio/culto): nome, departamento, data e horario."""

    meta = {"collection": "escalas", "indexes": ["ministerio_id", "data"]}
    _nome_sequencia = "escalas"

    ministerio_id = mongoengine.IntField(required=True)
    nome = mongoengine.StringField(required=True, max_length=80)
    departamento = mongoengine.StringField(required=True, max_length=40)
    data = PureDateField()
    horario = PureTimeField()
    # Opcional -- so pra completar o intervalo do evento (usado no calendario
    # e no aviso de conflito de horario, ver escala.routes._avisos_conflito_horario).
    # Sem preencher, o evento e tratado como instantaneo (mesmo horario de
    # inicio e fim) na hora de comparar conflitos.
    horario_fim = PureTimeField()
    criada_em = mongoengine.DateTimeField(default=lambda: datetime.now(timezone.utc))

    notificado_24h_em = mongoengine.DateTimeField()
    notificado_16h_em = mongoengine.DateTimeField()

    # Cancelamento (ver escala.routes::cancelar_escala/reabrir_escala) --
    # diferente de excluir: o evento continua existindo (historico, calendario),
    # so marcado que nao vai acontecer. Quem estava escalado e avisado
    # individualmente (email/SMS/sino), um por um, na hora do cancelamento.
    cancelada = mongoengine.BooleanField(default=False)
    cancelada_em = mongoengine.DateTimeField()

    # Preenchidos quando esta Escala foi gerada automaticamente por um Turno de
    # Rodizio (ver app/plantao/sincronizacao.py) -- None para escalas manuais.
    # plantao_fixado trava essa ocorrencia especifica pra nao ser sobrescrita
    # pelo sync (ausencia remanejada ou reatribuicao manual). plantao_periodo
    # vira NULL quando o turno muda data_inicio/recorrencia (a numeracao dos
    # periodos deixa de valer pra essa linha, mas ela continua existindo como
    # historico) -- ver app/plantao/CLAUDE.md.
    # Sem ForeignKey("turnos_plantao.id") -- TurnoPlantao ainda em SQLAlchemy
    # nesta fase, ver `plantao_turno` abaixo (property).
    plantao_turno_id = mongoengine.IntField()
    plantao_periodo = mongoengine.IntField()
    plantao_fixado = mongoengine.BooleanField(default=False)

    # Preenchido quando esta Escala foi a ORIGEM usada para "Criar turno de
    # rodizio com esta equipe" (ver plantao.routes.nova) -- direcao OPOSTA de
    # plantao_turno_id (que marca "esta Escala FOI GERADA por aquele turno").
    # Uma Escala manual pode ser origem de no maximo 1 TurnoPlantao. So existe
    # pra turnos criados a partir de uma escala existente -- turnos criados
    # sem escala_id (caminho nao alcancavel por nenhum link da UI, ver
    # app/plantao/CLAUDE.md) nunca preenchem isso.
    turno_plantao_origem_id = mongoengine.IntField()

    # Cor escolhida manualmente pra esta Escala (chave de CORES_DISPONIVEIS,
    # acima) -- sobrepoe a cor padrao do departamento (DEPARTAMENTO_CORES)
    # tanto na lista de Escalas quanto no calendario do Ministerio. None =
    # usa a cor do departamento (comportamento de sempre).
    cor_selecionada = mongoengine.StringField(max_length=20)
    # Observacoes gerais do repertorio (saem no fim da folha de projecao e
    # das cifras, ver escala.routes.folha_repertorio).
    observacoes_repertorio = mongoengine.StringField(max_length=2000)

    # uq_escala_plantao_turno_periodo do Postgres (unique(plantao_turno_id,
    # plantao_periodo)) nao foi recriada aqui -- e uma invariante mantida
    # pelo proprio codigo de sincronizacao (app/plantao/sincronizacao.py),
    # nao uma restricao validada contra entrada de usuario, e indice composto
    # unico+esparso no Mongo tem semantica diferente o suficiente do Postgres
    # (multiplos None colidindo) pra nao valer o risco de replicar errado.

    @property
    def ministerio(self):
        from app.ministerio.models import Ministerio
        return relacao_em_cache(
            self, "ministerio", self.ministerio_id,
            lambda: Ministerio.objects(id=self.ministerio_id).first(),
        )

    @property
    def funcoes(self):
        return list(Funcao.objects(escala_id=self.id).order_by("ordem"))

    @property
    def repertorio(self):
        return list(ItemRepertorio.objects(escala_id=self.id).order_by("ordem"))

    @property
    def plantao_turno(self):
        """Sem cascade aqui de proposito (igual antes): excluir o
        TurnoPlantao nao pode apagar escalas ja ocorridas/fixadas (historico)
        -- ver plantao.routes.excluir_turno."""
        if not self.plantao_turno_id:
            return None
        from app.plantao.models import TurnoPlantao
        return TurnoPlantao.objects(id=self.plantao_turno_id).first()

    @property
    def turno_plantao_origem(self):
        if not self.turno_plantao_origem_id:
            return None
        from app.plantao.models import TurnoPlantao
        return TurnoPlantao.objects(id=self.turno_plantao_origem_id).first()

    @property
    def ensaios(self):
        return list(Ensaio.objects(escala_id=self.id).order_by("data", "horario"))

    def cascade_children(self):
        return [
            Funcao.objects(escala_id=self.id),
            ItemRepertorio.objects(escala_id=self.id),
            Ensaio.objects(escala_id=self.id),
            Anexo.objects(escala_id=self.id),
        ]

    @property
    def cor(self):
        if self.cor_selecionada and self.cor_selecionada in CORES_DISPONIVEIS:
            return CORES_DISPONIVEIS[self.cor_selecionada]
        return DEPARTAMENTO_CORES.get(self.departamento, "bg-gray-500")

    @property
    def data_hora(self):
        """Combina data+horario num datetime unico (None se faltar alguma parte)."""
        if not self.data:
            return None
        hora = self.horario or datetime.min.time()
        return datetime.combine(self.data, hora)

    def __repr__(self):
        return f"<Escala {self.nome} ({self.departamento}) do ministerio {self.ministerio_id}>"


TIPO_FUNCAO = "funcao"
TIPO_SUBCABECALHO = "subcabecalho"


class Funcao(SequentialIdDocument):
    """Uma linha da grade de uma escala.

    Normalmente um instrumento/funcao com no maximo 1 membro (tipo=funcao),
    mas tambem pode ser um subcabecalho (tipo=subcabecalho): uma linha
    somente com um rotulo, usada para agrupar visualmente as funcoes
    seguintes (ex: separar "Orquestra" de "Louvor" dentro do mesmo evento).
    A ordem das linhas (funcao ou subcabecalho) e definida por `ordem`.
    """

    meta = {"collection": "escala_funcoes", "indexes": ["escala_id", "membro_id"]}
    _nome_sequencia = "escala_funcoes"

    escala_id = mongoengine.IntField(required=True)
    nome = mongoengine.StringField(required=True, max_length=80)
    ordem = mongoengine.IntField(default=0)
    tipo = mongoengine.StringField(default=TIPO_FUNCAO, max_length=20)

    membro_id = mongoengine.IntField()
    status = mongoengine.StringField(max_length=20)
    notificado_em = mongoengine.DateTimeField()

    # Marca uma atribuicao pontual: o Membro por tras dela foi encontrado/criado
    # a partir de uma conta (User) ja existente na plataforma, buscada na hora
    # (ver escala.routes.adicionar_convidado), em vez de escolhido do diretorio
    # fixo da comunidade. Nao afeta notificacao/rodizio (ambos operam em cima
    # de Membro normalmente) -- so controla o selo visual "Convidado" e concede
    # ao dono dessa conta visibilidade de LEITURA desta Escala especifica (ver
    # escala.routes._escala_visivel_ou_404).
    eh_convidado = mongoengine.BooleanField(default=False)

    # Solicitacao de troca (ver escala.routes::atualizar_status/aprovar_troca/
    # recusar_troca) -- preenchidos quando status vira "troca_solicitada",
    # limpos quando o lider aprova ou recusa. troca_sugestao_membro_id e quem
    # a PROPRIA pessoa escalada sugeriu como substituto (opcional -- se nao
    # sugerir ninguem, o lider escolhe na hora de aprovar); pode ser qualquer
    # Membro do diretorio, nao precisa ja estar escalado nesta escala.
    troca_motivo = mongoengine.StringField()
    troca_sugestao_membro_id = mongoengine.IntField()

    @property
    def escala(self):
        return relacao_em_cache(
            self, "escala", self.escala_id, lambda: Escala.objects(id=self.escala_id).first()
        )

    @property
    def membro(self):
        if not self.membro_id:
            return None
        return relacao_em_cache(
            self, "membro", self.membro_id, lambda: Membro.objects(id=self.membro_id).first()
        )

    @property
    def troca_sugestao_membro(self):
        if not self.troca_sugestao_membro_id:
            return None
        return relacao_em_cache(
            self, "troca_sugestao_membro", self.troca_sugestao_membro_id,
            lambda: Membro.objects(id=self.troca_sugestao_membro_id).first(),
        )

    @property
    def eh_subcabecalho(self):
        return self.tipo == TIPO_SUBCABECALHO

    def __repr__(self):
        return f"<Funcao {self.nome} da escala {self.escala_id}>"


class ItemRepertorio(SequentialIdDocument):
    """Uma musica do repertorio de uma Escala (pensado pro departamento
    Louvor, mas nao restrito -- ver escala/detalhe.html, so exibido quando
    escala.departamento == "Louvor"). `ordem` define a sequencia de
    apresentacao; `link` e opcional (cifra, video de referencia etc.)."""

    meta = {"collection": "escala_repertorio", "indexes": ["escala_id"]}
    _nome_sequencia = "escala_repertorio"

    escala_id = mongoengine.IntField(required=True)
    nome_musica = mongoengine.StringField(required=True, max_length=150)
    tom = mongoengine.StringField(max_length=10)
    link = mongoengine.StringField(max_length=500)
    ordem = mongoengine.IntField(default=0)
    # Musica do banco do ministerio (ver Musica) -- None = musica avulsa,
    # so com nome/tom/link (como era antes do banco existir).
    musica_id = mongoengine.IntField()
    # Momento do culto em que ela entra (ex: "Musica 1", "Ofertorio").
    momento = mongoengine.StringField(max_length=60)

    @property
    def escala(self):
        return Escala.objects(id=self.escala_id).first()

    @property
    def musica(self):
        return Musica.objects(id=self.musica_id).first() if self.musica_id else None

    def __repr__(self):
        return f"<ItemRepertorio {self.nome_musica!r} da escala {self.escala_id}>"



DIAS_SEMANA_CURTOS = ["seg", "ter", "qua", "qui", "sex", "sab", "dom"]


class Ensaio(SequentialIdDocument):
    """Um dia de ensaio de uma Escala (a Escala em si e o evento; os ensaios
    sao os encontros antes dele). Cada ensaio pode ser cancelado sozinho --
    quem esta escalado e avisado (ver escala.routes.cancelar_ensaio) -- sem
    cancelar a escala inteira."""

    meta = {"collection": "escala_ensaios", "indexes": ["escala_id"]}
    _nome_sequencia = "escala_ensaios"

    escala_id = mongoengine.IntField(required=True)
    data = PureDateField(required=True)
    horario = PureTimeField()
    horario_fim = PureTimeField()
    local = mongoengine.StringField(max_length=120)
    cancelado = mongoengine.BooleanField(default=False)
    cancelado_em = mongoengine.DateTimeField()
    criado_em = mongoengine.DateTimeField(default=lambda: datetime.now(timezone.utc))

    @property
    def escala(self):
        return Escala.objects(id=self.escala_id).first()

    @property
    def descricao_data(self):
        """Ex: "sab 03/10 - 18:15 as 20:00"."""
        texto = f"{DIAS_SEMANA_CURTOS[self.data.weekday()]} {self.data.strftime('%d/%m')}"
        if self.horario:
            texto += f" - {self.horario.strftime('%H:%M')}"
            if self.horario_fim:
                texto += f" as {self.horario_fim.strftime('%H:%M')}"
        return texto

    def __repr__(self):
        return f"<Ensaio {self.data} da escala {self.escala_id}>"

def criar_escala_com_funcoes_padrao(
    ministerio_id, nome, departamento, data=None, horario=None, horario_fim=None, cor_selecionada=None
):
    """Cria uma escala nova ja com as funcoes padrao do departamento escolhido."""
    escala = Escala(
        ministerio_id=ministerio_id, nome=nome, departamento=departamento, data=data, horario=horario,
        horario_fim=horario_fim, cor_selecionada=cor_selecionada,
    )
    escala.save()

    funcoes_padrao = DEPARTAMENTOS.get(departamento, [])
    for ordem, nome_funcao in enumerate(funcoes_padrao):
        Funcao(escala_id=escala.id, nome=nome_funcao, ordem=ordem).save()

    return escala


def marcar_notificado(funcao):
    funcao.notificado_em = datetime.now(timezone.utc)


def trocar_atribuicao(funcao_a, funcao_b):
    """Troca (swap) membro/status/notificado_em entre duas Funcao.

    Usado tanto por escala.routes.mover_membro (troca manual dentro da mesma
    escala) quanto por plantao.sincronizacao.marcar_ausencia (troca entre a
    Funcao do periodo N e a do periodo N+1, em duas Escalas diferentes).
    """
    funcao_a.membro_id, funcao_b.membro_id = funcao_b.membro_id, funcao_a.membro_id
    funcao_a.status, funcao_b.status = funcao_b.status, funcao_a.status
    funcao_a.notificado_em, funcao_b.notificado_em = funcao_b.notificado_em, funcao_a.notificado_em
    funcao_a.eh_convidado, funcao_b.eh_convidado = funcao_b.eh_convidado, funcao_a.eh_convidado


def mensagem_para(escala, funcao, membro):
    modelo = MENSAGENS_POR_DEPARTAMENTO.get(escala.departamento, MENSAGENS_POR_DEPARTAMENTO["_padrao"])
    data_texto = escala.data.strftime("%d/%m/%Y") if escala.data else "data a definir"
    return modelo.format(membro=membro.nome, funcao=funcao.nome, escala=escala.nome, data=data_texto)


def resumos_para_calendario_em_lote(escalas):
    """Versao em lote de resumo_para_calendario -- monta o resumo de VARIAS
    Escala de uma vez (2 consultas no total: Funcao + Membro), em vez de uma
    consulta de Funcao por Escala e uma de Membro por Funcao escalada. Usada
    pelas telas de calendario (ministerio/comunidade), que precisam do
    resumo de todas as escalas do mes ao mesmo tempo -- sem isso, um mes com
    N escalas custava N+M consultas (M = total de pessoas escaladas no mes).
    Devolve um dict {escala.id: resumo}."""
    escalas = list(escalas)
    if not escalas:
        return {}

    funcoes_por_escala = {}
    for f in Funcao.objects(escala_id__in=[e.id for e in escalas]).order_by("ordem"):
        funcoes_por_escala.setdefault(f.escala_id, []).append(f)

    ids_membro = {
        f.membro_id for fs in funcoes_por_escala.values() for f in fs
        if f.membro_id and not f.eh_subcabecalho
    }
    membros_por_id = {m.id: m for m in Membro.objects(id__in=ids_membro)} if ids_membro else {}

    resumos = {}
    for escala in escalas:
        escalados = [
            {
                "funcao": f.nome,
                "membro": membros_por_id[f.membro_id].nome,
                "status": STATUS_LABELS.get(f.status, f.status or ""),
            }
            for f in funcoes_por_escala.get(escala.id, [])
            if not f.eh_subcabecalho and f.membro_id and f.membro_id in membros_por_id
        ]
        resumos[escala.id] = {
            "nome": escala.nome,
            "departamento": escala.departamento,
            "data": escala.data.strftime("%d/%m/%Y") if escala.data else None,
            "horario": escala.horario.strftime("%H:%M") if escala.horario else None,
            "horario_fim": escala.horario_fim.strftime("%H:%M") if escala.horario_fim else None,
            "cancelada": escala.cancelada,
            "cor": escala.cor,
            "escalados": escalados,
        }
    return resumos


def resumo_para_calendario(escala):
    """Resumo enxuto de UMA Escala -- ver resumos_para_calendario_em_lote
    (usada pelas telas de calendario de verdade, que precisam de varias de
    uma vez). Mantida pra quem precisar do resumo de uma unica escala."""
    return resumos_para_calendario_em_lote([escala])[escala.id]


def ensaios_do_mes_por_dia(inicio, fim, ministerio_ids):
    """Ensaios nao cancelados entre inicio e fim das escalas desses
    ministerios, agrupados por dia: ({data: [(ensaio, escala, cor)]},
    [escalas envolvidas]). Busca os ensaios do periodo primeiro (poucos) e so
    depois as escalas deles -- nao varre todas as escalas do ministerio."""
    ensaios = list(Ensaio.objects(data__gte=inicio, data__lte=fim, cancelado__ne=True).order_by("data", "horario"))
    if not ensaios:
        return {}, []
    escalas = {
        e.id: e for e in Escala.objects(
            id__in=list({x.escala_id for x in ensaios}), ministerio_id__in=list(ministerio_ids)
        )
    }
    por_dia = {}
    for ensaio in ensaios:
        escala = escalas.get(ensaio.escala_id)
        if escala is not None:
            por_dia.setdefault(ensaio.data, []).append((ensaio, escala, escala.cor))
    return por_dia, list(escalas.values())


# Extensoes aceitas como material de uma escala (cifra, partitura, letra,
# roteiro...) e o tipo servido no download.
TIPOS_ANEXO = {
    "pdf": "application/pdf",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "txt": "text/plain; charset=utf-8",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
TAMANHO_MAXIMO_ANEXO = 10 * 1024 * 1024


class Anexo(SequentialIdDocument):
    """Material de uma Escala (cifra, partitura, roteiro...). funcao_id
    preenchido = so pra quem esta naquela funcao (ex: cifra de baixo pro
    Baixo); None = pra toda a equipe. O arquivo fica no proprio documento
    (Mongo, sobrevive a deploy) -- listagens usam .exclude("conteudo")."""

    meta = {"collection": "escala_anexos"}
    _nome_sequencia = "escala_anexos"

    escala_id = mongoengine.IntField(required=True)
    funcao_id = mongoengine.IntField()
    nome_arquivo = mongoengine.StringField(required=True, max_length=200)
    tipo = mongoengine.StringField(required=True, max_length=120)
    tamanho = mongoengine.IntField(default=0)
    conteudo = mongoengine.BinaryField(required=True)
    enviado_por_id = mongoengine.IntField()
    criado_em = mongoengine.DateTimeField(default=lambda: datetime.now(timezone.utc))

    @property
    def funcao(self):
        return Funcao.objects(id=self.funcao_id).first() if self.funcao_id else None

    @property
    def extensao(self):
        return self.nome_arquivo.rsplit(".", 1)[-1].lower() if "." in self.nome_arquivo else ""

    @property
    def icone(self):
        return {
            "pdf": "fa-file-pdf", "png": "fa-file-image", "jpg": "fa-file-image", "jpeg": "fa-file-image",
            "txt": "fa-file-lines", "doc": "fa-file-word", "docx": "fa-file-word",
        }.get(self.extensao, "fa-file")

    @property
    def tamanho_legivel(self):
        if self.tamanho >= 1024 * 1024:
            return f"{self.tamanho / (1024 * 1024):.1f} MB".replace(".", ",")
        return f"{max(1, round(self.tamanho / 1024))} KB"

    @property
    def abre_no_navegador(self):
        return self.extensao in ("pdf", "png", "jpg", "jpeg", "txt")

    def __repr__(self):
        return f"<Anexo {self.nome_arquivo!r} da escala {self.escala_id}>"


class VersaoCifra(mongoengine.EmbeddedDocument):
    """Cifra da musica guardada em outro tom (alem da original). Cada versao
    e independente: editar a original nao mexe nas versoes, e vice-versa."""

    tom = mongoengine.StringField(required=True, max_length=10)
    cifra = mongoengine.StringField()
    atualizada_em = mongoengine.DateTimeField(default=lambda: datetime.now(timezone.utc))


class Musica(SequentialIdDocument):
    """Musica de um banco de musicas -- ver escala/banco_musicas.py. Dois
    niveis: o banco OFICIAL da comunidade (oficial=True; so admin altera, usado
    por todos os ministerios) e o banco LOCAL de cada ministerio (oficial=False,
    ministerio_id = dono; o lider adiciona a vontade e o admin pode aprovar
    pra virar oficial). Uma unica musica com
    duas versoes editadas separadamente: letra_projecao (pro telao: blocos
    sem cifra, rotulos tipo [VERSO 1]/[REFRAO]) e cifra_louvor (pra quem toca:
    acordes em cima da letra, alinhamento monoespacado). As escalas apontam
    pra ela via ItemRepertorio.musica_id."""

    meta = {"collection": "musicas", "indexes": ["comunidade_id", "ministerio_id"]}
    _nome_sequencia = "musicas"

    # Comunidade dona (oficial e local). None so em musica antiga, de quando
    # cada ministerio tinha o proprio banco -- banco_musicas.
    # unificar_banco_da_comunidade preenche (e junta repetidas) na 1a vez que o
    # banco da comunidade e usado; essas antigas viram OFICIAIS.
    comunidade_id = mongoengine.IntField()
    # Musica LOCAL: o ministerio dono. Musica oficial: so historico de onde foi
    # cadastrada/aprovada (nao usar pra permissao de oficial).
    ministerio_id = mongoengine.IntField()
    # True (padrao, inclui as antigas sem o campo) = banco oficial da
    # comunidade; False = banco local do ministerio_id.
    oficial = mongoengine.BooleanField(default=True)
    # Admin escondeu esta musica local da lista "Sugestoes dos ministerios"
    # (nao quis aprovar) -- ela continua no banco local normalmente.
    sugestao_dispensada = mongoengine.BooleanField(default=False)
    # As palavras-chave de tema (tags) ja foram preenchidas automaticamente
    # pela letra, ou alguem mexeu nelas a mao -- o preenchimento automatico
    # do banco (banco_musicas.preencher_palavras_chave_da_comunidade) nao
    # volta nesta musica. Salvar cifra/letra numa musica SEM tags ainda
    # preenche (ver ministerio.routes._palavras_chave_se_faltar).
    palavras_chave_verificadas = mongoengine.BooleanField(default=False)
    nome = mongoengine.StringField(required=True, max_length=150)
    artista = mongoengine.StringField(max_length=120)
    tom = mongoengine.StringField(max_length=10)
    tags = mongoengine.ListField(mongoengine.StringField(max_length=40))
    link = mongoengine.StringField(max_length=500)
    letra_projecao = mongoengine.StringField()
    cifra_louvor = mongoengine.StringField()
    # Cifra salva em outros tons (a original continua em cifra_louvor/tom).
    versoes_cifra = mongoengine.EmbeddedDocumentListField(VersaoCifra)
    criada_em = mongoengine.DateTimeField(default=lambda: datetime.now(timezone.utc))
    atualizada_em = mongoengine.DateTimeField(default=lambda: datetime.now(timezone.utc))

    @property
    def ministerio(self):
        from app.ministerio.models import Ministerio
        return Ministerio.objects(id=self.ministerio_id).first()

    def eh_tom_original(self, tom):
        """Sem tom informado, ou mesmo tom (mesma nota e modo) do cadastro."""
        return not (tom or "").strip() or not self.tom or mesmo_tom(tom, self.tom)

    def versao_no_tom(self, tom):
        for versao in self.versoes_cifra or []:
            if mesmo_tom(versao.tom, tom):
                return versao
        return None

    def cifra_no_tom(self, tom):
        """Cifra salva exatamente nesse tom (original ou versao); None se nao houver."""
        if self.eh_tom_original(tom):
            return self.cifra_louvor
        versao = self.versao_no_tom(tom)
        return versao.cifra if versao else None

    @property
    def tons_salvos(self):
        """[(tom, eh_original)] -- original primeiro, depois as versoes."""
        tons = [(self.tom or "", True)] if self.cifra_louvor else []
        return tons + [(v.tom, False) for v in self.versoes_cifra or []]

    def __repr__(self):
        banco = "oficial" if self.oficial else f"local do ministerio {self.ministerio_id}"
        return f"<Musica {self.nome!r} ({banco}) da comunidade {self.comunidade_id}>"


class ItemPasta(mongoengine.EmbeddedDocument):
    """Uma musica dentro de uma PastaMusicas. `musica_id` None = musica avulsa
    (veio de um repertorio de escala com musica fora do banco)."""

    musica_id = mongoengine.IntField()
    nome = mongoengine.StringField(required=True, max_length=150)
    tom = mongoengine.StringField(max_length=10)
    momento = mongoengine.StringField(max_length=60)

    @property
    def musica(self):
        return Musica.objects(id=self.musica_id).first() if self.musica_id else None


class CompartilhamentoPasta(mongoengine.EmbeddedDocument):
    """Pasta enviada pra uma conta (de qualquer ministerio/comunidade) --
    aparece na tela inicial dela ate abrir (visto_em)."""

    usuario_id = mongoengine.IntField(required=True)
    enviado_por_id = mongoengine.IntField(required=True)
    enviado_em = mongoengine.DateTimeField(default=lambda: datetime.now(timezone.utc))
    visto_em = mongoengine.DateTimeField()


class PastaMusicas(SequentialIdDocument):
    """Um REPERTORIO com nome (ex: "Repertorio da manha", "da noite") de um
    MINISTERIO -- aba "Repertorios" do banco de musicas. (O nome da classe
    ficou do 1o desenho, quando se chamava "pasta"; na tela e sempre
    "repertorio".) Montada a mao a partir do banco ou copiada
    do repertorio de uma escala (com o tom do dia de cada musica). Pode ser
    compartilhada com qualquer conta da plataforma, que ganha acesso de
    LEITURA a ela e as folhas (cifras/projecao) pra baixar -- mesmo sem ser
    da comunidade. Ver ministerio.routes (secao "Pastas")."""

    meta = {"collection": "pastas_musicas", "indexes": ["comunidade_id", "compartilhada_com.usuario_id"]}
    _nome_sequencia = "pastas_musicas"

    comunidade_id = mongoengine.IntField(required=True)
    # Ministerio dono (quem lidera ele cria/edita/envia). None so nos criados
    # antes de existir esse campo -- aparecem como "Sem ministerio".
    ministerio_id = mongoengine.IntField()
    nome = mongoengine.StringField(required=True, max_length=120)
    criada_por_id = mongoengine.IntField(required=True)
    criada_em = mongoengine.DateTimeField(default=lambda: datetime.now(timezone.utc))
    # Escala de onde foi copiada (so informativo -- a pasta e uma copia, nao
    # muda se o repertorio da escala mudar depois).
    escala_id = mongoengine.IntField()
    itens = mongoengine.EmbeddedDocumentListField(ItemPasta)
    compartilhada_com = mongoengine.EmbeddedDocumentListField(CompartilhamentoPasta)
    # Historico legivel dos envios ("Louvor - Teclado: 3 pessoas, 12/10") --
    # ver ministerio/compartilhamento.py.
    envios = mongoengine.ListField(mongoengine.StringField(max_length=200))

    @property
    def comunidade(self):
        from app.comunidade.models import Comunidade
        return Comunidade.objects(id=self.comunidade_id).first()

    @property
    def ministerio(self):
        if not self.ministerio_id:
            return None
        from app.ministerio.models import Ministerio
        return Ministerio.objects(id=self.ministerio_id).first()

    def compartilhamento_de(self, usuario_id):
        return next((c for c in self.compartilhada_com if c.usuario_id == usuario_id), None)

    def __repr__(self):
        return f"<PastaMusicas {self.nome!r} da comunidade {self.comunidade_id}>"


_ROTULO_SECAO = re.compile(r"^\s*\[(.+?)\]\s*$")


def blocos_da_letra(texto):
    """Quebra a letra de projecao em blocos pra exibir/imprimir: cada bloco
    e {"rotulo": "VERSO 1" ou None, "linhas": [...]}. Linha so com [ALGO]
    vira rotulo; linha em branco separa blocos (um "slide")."""
    blocos, atual = [], None
    for linha in (texto or "").replace("\r\n", "\n").split("\n"):
        rotulo = _ROTULO_SECAO.match(linha)
        if rotulo:
            atual = {"rotulo": rotulo.group(1).strip(), "linhas": []}
            blocos.append(atual)
        elif not linha.strip():
            if atual is not None and atual["linhas"]:
                atual = None
        else:
            if atual is None:
                atual = {"rotulo": None, "linhas": []}
                blocos.append(atual)
            atual["linhas"].append(linha.rstrip())
    return blocos


_PALAVRAS_PROJECAO = ("proje", "midia", "datashow", "telao", "slide", "letra", "transmiss")


def eh_funcao_de_projecao(nome_funcao):
    """Funcoes que recebem a versao de projecao (letra) em vez das cifras.
    Pelo nome da funcao, sem acento: Projecao, Midia, Datashow, Telao..."""
    nome = unicodedata.normalize("NFD", nome_funcao or "").encode("ascii", "ignore").decode().lower()
    return any(p in nome for p in _PALAVRAS_PROJECAO)


# --- Transposicao de cifras (mesma logica em static/js/transpor.js) ---------

_NOTAS_SUSTENIDO = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
_NOTAS_BEMOL = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]
_INDICE_NOTA = {**{n: i for i, n in enumerate(_NOTAS_SUSTENIDO)},
                **{n: i for i, n in enumerate(_NOTAS_BEMOL)},
                "Cb": 11, "B#": 0, "E#": 5, "Fb": 4}
# Tons que se escrevem com bemol (maiores: F Bb Eb Ab Db; menores: Dm Gm Cm Fm Bbm Ebm).
_MAIORES_BEMOL = {5, 10, 3, 8, 1}
_MENORES_BEMOL = {2, 7, 0, 5, 10, 3}

# no3/omit (C9(no3)), alt, ø (meio-diminuto), Δ (maior com 7M) e "/" seguido
# de numero (6/9, (b9/#11)) -- o "/" seguido de NOTA continua sendo o baixo.
_SUFIXO = r"(?:maj|min|dim|aug|sus|add|no|omit|alt|m|M|º|°|ø|Δ|\+|-|\d|\(|\)|[#b](?=\d)|/(?=[#b]?\d)|,)*"
_TOKEN_ACORDE = re.compile(r"^(\(?)([A-G][#b]?)(" + _SUFIXO + r")(?:/([A-G][#b]?))?([)\],.]*)$")
_ROTULO_INICIAL = re.compile(r"^\s*(?:\[[^\]]*\]|[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ ]*\d*\s*:)")
# Marcas que podem aparecer numa linha de acordes sem ser acorde: barras e
# repeticao (| || |: :|), N.C. (sem acorde), parenteses soltos, reticencias,
# setas, asterisco, % e "2x"/"(x2)".
_MARCAS_OK = re.compile(
    r"^(?:\|+:?|:\|+|:|-+|/|%|\(|\)|\.{2,}|…|->|→|\*+|N\.?C\.?|\(?\d*x\d*\)?|\(?\d+x?\)?)$", re.I
)
_TOM = re.compile(r"^\s*([A-G][#b]?)(m(?!aj))?")


def _ler_tom(tom):
    m = _TOM.match(tom or "")
    if not m:
        return None
    return _INDICE_NOTA[m.group(1)], bool(m.group(2)), m.group(1)


def prefere_bemol(tom):
    """Se o tom se escreve com bemol (Bb, Eb...) ou sustenido (F#, C#...)."""
    lido = _ler_tom(tom)
    if lido is None:
        return False
    indice, menor, nota = lido
    if len(nota) == 2:
        return nota[1] == "b"
    return indice in (_MENORES_BEMOL if menor else _MAIORES_BEMOL)


def transpor_tom(tom, semitons):
    lido = _ler_tom(tom)
    if lido is None:
        return tom
    indice, menor, _ = lido
    novo = (indice + semitons) % 12
    bemol = novo in (_MENORES_BEMOL if menor else _MAIORES_BEMOL)
    return (_NOTAS_BEMOL if bemol else _NOTAS_SUSTENIDO)[novo] + ("m" if menor else "")


def mesmo_tom(a, b):
    """G == G, Gb == F#, mas G != Gm."""
    x, y = _ler_tom(a), _ler_tom(b)
    if x is None or y is None:
        return (a or "").strip().lower() == (b or "").strip().lower()
    return x[0] == y[0] and x[1] == y[1]


def semitons_entre(de, para):
    """Quantos semitons (0..11) do tom `de` pro tom `para`; None se nao der pra ler."""
    a, b = _ler_tom(de), _ler_tom(para)
    if a is None or b is None:
        return None
    return (b[0] - a[0]) % 12


def _transpor_nota(nota, semitons, bemol):
    return (_NOTAS_BEMOL if bemol else _NOTAS_SUSTENIDO)[(_INDICE_NOTA[nota] + semitons) % 12]


def _transpor_token(token, semitons, bemol):
    m = _TOKEN_ACORDE.match(token)
    if not m:
        return token
    antes, raiz, sufixo, baixo, depois = m.groups()
    novo = antes + _transpor_nota(raiz, semitons, bemol) + sufixo
    if baixo:
        novo += "/" + _transpor_nota(baixo, semitons, bemol)
    return novo + depois


def eh_linha_de_acordes(linha):
    """Linha so de acordes (pode ter rotulo tipo "Intro:"/"[Solo]" na frente e
    marcas como | ou x2) -- as linhas de letra ficam intactas."""
    resto = _ROTULO_INICIAL.sub("", linha, count=1)
    acordes = 0
    for token in resto.split():
        if _TOKEN_ACORDE.match(token):
            acordes += 1
        elif not _MARCAS_OK.match(token):
            return False
    return acordes > 0


def _transpor_linha(linha, semitons, bemol):
    # Mantem cada acorde em cima da mesma silaba: se o acorde novo ficou maior
    # ou menor, compensa nos espacos que vem depois dele.
    saida, sobra = [], 0
    for parte in re.split(r"(\s+)", linha):
        if not parte:
            continue
        if parte.isspace():
            if sobra:
                tamanho = len(parte) - sobra
                sobra = 0
                if tamanho < 1:
                    sobra, tamanho = 1 - tamanho, 1
                parte = " " * tamanho
            saida.append(parte)
            continue
        nova = _transpor_token(parte, semitons, bemol)
        sobra += len(nova) - len(parte)
        saida.append(nova)
    return "".join(saida)


def transpor_cifra(texto, semitons, bemol=False):
    """Sobe/desce todos os acordes da cifra `semitons` semitons."""
    if not texto or not semitons % 12:
        return texto
    return "\n".join(
        _transpor_linha(linha, semitons, bemol) if eh_linha_de_acordes(linha) else linha
        for linha in texto.replace("\r\n", "\n").split("\n")
    )


# --- Rascunho da projecao a partir da cifra ----------------------------------

_LINHA_DE_TABLATURA = re.compile(r"^\s*[eBGDAEbgdae]\s*\|[-\d|hpbr/\\~x ]*$")
_ACORDE_ENTRE_COLCHETES = re.compile(r"\[([^\]\s]+)\]")
_ROTULO_DE_SECAO = re.compile(
    r"^\s*[\[(]?\s*((?:intro|introducao|introdução|verso|estrofe|parte|pre[- ]?refrao|pré[- ]?refrão|"
    r"refrao|refrão|coro|ponte|final|tag|interludio|interlúdio|solo|instrumental|outro|vamp)"
    r"[\w\sÀ-ÿ]*?\d*)\s*[\])]?\s*:?\s*(?:\(?\s*\d*\s*x\s*\d*\s*\)?)?\s*$",
    re.I,
)


def _sem_acorde_inline(linha):
    # "[G]Grande e o [D]Senhor" -> "Grande e o Senhor"
    return _ACORDE_ENTRE_COLCHETES.sub(
        lambda m: "" if _TOKEN_ACORDE.match(m.group(1)) else m.group(0), linha
    )


def projecao_da_cifra(texto, linhas_por_slide=None):
    """Gera o RASCUNHO da letra de projecao a partir de uma cifra: tira as
    linhas de acordes e tablaturas, poe os rotulos no padrao [VERSO 1]/
    [REFRAO], passa a letra pra maiusculas e separa os slides por linha em
    branco. Partes so instrumentais (intro, solo) somem. Quem chama decide
    se usa -- nada aqui grava na musica."""
    blocos, atual = [], None
    for linha in (texto or "").replace("\r\n", "\n").split("\n"):
        if eh_linha_de_acordes(linha) or _LINHA_DE_TABLATURA.match(linha):
            continue
        rotulo = _ROTULO_DE_SECAO.match(linha) or _ROTULO_SECAO.match(linha)
        if rotulo:
            atual = {"rotulo": " ".join(rotulo.group(1).split()).upper(), "linhas": []}
            blocos.append(atual)
            continue
        letra = " ".join(_sem_acorde_inline(linha).split())
        if not letra:
            if atual is not None and atual["linhas"]:
                atual = None
            continue
        if atual is None:
            atual = {"rotulo": None, "linhas": []}
            blocos.append(atual)
        atual["linhas"].append(letra.upper())
    partes = []
    for bloco in blocos:
        if not bloco["linhas"]:
            continue  # rotulo sem letra (intro, solo...)
        # Slide de no maximo LINHAS_POR_SLIDE linhas: cifra digitada sem linha
        # em branco viraria a letra inteira num slide so. O rotulo fica no 1o.
        linhas = bloco["linhas"]
        tamanho = linhas_por_slide or LINHAS_POR_SLIDE
        for inicio in range(0, len(linhas), tamanho):
            cabeca = [f"[{bloco['rotulo']}]"] if bloco["rotulo"] and inicio == 0 else []
            partes.append("\n".join(cabeca + linhas[inicio:inicio + tamanho]))
    return "\n\n".join(partes)


LINHAS_POR_SLIDE = 4


def tem_acordes(texto):
    return any(eh_linha_de_acordes(l) for l in (texto or "").split("\n"))


# --- Deteccao do tom pelos acordes da cifra ----------------------------------
#
# Teoria musical simples, sem servico externo: cada tom tem um campo
# harmonico (os acordes "da casa"). Pontua os 24 tons pelos acordes da cifra
# e fica com o que mais encaixa. Tom relativo (G x Em) usa os mesmos acordes
# -- o desempate e pelo acorde do proprio tom: quantas vezes aparece e,
# principalmente, se a musica comeca/termina nele (quase sempre resolve ali).

# (intervalo a partir do tom, qualidade): "M" maior, "m" menor, "d" diminuto.
_CAMPO_MAIOR = {(0, "M"), (2, "m"), (4, "m"), (5, "M"), (7, "M"), (9, "m"), (11, "d")}
# Menor natural + V maior e vii diminuto do menor harmonico (muito comuns).
_CAMPO_MENOR = {(0, "m"), (2, "d"), (3, "M"), (5, "m"), (7, "m"), (7, "M"), (8, "M"), (10, "M"), (11, "d")}
_ACORDE_INLINE = re.compile(r"\[([A-G][^\]\s]*)\]")


def _qualidade(sufixo):
    s = sufixo or ""
    if s.startswith(("dim", "º", "°", "ø")) or "m7b5" in s or "m7(b5)" in s:
        return "d"
    if s.startswith("m") and not s.startswith("maj"):
        return "m"
    return "M"  # maior, 7, sus, add, aug... contam como maiores pro campo


def acordes_da_cifra(texto):
    """[(indice_da_nota 0..11, qualidade, raiz_como_escrita)] na ordem em que
    aparecem -- das linhas de acordes e de acordes entre colchetes no meio da
    letra ("[G]Tu es..."). Baixo invertido (/F#) e ignorado."""
    acordes = []
    for linha in (texto or "").replace("\r\n", "\n").split("\n"):
        if eh_linha_de_acordes(linha):
            tokens = _ROTULO_INICIAL.sub("", linha, count=1).split()
        else:
            tokens = _ACORDE_INLINE.findall(linha)
        for token in tokens:
            m = _TOKEN_ACORDE.match(token)
            if m:
                raiz = m.group(2)
                acordes.append((_INDICE_NOTA[raiz], _qualidade(m.group(3)), raiz))
    return acordes


def detectar_tom(texto):
    """Tom mais provavel da cifra ("G", "Em", "Bb"...) pelos acordes, ou None
    se houver pouco acorde pra decidir. E uma estimativa -- quem usa deve
    deixar claro que foi identificado automaticamente."""
    acordes = acordes_da_cifra(texto)
    if len(acordes) < 3:
        return None

    primeiro, ultimo = acordes[0], acordes[-1]
    melhor = None
    for tonica in range(12):
        for menor in (False, True):
            campo = _CAMPO_MENOR if menor else _CAMPO_MAIOR
            qualidade_tonica = "m" if menor else "M"
            pontos = 0.0
            for indice, qualidade, _ in acordes:
                intervalo = (indice - tonica) % 12
                if (intervalo, qualidade) in campo:
                    pontos += 1
                    if intervalo == 0 and qualidade == qualidade_tonica:
                        pontos += 0.5
                else:
                    pontos -= 1
            if primeiro[0] == tonica and primeiro[1] == qualidade_tonica:
                pontos += 2
            if ultimo[0] == tonica and ultimo[1] == qualidade_tonica:
                pontos += 3
            if melhor is None or pontos > melhor[0]:
                melhor = (pontos, tonica, menor)

    pontos, tonica, menor = melhor
    # Pouco encaixe (cifra cheia de acordes de fora): melhor nao chutar.
    if pontos < len(acordes) * 0.5:
        return None

    # Grafia: a que a propria cifra usa pra essa nota (Bb x A#); sem ela,
    # a convencao do tom (mesma regra da transposicao).
    escritas = [raiz for indice, _, raiz in acordes if indice == tonica]
    if escritas:
        nota = max(set(escritas), key=escritas.count)
    else:
        bemol = tonica in (_MENORES_BEMOL if menor else _MAIORES_BEMOL)
        nota = (_NOTAS_BEMOL if bemol else _NOTAS_SUSTENIDO)[tonica]
    return nota + ("m" if menor else "")


# --- Lista de tons (dropdown dos formularios, ver escala.forms.TomField) ------

# Na tela aparece so a cifra do tom (G, F#m...), sem o nome em portugues.
_TONS_MAIORES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
_TONS_MENORES = ["Cm", "C#m", "Dm", "Ebm", "Em", "Fm", "F#m", "Gm", "G#m", "Am", "Bbm", "Bm"]
_TOM_COMPLETO = re.compile(r"^[A-G][#b]?m?$")


TONS_MAIORES = [(t, t) for t in _TONS_MAIORES]
TONS_MENORES = [(t, t) for t in _TONS_MENORES]
TONS = [t for t, _ in TONS_MAIORES + TONS_MENORES]


def eh_tom_valido(tom):
    """Tom escrito como cifra (G, F#m, Bb...) -- inclui grafias fora da lista
    (A#, Db...) que musicas antigas ja tenham salvas."""
    return bool(_TOM_COMPLETO.match(tom or ""))


# --- Folha de repertorio (cifras/projecao) -- escala ou pasta ------------------

def itens_para_folha(entradas):
    """Monta os itens da folha de impressao (templates/escala/
    folha_repertorio.html) a partir de [(nome, momento, musica_ou_None, tom)].
    Cifra: 1o a salva nesse tom (original ou versao); senao a original
    transposta na hora pro tom pedido."""
    itens = []
    for nome, momento, musica, tom in entradas:
        tom = tom or (musica.tom if musica else None)
        tom_original = None
        cifra = musica.cifra_no_tom(tom) if musica else None
        if musica and cifra is None and musica.cifra_louvor:
            cifra = musica.cifra_louvor
            semitons = semitons_entre(musica.tom, tom)
            if semitons:
                cifra = transpor_cifra(cifra, semitons, prefere_bemol(tom))
                tom_original = musica.tom
        itens.append({
            "nome": nome,
            "momento": momento,
            "musica": musica,
            "tom": tom,
            "tom_original": tom_original,
            "blocos": blocos_da_letra(musica.letra_projecao) if musica else [],
            "cifra": cifra,
            "cifra_html": cifra_em_html(cifra) if cifra else None,
        })
    return itens


def cifra_em_html(texto):
    """Cifra pronta pra <pre>, com cada acorde das linhas de acordes num
    <span class="acorde"> (cor forte + negrito, ver folha_repertorio.html e
    static/css/input.css). Todo o resto e escapado; espacos e quebras ficam
    iguais, pra nao mexer no alinhamento. Mesma logica de
    static/js/transpor.js (colorirCifra), usada na tela."""
    from markupsafe import Markup, escape

    saida = []
    for linha in (texto or "").replace("\r\n", "\n").split("\n"):
        if not eh_linha_de_acordes(linha):
            saida.append(str(escape(linha)))
            continue
        pedacos = []
        for pedaco in re.split(r"(\s+)", linha):
            if pedaco and not pedaco.isspace() and _TOKEN_ACORDE.match(pedaco):
                pedacos.append(f'<span class="acorde">{escape(pedaco)}</span>')
            else:
                pedacos.append(str(escape(pedaco)))
        saida.append("".join(pedacos))
    return Markup("\n".join(saida))

