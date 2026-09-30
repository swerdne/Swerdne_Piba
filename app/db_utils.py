"""Utilitarios compartilhados da migracao pra MongoDB (MongoEngine).

Repoe, de forma explicita, tres coisas que o SQLAlchemy dava de graca e que
o Mongo nao tem embutido:

1. IDs inteiros sequenciais (Mongo usa ObjectId nativamente) -- ver next_id
   e SequentialIdDocument. Mantemos inteiro pra nao precisar tocar em nenhuma
   rota `<int:x_id>`, url_for ou teste existente (ver plano da migracao).
2. Cascade delete multi-nivel (o `reverse_delete_rule=CASCADE` do MongoEngine
   so cascade 1 nivel por campo) -- ver delete_cascade.
3. Transacao multi-documento -- ver atomic(). Documentado como
   nao-garantido no tier gratuito (M0) do Atlas; a flag
   MONGO_TRANSACTIONS_ENABLED (False em testes, onde o mongomock nao suporta
   sessao nenhuma) deixa isso opcional sem duplicar logica de negocio.
"""
from contextlib import contextmanager
from datetime import date, datetime, time

import mongoengine
from flask import abort, current_app
from pymongo import ReturnDocument


def primeiro_ou_404(queryset):
    """Equivalente ao `.first_or_404()`/`Model.query.get_or_404(id)` que o
    Flask-SQLAlchemy dava de graca -- MongoEngine nao tem essa conveniencia
    embutida. Uso: `primeiro_ou_404(Comunidade.objects(id=comunidade_id))`."""
    documento = queryset.first()
    if documento is None:
        abort(404)
    return documento

_DATA_FICTICIA = date(1970, 1, 1)  # so pra PureTimeField ter uma data pra "pendurar" a hora


class PureDateField(mongoengine.DateTimeField):
    """Campo de data pura (sem hora), equivalente ao db.Date do SQLAlchemy.

    BSON/Mongo so tem um tipo "Date" nativo, que e sempre datetime completo
    -- sem isso, ler um campo de volta devolveria um `datetime`, nao um
    `date`, e os dois NUNCA sao considerados iguais em Python (nem
    comparaveis com <, >), mesmo representando o mesmo dia. Isso quebraria
    silenciosamente qualquer comparacao com date.today() ou outro campo de
    data (`escala.data == outra_data`, `data_fim >= data_inicio`, etc.).
    Aceita tanto `date` quanto `datetime` na escrita; sempre devolve `date`
    na leitura."""

    def to_python(self, value):
        value = super().to_python(value)
        return value.date() if isinstance(value, datetime) else value

    def to_mongo(self, value):
        if isinstance(value, date) and not isinstance(value, datetime):
            value = datetime(value.year, value.month, value.day)
        return super().to_mongo(value)

    def validate(self, value):
        if isinstance(value, date) and not isinstance(value, datetime):
            value = datetime(value.year, value.month, value.day)
        return super().validate(value)

    def prepare_query_value(self, op, value):
        if isinstance(value, date) and not isinstance(value, datetime):
            value = datetime(value.year, value.month, value.day)
        return super().prepare_query_value(op, value)


class PureTimeField(mongoengine.DateTimeField):
    """Campo de hora pura (sem data), equivalente ao db.Time do SQLAlchemy --
    mesma logica do PureDateField acima, so que "pendurando" a hora numa
    data ficticia fixa (1970-01-01, nunca exposta) pra caber no unico tipo
    Date que o Mongo tem. Sempre devolve `time` na leitura."""

    def to_python(self, value):
        value = super().to_python(value)
        return value.time() if isinstance(value, datetime) else value

    def to_mongo(self, value):
        if isinstance(value, time):
            value = datetime.combine(_DATA_FICTICIA, value)
        return super().to_mongo(value)

    def validate(self, value):
        if isinstance(value, time):
            value = datetime.combine(_DATA_FICTICIA, value)
        return super().validate(value)

    def prepare_query_value(self, op, value):
        if isinstance(value, time):
            value = datetime.combine(_DATA_FICTICIA, value)
        return super().prepare_query_value(op, value)


