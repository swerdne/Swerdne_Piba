"""Migracao de dados: Postgres (schema legado) -> MongoDB (Fase 8 do plano).

Le cada tabela do Postgres na ordem de dependencia, preservando o id inteiro
original de cada linha (sem tabela de remapeamento -- e assim que nenhuma
rota `<int:x_id>`, `url_for(...)` ou notificacao/convite antigo com um id
guardado precisa mudar). Ao final de cada collection, semeia o counter
correspondente (ver app/db_utils.py::next_id) com o maior id migrado, pra
o proximo documento criado pelo app (ja rodando 100% em Mongo, pos-corte)
continuar a numeracao de onde a producao parou.

So le do Postgres (nunca escreve/apaga nada la) -- o Neon continua intacto
como rede de seguranca depois do corte, conforme o plano.

Chamado via `flask migrar-dados-mongo` (ver app/__init__.py). Precisa de um
app com AMBAS as conexoes configuradas ao mesmo tempo (DATABASE_URL apontando
pro Postgres de origem e MONGODB_URI apontando pro Mongo de destino) -- uma
combinacao que so faz sentido durante o corte em si, nunca em execucao normal
(dev/producao rodam com uma ou outra, nunca as duas ao mesmo tempo antes do
corte).
"""
import mongoengine
from sqlalchemy import MetaData, Table, select

from app.extensions import db

from app.auth.models import User
from app.comunidade.models import Comunidade, UsuarioComunidade, Evento
from app.convites.models import Convite
from app.ministerio.models import Ministerio, UsuarioMinisterio, Crianca, CheckInCrianca
from app.escala.models import (
    Membro,
    CicloDisponibilidade,
    SegmentoCiclo,
    Escala,
    Funcao,
    ItemRepertorio,
)
from app.plantao.models import TurnoPlantao, EquipeTurno, EquipeMembro
from app.notificacoes import Notificacao

# Ordem de dependencia (ver secao 8 do plano da migracao) -- nao afeta
# corretude (MongoEngine nao valida integridade referencial na escrita),
# so torna o log de progresso legivel na mesma ordem que um humano lendo o
# plano esperaria.
ORDEM_DE_MIGRACAO = [
    User,
    Comunidade,
    UsuarioComunidade,
    Convite,
    Ministerio,
    UsuarioMinisterio,
    Crianca,
    CheckInCrianca,
    Membro,
    CicloDisponibilidade,
    SegmentoCiclo,
    Escala,
    Funcao,
    ItemRepertorio,
    TurnoPlantao,
    EquipeTurno,
    EquipeMembro,
    Notificacao,
]


class ErroDeMigracao(Exception):
    """Erro fatal da migracao -- sempre para o processo (nunca continua
    parcialmente: uma migracao pela metade e pior que nenhuma, dado que o
    corte de producao depende de contagens batendo exatamente)."""


def _campos_persistidos(documento_cls):
    """Nomes dos campos MongoEngine de verdade (`id` incluso) -- exclui as
    `@property` (usuario/comunidade/escala/etc.), que nunca sao campos
    armazenados. Listas (ex: User.tutoriais_vistos) nasceram ja no Mongo,
    depois da migracao -- nao tem coluna no Postgres."""
    import mongoengine

    return [nome for nome, campo in documento_cls._fields.items() if not isinstance(campo, mongoengine.ListField)]


def _validar_schema(tabela, documento_cls, campos):
    faltando = [c for c in campos if c not in tabela.columns]
    if faltando:
        raise ErroDeMigracao(
            f"{documento_cls._meta['collection']}: campo(s) {faltando} existem no "
            f"model Mongo mas nao na tabela Postgres '{tabela.name}' -- schema "
            f"desalinhado, abortando antes de escrever qualquer coisa."
        )


def _verificar_destino_vazio(documento_cls, forcar):
    """Trava contra rodar a migracao 2x sem querer. NAO e sobre duplicacao --
    `Document.save()` com um `id` que ja existe SUBSTITUI o documento (Mongo
    troca por `_id`, nao insere uma segunda linha) -- rodar de novo com os
    MESMOS dados de origem e ate inofensivo. O risco real e sobrescrever
    silenciosamente qualquer mudanca que o app ja tenha gravado nessas
    collections depois da 1a migracao (ex: rodar a migracao de novo por
    engano depois que o corte ja aconteceu e producao ja esta escrevendo no
    Mongo)."""
    if forcar:
        return
    existente = documento_cls.objects.first()
    if existente is not None:
        raise ErroDeMigracao(
            f"Collection '{documento_cls._meta['collection']}' ja tem documentos -- "
            f"abortando pra nao sobrescrever silenciosamente dados que o app possa "
            f"ja ter gravado ali depois de uma migracao anterior. Se a intencao e "
            f"mesmo re-rodar por cima (ex: corrigindo algo antes do corte de verdade "
            f"acontecer), use --force."
        )


def _seed_counter(documento_cls, maior_id):
    """Semeia `counters` com o maior id migrado -- o proximo next_id() (ver
    app/db_utils.py) faz $inc e devolve maior_id+1, continuando a numeracao
    de onde a producao parou. So roda se pelo menos 1 linha foi migrada
    (collection vazia mantem o counter intocado, next_id() comeca do 1
    normalmente, igual uma collection nova)."""
    mongoengine.get_db().counters.update_one(
        {"_id": documento_cls._nome_sequencia},
        {"$set": {"seq": maior_id}},
        upsert=True,
    )


def migrar_tabela(engine, metadata, documento_cls, dry_run, force, log):
    nome_collection = documento_cls._meta["collection"]
    campos = _campos_persistidos(documento_cls)

    tabela = Table(nome_collection, metadata, autoload_with=engine)
    _validar_schema(tabela, documento_cls, campos)

    if not dry_run:
        _verificar_destino_vazio(documento_cls, force)

    with engine.connect() as conexao:
        linhas = conexao.execute(select(tabela).order_by(tabela.c.id)).fetchall()

    total = 0
    maior_id = 0
    for linha in linhas:
        valores = {campo: getattr(linha, campo) for campo in campos}
        maior_id = max(maior_id, valores["id"])
        if not dry_run:
            documento_cls(**valores).save()
        total += 1

    mensagem = f"{nome_collection}: {total} linha(s) migrada(s)"
    if dry_run:
        mensagem += " [dry-run]"
    elif total:
        _seed_counter(documento_cls, maior_id)
        mensagem += f", counter semeado em {maior_id}"
    log(mensagem)
    return total


def executar_migracao(dry_run=False, force=False, log=print):
    """Ponto de entrada chamado pelo comando `flask migrar-dados-mongo`.

    `log` recebe uma linha de progresso por collection -- o comando CLI passa
    `click.echo`, os testes passam uma lista pra inspecionar depois."""
    engine = db.engine
    metadata = MetaData()

    resumo = {}
    for documento_cls in ORDEM_DE_MIGRACAO:
        resumo[documento_cls._meta["collection"]] = migrar_tabela(
            engine, metadata, documento_cls, dry_run=dry_run, force=force, log=log
        )

    total_geral = sum(resumo.values())
    sufixo = " [dry-run, nada foi escrito]" if dry_run else "."
    log(f"Total: {total_geral} linha(s) em {len(resumo)} collection(s){sufixo}")
    return resumo
