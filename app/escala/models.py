"""Models (M do MVC): Escala Rapida.

Cada Escala e um EVENTO especifico (nome, departamento, data e horario),
pertencente a um usuario. Departamentos sao independentes entre si (uma
escala de Louvor nao tem nenhuma ligacao com uma de Midia ou Kids).
"""
from datetime import datetime, timezone

from app.extensions import db

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


class Membro(db.Model):
    """Pessoa do diretorio de uma comunidade, reaproveitavel entre escalas/funcoes.

    Cadastrada uma vez em "Gerenciar membros" da comunidade; escalar uma funcao
    significa escolher uma pessoa ja existente neste diretorio (nao criar uma
    nova a cada escalacao).
    """

    __tablename__ = "escala_membros"

    id = db.Column(db.Integer, primary_key=True)
    comunidade_id = db.Column(db.Integer, db.ForeignKey("comunidades.id"), nullable=False)
    nome = db.Column(db.String(120), nullable=False)
    telefone = db.Column(db.String(30), nullable=True)
    email = db.Column(db.String(120), nullable=True)

    comunidade = db.relationship(
        "Comunidade", backref=db.backref("membros", cascade="all, delete-orphan")
    )

    @property
    def iniciais(self):
        partes = self.nome.split()
        letras = "".join(p[0] for p in partes[:2])
        return letras.upper() or "?"

    def __repr__(self):
        return f"<Membro {self.nome}>"


class Escala(db.Model):
    """Um evento de escala (ensaio/culto): nome, departamento, data e horario."""

    __tablename__ = "escalas"

    id = db.Column(db.Integer, primary_key=True)
    ministerio_id = db.Column(db.Integer, db.ForeignKey("ministerios.id"), nullable=False)
    nome = db.Column(db.String(80), nullable=False)
    departamento = db.Column(db.String(40), nullable=False)
    data = db.Column(db.Date, nullable=True)
    horario = db.Column(db.Time, nullable=True)
    criada_em = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    notificado_24h_em = db.Column(db.DateTime, nullable=True)
    notificado_16h_em = db.Column(db.DateTime, nullable=True)

    # Preenchidos quando esta Escala foi gerada automaticamente por um Turno de
    # Rodizio (ver app/plantao/sincronizacao.py) -- None para escalas manuais.
    # plantao_fixado trava essa ocorrencia especifica pra nao ser sobrescrita
    # pelo sync (ausencia remanejada ou reatribuicao manual). plantao_periodo
    # vira NULL quando o turno muda data_inicio/recorrencia (a numeracao dos
    # periodos deixa de valer pra essa linha, mas ela continua existindo como
    # historico) -- ver app/plantao/CLAUDE.md.
    plantao_turno_id = db.Column(db.Integer, db.ForeignKey("turnos_plantao.id"), nullable=True)
    plantao_periodo = db.Column(db.Integer, nullable=True)
    plantao_fixado = db.Column(db.Boolean, nullable=False, default=False, server_default="0")

    # Preenchido quando esta Escala foi a ORIGEM usada para "Criar turno de
    # rodizio com esta equipe" (ver plantao.routes.nova) -- direcao OPOSTA de
    # plantao_turno_id (que marca "esta Escala FOI GERADA por aquele turno").
    # Uma Escala manual pode ser origem de no maximo 1 TurnoPlantao (por isso
    # uselist=False no backref). So existe pra turnos criados a partir de uma
    # escala existente -- turnos criados sem escala_id (caminho nao alcancavel
    # por nenhum link da UI, ver app/plantao/CLAUDE.md) nunca preenchem isso.
    turno_plantao_origem_id = db.Column(db.Integer, db.ForeignKey("turnos_plantao.id"), nullable=True)

    # Cor escolhida manualmente pra esta Escala (chave de CORES_DISPONIVEIS,
    # abaixo) -- sobrepoe a cor padrao do departamento (DEPARTAMENTO_CORES)
    # tanto na lista de Escalas quanto no calendario do Ministerio. None =
    # usa a cor do departamento (comportamento de sempre).
    cor_selecionada = db.Column(db.String(20), nullable=True)

    funcoes = db.relationship(
        "Funcao", backref="escala", order_by="Funcao.ordem", cascade="all, delete-orphan"
    )
    ministerio = db.relationship(
        "Ministerio", backref=db.backref("escalas", cascade="all, delete-orphan")
    )
    # Sem cascade aqui de proposito: excluir o TurnoPlantao nao pode apagar
    # escalas ja ocorridas/fixadas (historico) -- ver plantao.routes.excluir_turno.
    plantao_turno = db.relationship(
        "TurnoPlantao", foreign_keys=[plantao_turno_id], backref=db.backref("escalas_geradas")
    )
    turno_plantao_origem = db.relationship(
        "TurnoPlantao", foreign_keys=[turno_plantao_origem_id],
        backref=db.backref("escala_origem", uselist=False),
    )

    __table_args__ = (
        db.UniqueConstraint("plantao_turno_id", "plantao_periodo", name="uq_escala_plantao_turno_periodo"),
    )

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


