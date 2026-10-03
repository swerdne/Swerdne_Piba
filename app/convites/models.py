"""Model (M do MVC): Convite (MongoDB, ver app/db_utils.py).

Um Convite concede um PAPEL (ver app/comunidade/models.py::PAPEIS_COMUNIDADE,
app/ministerio/models.py::PAPEIS_MINISTERIO) num escopo especifico (uma
Comunidade ou um Ministerio) a um e-mail -- nao exige que a pessoa ja tenha
conta na plataforma (ver ver_convite em routes.py: sem conta, a tela manda
criar uma antes de aceitar). So gera a linha de papel de verdade
(UsuarioComunidade/UsuarioMinisterio) quando ACEITO -- enquanto pendente, a
pessoa nao tem nenhum acesso extra, nao entra no rodizio, nao recebe
notificacao de escala (so o e-mail do proprio convite).

NAO cobre o papel "convidado" (vinculo pontual a 1 Escala/Funcao) -- esse
mecanismo e outro, ja existente e instantaneo (sem convite/aceite), ver
Funcao.eh_convidado em app/escala/models.py e app/escala/CLAUDE.md.
"""
import secrets
from datetime import datetime, timezone

import mongoengine
from app.db_utils import SequentialIdDocument, relacao_em_cache

ESCOPOS = ("comunidade", "ministerio")
STATUS_PENDENTE = "pendente"
STATUS_ACEITO = "aceito"
STATUS_RECUSADO = "recusado"


def _gerar_token():
    return secrets.token_urlsafe(32)


class Convite(SequentialIdDocument):
    meta = {"collection": "convites"}
    _nome_sequencia = "convites"

    # "comunidade" ou "ministerio" -- ver ESCOPOS. escopo_id aponta pra
    # Comunidade.id ou Ministerio.id conforme escopo_tipo (referencia
    # polimorfica -- nao da pra usar um ReferenceField pra 2 collections
    # diferentes; a resolucao e feita em Python via comunidade/ministerio
    # abaixo).
    escopo_tipo = mongoengine.StringField(required=True, max_length=15)
    escopo_id = mongoengine.IntField(required=True)
    papel = mongoengine.StringField(required=True, max_length=10)

    email = mongoengine.StringField(required=True, max_length=120)
    convidado_por_id = mongoengine.IntField(required=True)
    token = mongoengine.StringField(unique=True, required=True, default=_gerar_token, max_length=64)
    status = mongoengine.StringField(default=STATUS_PENDENTE, max_length=10)

    criado_em = mongoengine.DateTimeField(default=lambda: datetime.now(timezone.utc))
    respondido_em = mongoengine.DateTimeField()

    @property
    def convidado_por(self):
        from app.auth.models import User
        return relacao_em_cache(self, "convidado_por", self.convidado_por_id, lambda: User.objects(id=self.convidado_por_id).first())

    @property
    def comunidade(self):
        """So valido quando escopo_tipo == 'comunidade' -- ver escopo_nome/escopo_obj."""
        from app.comunidade.models import Comunidade
        return relacao_em_cache(self, "comunidade", self.escopo_id, lambda: Comunidade.objects(id=self.escopo_id).first())

    @property
    def ministerio(self):
        """So valido quando escopo_tipo == 'ministerio' -- ver escopo_nome/escopo_obj."""
        from app.ministerio.models import Ministerio
        return relacao_em_cache(self, "ministerio", self.escopo_id, lambda: Ministerio.objects(id=self.escopo_id).first())

    @property
    def escopo_obj(self):
        return self.comunidade if self.escopo_tipo == "comunidade" else self.ministerio

    @property
    def escopo_nome(self):
        obj = self.escopo_obj
        return obj.nome if obj else "(removido)"

    @property
    def usuario_ja_cadastrado(self):
        """Se ja existe uma conta (User) com o e-mail do convite -- usado na
        tela de aceite pra decidir se manda logar ou criar conta."""
        from app.auth.models import User
        return User.objects(email__iexact=self.email).first()

    def __repr__(self):
        return f"<Convite {self.email} papel={self.papel} {self.escopo_tipo}={self.escopo_id} status={self.status}>"


def criar_ou_reenviar_convite(escopo_tipo, escopo_id, papel, email, convidado_por_id):
    """Find-or-create: reaproveita um convite PENDENTE ja existente pro mesmo
    escopo+e-mail (atualiza papel/quem convidou/token, pra reenviar em vez de
    acumular convites duplicados) -- so cria um novo se nao houver nenhum
    pendente."""
    email = email.strip().lower()
    convite = Convite.objects(
        escopo_tipo=escopo_tipo, escopo_id=escopo_id, email=email, status=STATUS_PENDENTE
    ).first()

    if convite is None:
        convite = Convite(escopo_tipo=escopo_tipo, escopo_id=escopo_id, email=email)

    convite.papel = papel
    convite.convidado_por_id = convidado_por_id
    convite.token = _gerar_token()
    convite.save()
    return convite