def conectar_mongo(app):
    """Chamado uma vez por create_app (ver app/__init__.py), do mesmo jeito
    que `db.init_app(app)` conecta o Postgres. Convive com o Postgres/
    SQLAlchemy enquanto a migracao esta em andamento -- so conecta de fato
    se MONGODB_URI estiver configurada (producao/dev) ou MONGO_USE_MOCK
    estiver ligado (testes); sem nenhum dos dois, nao faz nada (mantem o
    app funcionando 100% em cima do Postgres, como hoje, enquanto nenhum
    modulo ainda foi migrado)."""
    mongoengine.disconnect_all()  # evita erro de "conexao ja existe com outros parametros" quando create_app roda mais de uma vez no mesmo processo (cada teste cria um app novo)

    if app.config.get("MONGO_USE_MOCK"):
        import mongomock
        mongoengine.connect(
            db="tybenson_test", mongo_client_class=mongomock.MongoClient,
            alias="default", uuidRepresentation="standard",
        )
        return

    uri = app.config.get("MONGODB_URI")
    if not uri:
        return
    mongoengine.connect(host=uri, alias="default", uuidRepresentation="standard")


def next_id(nome_sequencia):
    """Gera o proximo inteiro de uma sequencia nomeada (equivalente a um
    SERIAL/IDENTITY do Postgres), via um documento em `counters` incrementado
    atomicamente (find_one_and_update com $inc evita corrida entre
    requisicoes concorrentes -- duas chamadas simultaneas nunca recebem o
    mesmo numero)."""
    doc = mongoengine.get_db().counters.find_one_and_update(
        {"_id": nome_sequencia},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return doc["seq"]


class SequentialIdDocument(mongoengine.Document):
    """Base pra Documents que precisam manter o mesmo id inteiro sequencial
    que tinham como PK no Postgres (em vez do ObjectId nativo do Mongo).

    `meta["abstract"] = True` faz o MongoEngine tratar esta classe soh como
    base -- nao vira uma collection propria, cada subclasse ganha a sua.
    Subclasses devem definir `_nome_sequencia` (nome da chave em `counters`,
    ex: "usuarios", "comunidades") e, se quiserem, o resto dos campos.
    """
    meta = {"abstract": True}

    id = mongoengine.IntField(primary_key=True)

    def save(self, *args, **kwargs):
        if self.id is None:
            self.id = next_id(self._nome_sequencia)
        return super().save(*args, **kwargs)


def delete_cascade(doc):
    """Deleta `doc` e, recursivamente, todo documento que depende dele --
    equivalente ao `cascade="all, delete-orphan"` do SQLAlchemy, mas
    percorrendo QUALQUER profundidade (o `reverse_delete_rule` nativo do
    MongoEngine so cascade 1 nivel por campo, nao serve pra arvores como
    Comunidade -> Ministerio -> Escala -> Funcao).

    Cada classe com dependentes deve implementar `cascade_children(self)`,
    devolvendo uma lista de querysets (ex: `[Evento.objects(comunidade=self)]`).
    Classes sem dependentes (a maioria) nao precisam implementar nada -- o
    `getattr` abaixo trata a ausencia do metodo como "nao tem filhos"."""
    obter_filhos = getattr(doc, "cascade_children", None)
    if obter_filhos is not None:
        for queryset in obter_filhos():
            for filho in queryset:
                delete_cascade(filho)
    doc.delete()


@contextmanager
def atomic():
    """Agrupa varias escritas numa unica transacao multi-documento, quando
    o backend em uso suporta (Atlas real, qualquer tier -- inclusive M0,
    que roda como replica set; nao suportado pelo mongomock usado nos
    testes, ver MONGO_TRANSACTIONS_ENABLED). Uso:

        with atomic() as sessao:
            doc1.save(session=sessao)
            doc2.save(session=sessao)

    `sessao` vem None quando a flag esta desligada -- todo `.save(session=s)`
    aceita `session=None` normalmente (grava direto, sem transacao), entao o
    mesmo codigo funciona nos dois casos sem precisar de `if`."""
    if not current_app.config.get("MONGO_TRANSACTIONS_ENABLED", True):
        yield None
        return

    conexao = mongoengine.get_connection()
    with conexao.start_session() as sessao:
        with sessao.start_transaction():
            yield sessao
