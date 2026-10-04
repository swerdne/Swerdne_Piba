"""Model (M do MVC): Ministerio (MongoDB, ver app/db_utils.py).

Camada organizacional dentro de uma Comunidade: agrupa escalas relacionadas
(ex: "Ministerio de Louvor", "Equipe de Midia"). Puramente organizacional --
nao tem ligacao obrigatoria com o campo `departamento` de cada Escala.
"""
import secrets
from datetime import datetime, timezone

import mongoengine
from app.db_utils import PureDateField, SequentialIdDocument, relacao_em_cache

PAPEIS_MINISTERIO = ("lider", "membro")


class Ministerio(SequentialIdDocument):
    meta = {"collection": "ministerios"}
    _nome_sequencia = "ministerios"

    comunidade_id = mongoengine.IntField(required=True)
    nome = mongoengine.StringField(required=True, max_length=120)
    descricao = mongoengine.StringField()
    imagem = mongoengine.StringField(max_length=500)
    criada_em = mongoengine.DateTimeField(default=lambda: datetime.now(timezone.utc))

    # Dias da semana que esse ministerio costuma ter culto/evento (CSV de
    # inteiros 0=segunda..6=domingo, mesma convencao de
    # app/plantao/models.py::TurnoPlantao.dias_semana). So um lembrete
    # visual pra quem configura a recorrencia de um Rodizio (ver
    # dias_culto_efetivos) -- nunca restringe quais dias podem ser
    # escolhidos la, so destaca os habituais.
    dias_culto = mongoengine.StringField(max_length=20)

    # Link de acesso direto do ministerio (mesma ideia de
    # Comunidade.token_convite_publico, ver app/convites/link_publico.py):
    # quem abre entra como "membro". Regenerar invalida o anterior.
    token_convite_publico = mongoengine.StringField(unique=True, sparse=True, max_length=64)

    # Local proprio do check-in por localizacao (ver app/escala/checkin.py) --
    # vazio = vale o da Comunidade. Endereco so pra exibir; o que conta e
    # latitude/longitude + o raio aceito.
    endereco = mongoengine.StringField(max_length=300)
    latitude = mongoengine.FloatField()
    longitude = mongoengine.FloatField()
    raio_checkin_m = mongoengine.IntField()

    # Estatisticas de comparecimento (ver app/escala/estatisticas.py) --
    # vazio = padrao de la. Tolerancia: minutos de atraso que ainda contam
    # como "no horario". Alerta: faltas seguidas que avisam o lider (0 = nunca).
    tolerancia_atraso_min = mongoengine.IntField()
    alerta_faltas_seguidas = mongoengine.IntField()

    # Check-in por localizacao: padrao do ministerio (cada Escala pode
    # sobrepor, ver Escala.checkin_*_modo e checkin.checkin_ligado).
    # Vazio = padrao: ligado no dia da escala, desligado nos ensaios.
    checkin_escala = mongoengine.BooleanField()
    checkin_ensaio = mongoengine.BooleanField()

    def gerar_novo_link_convite(self):
        self.token_convite_publico = secrets.token_urlsafe(8)
        return self.token_convite_publico

    @property
    def comunidade(self):
        from app.comunidade.models import Comunidade
        return relacao_em_cache(
            self, "comunidade", self.comunidade_id,
            lambda: Comunidade.objects(id=self.comunidade_id).first(),
        )

    @property
    def dias_culto_efetivos(self):
        """Lista de inteiros (0=segunda..6=domingo) -- vazia se nunca
        configurado (diferente de TurnoPlantao.dias_semana_efetivos, aqui
        nao ha uma data-ancora pra cair de volta, entao "nao configurado"
        e so "nenhum destaque", nao um erro)."""
        if not self.dias_culto:
            return []
        return sorted(int(d) for d in self.dias_culto.split(","))

    @property
    def eh_kids(self):
        """O check-in de criancas (ver ministerio.routes.checkin) so faz
        sentido pra um Ministerio voltado a criancas -- sem um campo
        dedicado pra isso, usa o nome como sinal (contem "kids",
        case-insensitive, ex: "Piba Kids")."""
        return "kids" in self.nome.lower()

    @property
    def papeis_usuarios(self):
        return list(UsuarioMinisterio.objects(ministerio_id=self.id))

    @property
    def escalas(self):
        """Substitui o antigo backref `Ministerio.escalas` do SQLAlchemy."""
        from app.escala.models import Escala
        return list(Escala.objects(ministerio_id=self.id))

    @property
    def turnos_plantao(self):
        from app.plantao.models import TurnoPlantao
        return list(TurnoPlantao.objects(ministerio_id=self.id))

    def cascade_children(self):
        """Ver app/db_utils.py::delete_cascade. Escala e TurnoPlantao sao
        apagados a parte, explicitamente, em ministerio.routes.excluir_ministerio.

        Musica: so as do banco LOCAL deste ministerio vao junto. As OFICIAIS
        sao da comunidade e outros ministerios usam (`ministerio_id` nelas e
        so historico) -- antes de apagar, junta o banco da comunidade, pra
        musica antiga deste ministerio virar oficial em vez de sumir."""
        from app.escala.banco_musicas import unificar_banco_da_comunidade
        from app.escala.models import AlertaFaltas, Musica

        unificar_banco_da_comunidade(self.comunidade_id)
        return [
            UsuarioMinisterio.objects(ministerio_id=self.id),
            AlertaFaltas.objects(ministerio_id=self.id),
            Crianca.objects(ministerio_id=self.id),
            Musica.objects(ministerio_id=self.id, oficial=False),
        ]

    def __repr__(self):
        return f"<Ministerio {self.nome} da comunidade {self.comunidade_id}>"