class Funcao(db.Model):
    """Uma linha da grade de uma escala.

    Normalmente um instrumento/funcao com no maximo 1 membro (tipo=funcao),
    mas tambem pode ser um subcabecalho (tipo=subcabecalho): uma linha
    somente com um rotulo, usada para agrupar visualmente as funcoes
    seguintes (ex: separar "Orquestra" de "Louvor" dentro do mesmo evento).
    A ordem das linhas (funcao ou subcabecalho) e definida por `ordem`.
    """

    __tablename__ = "escala_funcoes"

    id = db.Column(db.Integer, primary_key=True)
    escala_id = db.Column(db.Integer, db.ForeignKey("escalas.id"), nullable=False)
    nome = db.Column(db.String(80), nullable=False)
    ordem = db.Column(db.Integer, nullable=False, default=0)
    tipo = db.Column(db.String(20), nullable=False, default=TIPO_FUNCAO, server_default=TIPO_FUNCAO)

    membro_id = db.Column(db.Integer, db.ForeignKey("escala_membros.id"), nullable=True)
    status = db.Column(db.String(20), nullable=True)
    notificado_em = db.Column(db.DateTime, nullable=True)

    # Marca uma atribuicao pontual: o Membro por tras dela foi encontrado/criado
    # a partir de uma conta (User) ja existente na plataforma, buscada na hora
    # (ver escala.routes.adicionar_convidado), em vez de escolhido do diretorio
    # fixo da comunidade. Nao afeta notificacao/rodizio (ambos operam em cima
    # de Membro normalmente) -- so controla o selo visual "Convidado" e concede
    # ao dono dessa conta visibilidade de LEITURA desta Escala especifica (ver
    # escala.routes._escala_visivel_ou_404).
    eh_convidado = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())

    membro = db.relationship("Membro")

    @property
    def eh_subcabecalho(self):
        return self.tipo == TIPO_SUBCABECALHO

    def __repr__(self):
        return f"<Funcao {self.nome} da escala {self.escala_id}>"


def criar_escala_com_funcoes_padrao(ministerio_id, nome, departamento, data=None, horario=None, cor_selecionada=None):
    """Cria uma escala nova ja com as funcoes padrao do departamento escolhido."""
    escala = Escala(
        ministerio_id=ministerio_id, nome=nome, departamento=departamento, data=data, horario=horario,
        cor_selecionada=cor_selecionada,
    )
    db.session.add(escala)
    db.session.flush()  # garante escala.id antes de criar as funcoes

    funcoes_padrao = DEPARTAMENTOS.get(departamento, [])
    for ordem, nome_funcao in enumerate(funcoes_padrao):
        db.session.add(Funcao(escala_id=escala.id, nome=nome_funcao, ordem=ordem))

    db.session.commit()
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
