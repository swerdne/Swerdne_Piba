"""Model (M do MVC): Comunidade (MongoDB, ver app/db_utils.py).

Camada organizacional anterior a Escala Rapida: toda escala e todo membro do
diretorio pertencem a uma comunidade especifica (ex: uma igreja/ministerio).
Comunidades sao independentes entre si.
"""
import secrets
from datetime import datetime, timezone

import mongoengine
from app.db_utils import PureDateField, PureTimeField, SequentialIdDocument, delete_cascade, relacao_em_cache

PAPEIS_COMUNIDADE = ("admin", "membro")


class Comunidade(SequentialIdDocument):
    meta = {"collection": "comunidades"}
    _nome_sequencia = "comunidades"

    nome = mongoengine.StringField(required=True, max_length=120)
    descricao = mongoengine.StringField()
    imagem = mongoengine.StringField(max_length=500)
    # Criador original -- mantido como metadado historico. Nao e mais a UNICA
    # fonte de autorizacao (ver UsuarioComunidade/comunidade.routes._eh_admin_da_comunidade):
    # o criador ganha automaticamente uma linha papel=admin em UsuarioComunidade
    # ao criar a comunidade (criar_comunidade abaixo), entao toda checagem
    # passa a consultar essa tabela, nao mais usuario_id direto.
    usuario_id = mongoengine.IntField(required=True)
    criada_em = mongoengine.DateTimeField(default=lambda: datetime.now(timezone.utc))

    # Link generico de entrada (ver comunidade.routes.entrar_via_link) --
    # alternativa ao convite por e-mail individual (app/convites): qualquer
    # pessoa com o link vira "membro" desta Comunidade direto, sem precisar
    # que o admin saiba o e-mail de antemao. Nulo ate o admin gerar o
    # primeiro link (tela "Papeis e convites"). Regeneravel a qualquer
    # momento -- gerar um novo invalida o anterior (mesma coluna, valor
    # sobrescrito), protege contra o link vazado continuar funcionando.
    token_convite_publico = mongoengine.StringField(unique=True, sparse=True, max_length=64)

    # Local do check-in por localizacao (ver app/escala/checkin.py): endereco
    # so pra exibir; o que vale e latitude/longitude + o raio aceito.
    endereco = mongoengine.StringField(max_length=300)
    latitude = mongoengine.FloatField()
    longitude = mongoengine.FloatField()
    raio_checkin_m = mongoengine.IntField()

    def gerar_novo_link_convite(self):
        # 8 bytes (64 bits): ainda inviavel de adivinhar por forca bruta
        # (rota tambem tem rate limit, ver entrar_via_link), mas curto o
        # suficiente (~11 caracteres) pra ficar apresentavel ao compartilhar.
        self.token_convite_publico = secrets.token_urlsafe(8)
        return self.token_convite_publico

    @property
    def ministerios(self):
        """Substitui o antigo backref `Comunidade.ministerios` do
        SQLAlchemy, usado em varias telas (calendario, lideres)."""
        from app.ministerio.models import Ministerio
        return list(Ministerio.objects(comunidade_id=self.id))

    def cascade_children(self):
        """Ver app/db_utils.py::delete_cascade. So cobre os filhos que ja
        moraram no Mongo (UsuarioComunidade/Evento) -- Ministerio e Membro
        (ainda em SQLAlchemy nesta fase da migracao) sao apagados a parte,
        explicitamente, em comunidade.routes.excluir_comunidade."""
        from app.escala.models import Musica, PastaMusicas  # banco de musicas e pastas sao da comunidade

        return [
            UsuarioComunidade.objects(comunidade_id=self.id),
            Evento.objects(comunidade_id=self.id),
            Musica.objects(comunidade_id=self.id),
            PastaMusicas.objects(comunidade_id=self.id),
        ]

    def __repr__(self):
        return f"<Comunidade {self.nome} do usuario {self.usuario_id}>"


class UsuarioComunidade(SequentialIdDocument):
    """Papel de um usuario (conta com login) dentro de uma Comunidade --
    'admin' pode gerenciar ministerios/membros/permissoes; 'membro' tem
    visibilidade de leitura (mesmo nivel de hoje via Membro vinculado por
    e-mail, ver comunidade.routes._comunidade_visivel_ou_404).

    Concedido SEMPRE via convite aceito (app/convites), exceto a linha do
    criador original, gerada automaticamente por criar_comunidade. Nao
    confundir com Membro (app/escala/models.py) -- Membro e o diretorio de
    pessoas escalaveis, nao precisa de conta nem de papel; os dois so se
    cruzam por coincidencia de e-mail, quando faz sentido."""

    meta = {
        "collection": "usuario_comunidade",
        "indexes": [{"fields": ["usuario_id", "comunidade_id"], "unique": True}],
    }
    _nome_sequencia = "usuario_comunidade"

    usuario_id = mongoengine.IntField(required=True)
    comunidade_id = mongoengine.IntField(required=True)
    papel = mongoengine.StringField(required=True, max_length=10)
    criado_em = mongoengine.DateTimeField(default=lambda: datetime.now(timezone.utc))
    # O admin recusou colocar essa conta no diretorio de escalacao (Membro)
    # -- sai da lista "Aguardando entrar no diretorio", mas continua com o
    # papel na comunidade; da pra adicionar depois pela lista de contas.
    diretorio_recusado = mongoengine.BooleanField(default=False)

    @property
    def usuario(self):
        from app.auth.models import User
        return relacao_em_cache(self, "usuario", self.usuario_id, lambda: User.objects(id=self.usuario_id).first())

    @property
    def comunidade(self):
        return relacao_em_cache(self, "comunidade", self.comunidade_id, lambda: Comunidade.objects(id=self.comunidade_id).first())

    def __repr__(self):
        return f"<UsuarioComunidade {self.usuario_id} papel={self.papel} da comunidade {self.comunidade_id}>"


class Evento(SequentialIdDocument):
    """Evento pontual da Comunidade (ex: conferencia, congresso, culto
    especial) -- diferente de Escala (app/escala/models.py), que e
    ensaio/culto de rotina de um Ministerio especifico, com equipe escalada.
    Evento e so o registro do acontecimento em si (data, local, descricao),
    sem funcoes/escalacao; comunidade inteira, nao amarrado a 1 ministerio."""

    meta = {"collection": "comunidade_eventos", "ordering": ["data"]}
    _nome_sequencia = "comunidade_eventos"

    comunidade_id = mongoengine.IntField(required=True)
    nome = mongoengine.StringField(required=True, max_length=120)
    descricao = mongoengine.StringField()
    data = PureDateField(required=True)
    data_fim = PureDateField()
    horario = PureTimeField()
    local = mongoengine.StringField(max_length=200)
    criado_em = mongoengine.DateTimeField(default=lambda: datetime.now(timezone.utc))

    @property
    def comunidade(self):
        return relacao_em_cache(self, "comunidade", self.comunidade_id, lambda: Comunidade.objects(id=self.comunidade_id).first())

    def __repr__(self):
        return f"<Evento {self.nome!r} da comunidade {self.comunidade_id}>"


def criar_comunidade(usuario_id, nome, descricao=None, imagem=None):
    comunidade = Comunidade(usuario_id=usuario_id, nome=nome, descricao=descricao, imagem=imagem)
    comunidade.save()

    UsuarioComunidade(usuario_id=usuario_id, comunidade_id=comunidade.id, papel="admin").save()
    return comunidade