class UsuarioMinisterio(SequentialIdDocument):
    """Papel de um usuario (conta com login) dentro de um Ministerio --
    'lider' gerencia escalas/turnos/membros daquele ministerio; 'membro'
    participa (visualiza as escalas em que esta inserido). Nao existe papel
    'convidado' aqui de proposito -- convidado e sempre escopado a 1 unica
    Escala/Funcao, mecanismo separado e ja existente (Funcao.eh_convidado,
    ver app/escala/CLAUDE.md), nao um papel de ministerio.

    Concedido sempre via convite aceito (app/convites) -- nunca criado
    automaticamente. Quem administra a Comunidade (dono original ou
    UsuarioComunidade papel=admin) tem as mesmas permissoes de um lider em
    QUALQUER ministerio dela, mesmo sem uma linha aqui -- ver
    ministerio.routes._eh_lider_do_ministerio."""

    meta = {
        "collection": "usuario_ministerio",
        "indexes": [{"fields": ["usuario_id", "ministerio_id"], "unique": True}],
    }
    _nome_sequencia = "usuario_ministerio"

    usuario_id = mongoengine.IntField(required=True)
    ministerio_id = mongoengine.IntField(required=True)
    papel = mongoengine.StringField(required=True, max_length=10)
    criado_em = mongoengine.DateTimeField(default=lambda: datetime.now(timezone.utc))

    @property
    def usuario(self):
        from app.auth.models import User
        return relacao_em_cache(self, "usuario", self.usuario_id, lambda: User.objects(id=self.usuario_id).first())

    @property
    def ministerio(self):
        return relacao_em_cache(self, "ministerio", self.ministerio_id, lambda: Ministerio.objects(id=self.ministerio_id).first())

    def __repr__(self):
        return f"<UsuarioMinisterio {self.usuario_id} papel={self.papel} do ministerio {self.ministerio_id}>"


class Crianca(SequentialIdDocument):
    """Uma crianca cadastrada no check-in de um Ministerio (pensado pro
    ministerio Kids, mas nao restrito -- qualquer Ministerio pode ter sua
    propria lista). Cadastrada uma vez pelo lider/voluntario no balcao de
    check-in; reaproveitada em cada culto (ver CheckInCrianca abaixo)."""

    meta = {"collection": "ministerio_criancas"}
    _nome_sequencia = "ministerio_criancas"

    ministerio_id = mongoengine.IntField(required=True)
    nome = mongoengine.StringField(required=True, max_length=120)
    data_nascimento = PureDateField()
    responsavel_nome = mongoengine.StringField(required=True, max_length=120)
    responsavel_telefone = mongoengine.StringField(max_length=30)
    observacoes = mongoengine.StringField()
    criada_em = mongoengine.DateTimeField(default=lambda: datetime.now(timezone.utc))

    @property
    def ministerio(self):
        return relacao_em_cache(self, "ministerio", self.ministerio_id, lambda: Ministerio.objects(id=self.ministerio_id).first())

    @property
    def iniciais(self):
        partes = self.nome.split()
        letras = "".join(p[0] for p in partes[:2])
        return letras.upper() or "?"

    @property
    def checkins(self):
        return CheckInCrianca.objects(crianca_id=self.id).order_by("-hora_entrada")

    def cascade_children(self):
        return [CheckInCrianca.objects(crianca_id=self.id)]

    def __repr__(self):
        return f"<Crianca {self.nome} do ministerio {self.ministerio_id}>"


class CheckInCrianca(SequentialIdDocument):
    """Uma entrada+saida de uma Crianca no balcao de check-in, num dia
    especifico. `codigo_seguranca` e gerado na entrada e entregue ao
    responsavel (escrito/tirado foto) -- na saida, o voluntario confere
    esse mesmo codigo antes de liberar a crianca (ver
    ministerio.routes.fazer_checkout)."""

    meta = {"collection": "ministerio_checkins"}
    _nome_sequencia = "ministerio_checkins"

    crianca_id = mongoengine.IntField(required=True)
    data = PureDateField(required=True)
    hora_entrada = mongoengine.DateTimeField(default=lambda: datetime.now(timezone.utc))
    hora_saida = mongoengine.DateTimeField()
    codigo_seguranca = mongoengine.StringField(required=True, max_length=6)
    registrado_por_id = mongoengine.IntField(required=True)
    retirado_por_id = mongoengine.IntField()

    @property
    def crianca(self):
        return relacao_em_cache(self, "crianca", self.crianca_id, lambda: Crianca.objects(id=self.crianca_id).first())

    @property
    def registrado_por(self):
        from app.auth.models import User
        return relacao_em_cache(self, "registrado_por", self.registrado_por_id, lambda: User.objects(id=self.registrado_por_id).first())

    @property
    def retirado_por(self):
        from app.auth.models import User
        return relacao_em_cache(self, "retirado_por", self.retirado_por_id, lambda: User.objects(id=self.retirado_por_id).first() if self.retirado_por_id else None)

    @property
    def esta_presente(self):
        return self.hora_saida is None

    def __repr__(self):
        return f"<CheckInCrianca {self.crianca_id} em {self.data}>"


def criar_ministerio(comunidade_id, nome, descricao=None, imagem=None):
    ministerio = Ministerio(comunidade_id=comunidade_id, nome=nome, descricao=descricao, imagem=imagem)
    ministerio.save()
    return ministerio
