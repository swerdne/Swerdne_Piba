"""Model (M do MVC): Ministerio (MongoDB, ver app/db_utils.py).

Camada organizacional dentro de uma Comunidade: agrupa escalas relacionadas
(ex: "Ministerio de Louvor", "Equipe de Midia"). Puramente organizacional --
nao tem ligacao obrigatoria com o campo `departamento` de cada Escala.
"""
from datetime import datetime, timezone

import mongoengine
from app.db_utils import PureDateField, SequentialIdDocument

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

    @property
    def comunidade(self):
        from app.comunidade.models import Comunidade
        return Comunidade.objects(id=self.comunidade_id).first()

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
    def papeis_usuarios(self):
        return list(UsuarioMinisterio.objects(ministerio_id=self.id))

    @property
    def escalas(self):
        """Escala ainda em SQLAlchemy nesta fase da migracao (ver plano) --
        substitui o antigo backref `Ministerio.escalas` do SQLAlchemy."""
        from app.escala.models import Escala
        return Escala.query.filter_by(ministerio_id=self.id).all()

    @property
    def turnos_plantao(self):
        """TurnoPlantao ainda em SQLAlchemy nesta fase da migracao -- ver
        `escalas` acima, mesmo motivo."""
        from app.plantao.models import TurnoPlantao
        return TurnoPlantao.query.filter_by(ministerio_id=self.id).all()

    def cascade_children(self):
        """Ver app/db_utils.py::delete_cascade. Escala e TurnoPlantao
        (ainda em SQLAlchemy nesta fase) sao apagados a parte, explicitamente,
        em ministerio.routes.excluir_ministerio."""
        return [
            UsuarioMinisterio.objects(ministerio_id=self.id),
            Crianca.objects(ministerio_id=self.id),
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
        return User.objects(id=self.usuario_id).first()

    @property
    def ministerio(self):
        return Ministerio.objects(id=self.ministerio_id).first()

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
        return Ministerio.objects(id=self.ministerio_id).first()

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
        return Crianca.objects(id=self.crianca_id).first()

    @property
    def registrado_por(self):
        from app.auth.models import User
        return User.objects(id=self.registrado_por_id).first()

    @property
    def retirado_por(self):
        from app.auth.models import User
        return User.objects(id=self.retirado_por_id).first() if self.retirado_por_id else None

    @property
    def esta_presente(self):
        return self.hora_saida is None

    def __repr__(self):
        return f"<CheckInCrianca {self.crianca_id} em {self.data}>"


def criar_ministerio(comunidade_id, nome, descricao=None, imagem=None):
    ministerio = Ministerio(comunidade_id=comunidade_id, nome=nome, descricao=descricao, imagem=imagem)
    ministerio.save()
    return ministerio
