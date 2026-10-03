"""Testes do script de migracao de dados Postgres -> Mongo (Fase 8).

Usa uma base SQLite local descartavel (arquivo temporario, nunca
:memory: -- precisa sobreviver a varias conexoes dentro do mesmo teste) com
um schema reconstruido a partir dos proprios models MongoEngine, nunca toca
Postgres/Mongo reais. Valida a LOGICA do script (leitura, preservacao de id,
seed de counters, checagens de seguranca) -- nao a fidelidade ao schema
historico exato do Postgres de producao, que so e verificada de verdade no
dry-run real contra um snapshot, na hora do corte (Fase 8 ainda nao
executada)."""
import os
import tempfile
from datetime import date, time

import mongoengine
import pytest
from sqlalchemy import Boolean, Column, Date, DateTime, Integer, MetaData, String, Table, Time, Float

from app import create_app
from app.extensions import db
from app.db_utils import PureDateField, PureTimeField, next_id
from app.migracao_dados import ORDEM_DE_MIGRACAO, ErroDeMigracao, executar_migracao, migrar_tabela
from app.auth.models import User
from app.comunidade.models import Comunidade, UsuarioComunidade
from app.ministerio.models import Ministerio
from app.escala.models import Escala, Funcao
from app.notificacoes import Notificacao


def _tipo_sql_para_campo(campo):
    # Pure*Field precisa vir ANTES de DateTimeField (sao subclasses dela).
    if isinstance(campo, PureDateField):
        return Date
    if isinstance(campo, PureTimeField):
        return Time
    if isinstance(campo, mongoengine.DateTimeField):
        return DateTime
    if isinstance(campo, mongoengine.BooleanField):
        return Boolean
    if isinstance(campo, mongoengine.IntField):
        return Integer
    if isinstance(campo, mongoengine.FloatField):
        return Float
    if isinstance(campo, mongoengine.StringField):
        return String
    raise TypeError(f"tipo de campo sem mapeamento de teste: {campo!r}")


def _tabela_a_partir_do_documento(documento_cls, metadata):
    """Reconstroi a tabela Postgres 'legada' a partir dos campos MongoEngine
    de verdade -- schema de teste autoconsistente com o que o script espera
    ler, pra validar a LOGICA de migracao (nao o schema historico exato)."""
    colunas = []
    for nome, campo in documento_cls._fields.items():
        if nome == "id":
            colunas.append(Column("id", Integer, primary_key=True, autoincrement=False))
        elif isinstance(campo, mongoengine.ListField):
            continue  # campo criado depois da migracao (ex: User.tutoriais_vistos) -- nao existia no Postgres
        else:
            colunas.append(Column(nome, _tipo_sql_para_campo(campo), nullable=not campo.required))
    return Table(documento_cls._meta["collection"], metadata, *colunas)


@pytest.fixture
def ambiente_migracao():
    """App de teste com MongoEngine em mongomock (via create_app('testing'))
    e SQLALCHEMY_DATABASE_URI redirecionada pra um SQLite em arquivo
    temporario, com TODAS as tabelas do ORDEM_DE_MIGRACAO criadas (vazias) --
    cada teste popula so as que precisa."""
    app = create_app("testing")
    caminho_temp = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name

    with app.app_context():
        app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{caminho_temp}"

        metadata = MetaData()
        tabelas = {
            documento_cls: _tabela_a_partir_do_documento(documento_cls, metadata)
            for documento_cls in ORDEM_DE_MIGRACAO
        }
        metadata.create_all(db.engine)

        yield app, tabelas

    os.remove(caminho_temp)
    mongoengine.disconnect_all()


def _inserir(tabela, **valores):
    with db.engine.begin() as conexao:
        conexao.execute(tabela.insert().values(**valores))


def test_migracao_completa_preserva_ids_e_dados(ambiente_migracao):
    app, tabelas = ambiente_migracao

    _inserir(tabelas[User], id=1, email="ana@example.com", name="Ana", foto_perfil=None,
             username="ana", password_hash="hash", google_id=None, theme="indigo",
             tutorial_comunidade_visto=False, eh_super_admin=False, email_confirmado=True,
             token_confirmacao=None, token_confirmacao_expira_em=None,
             token_redefinicao_senha=None, token_redefinicao_expira_em=None)
    _inserir(tabelas[User], id=2, email="bruno@example.com", name=None, foto_perfil=None,
             username=None, password_hash=None, google_id="google-123", theme="escuro",
             tutorial_comunidade_visto=True, eh_super_admin=False, email_confirmado=True,
             token_confirmacao=None, token_confirmacao_expira_em=None,
             token_redefinicao_senha=None, token_redefinicao_expira_em=None)

    _inserir(tabelas[Comunidade], id=10, nome="Comunidade Teste", descricao=None, imagem=None,
             usuario_id=1, criada_em=None, token_convite_publico=None)
    _inserir(tabelas[UsuarioComunidade], id=100, usuario_id=1, comunidade_id=10, papel="admin", criado_em=None)

    _inserir(tabelas[Ministerio], id=20, comunidade_id=10, nome="Louvor", descricao=None,
             imagem=None, criada_em=None, dias_culto=None)

    _inserir(tabelas[Escala], id=200, ministerio_id=20, nome="Culto de Domingo", departamento="Louvor",
             data=date(2026, 9, 6), horario=time(10, 0), horario_fim=None, criada_em=None,
             notificado_24h_em=None, notificado_16h_em=None, cancelada=False, cancelada_em=None,
             plantao_turno_id=None, plantao_periodo=None, plantao_fixado=False,
             turno_plantao_origem_id=None, cor_selecionada=None)
    _inserir(tabelas[Escala], id=201, ministerio_id=20, nome="Ensaio", departamento="Louvor",
             data=None, horario=None, horario_fim=None, criada_em=None,
             notificado_24h_em=None, notificado_16h_em=None, cancelada=False, cancelada_em=None,
             plantao_turno_id=None, plantao_periodo=None, plantao_fixado=False,
             turno_plantao_origem_id=None, cor_selecionada=None)

    _inserir(tabelas[Funcao], id=2000, escala_id=200, nome="Baixo", ordem=0, tipo="funcao",
             membro_id=None, status="nao_notificado", notificado_em=None, eh_convidado=False,
             troca_motivo=None, troca_sugestao_membro_id=None)

    _inserir(tabelas[Notificacao], id=30000, usuario_id=1, titulo="Bem-vindo", mensagem="Ola!",
             lida=False, criada_em=None, escala_id=200, tipo="escalado")

    eventos = []
    resumo = executar_migracao(dry_run=False, force=False, log=eventos.append)

    assert resumo == {
        "users": 2, "comunidades": 1, "usuario_comunidade": 1, "convites": 0,
        "ministerios": 1, "usuario_ministerio": 0, "ministerio_criancas": 0, "ministerio_checkins": 0,
        "escala_membros": 0, "escala_ciclos_disponibilidade": 0, "escala_ciclo_segmentos": 0,
        "escalas": 2, "escala_funcoes": 1, "escala_repertorio": 0,
        "turnos_plantao": 0, "turno_plantao_equipes": 0, "turno_plantao_equipe_membros": 0,
        "notificacoes": 1,
    }

    ana = User.objects(id=1).first()
    assert ana is not None
    assert ana.email == "ana@example.com"
    assert ana.username == "ana"
    assert ana.google_id is None

    bruno = User.objects(id=2).first()
    assert bruno.google_id == "google-123"
    assert bruno.username is None

    escala_com_data = Escala.objects(id=200).first()
    assert escala_com_data.data == date(2026, 9, 6)
    assert escala_com_data.horario == time(10, 0)

    escala_sem_data = Escala.objects(id=201).first()
    assert escala_sem_data.data is None
    assert escala_sem_data.horario is None

    funcao = Funcao.objects(id=2000).first()
    assert funcao.escala_id == 200
    assert funcao.nome == "Baixo"

    notificacao = Notificacao.objects(id=30000).first()
    assert notificacao.escala_id == 200

    # Counters semeados -- o proximo next_id() continua de onde a producao
    # parou, nao reseta do 1.
    assert next_id("usuarios") == 3
    assert next_id("comunidades") == 11
    assert next_id("escalas") == 202
    assert next_id("escala_funcoes") == 2001
    # Collection vazia (Convite) -- counter intocado, comeca do 1 normal.
    assert next_id("convites") == 1


def test_dry_run_nao_escreve_nada(ambiente_migracao):
    app, tabelas = ambiente_migracao
    _inserir(tabelas[User], id=1, email="ana@example.com", name="Ana", foto_perfil=None,
             username="ana", password_hash="hash", google_id=None, theme="indigo",
             tutorial_comunidade_visto=False, eh_super_admin=False, email_confirmado=True,
             token_confirmacao=None, token_confirmacao_expira_em=None,
             token_redefinicao_senha=None, token_redefinicao_expira_em=None)

    eventos = []
    resumo = executar_migracao(dry_run=True, force=False, log=eventos.append)

    assert resumo["users"] == 1
    assert User.objects.count() == 0  # nada foi escrito de fato
    assert any("dry-run" in linha for linha in eventos)


def test_recusa_migrar_de_novo_sem_force(ambiente_migracao):
    app, tabelas = ambiente_migracao
    _inserir(tabelas[User], id=1, email="ana@example.com", name="Ana", foto_perfil=None,
             username="ana", password_hash="hash", google_id=None, theme="indigo",
             tutorial_comunidade_visto=False, eh_super_admin=False, email_confirmado=True,
             token_confirmacao=None, token_confirmacao_expira_em=None,
             token_redefinicao_senha=None, token_redefinicao_expira_em=None)

    executar_migracao(dry_run=False, force=False, log=lambda *_: None)
    assert User.objects.count() == 1

    with pytest.raises(ErroDeMigracao, match="ja tem documentos"):
        executar_migracao(dry_run=False, force=False, log=lambda *_: None)

    # nao duplicou -- abortou antes de tocar em qualquer linha nova
    assert User.objects.count() == 1

    # --force ignora a checagem e migra de novo por cima -- Document.save()
    # com um id ja existente SUBSTITUI o documento (Mongo troca por _id, nao
    # insere uma 2a linha), entao a contagem nao dobra mesmo re-rodando.
    executar_migracao(dry_run=False, force=True, log=lambda *_: None)
    assert User.objects.count() == 1


class _DocumentoFalso:
    """Stub minimo pra exercitar a checagem de schema desalinhado em
    migrar_tabela sem depender de um Document Mongo real registrado."""

    _meta = {"collection": "users"}
    _nome_sequencia = "usuarios"
    _fields = {
        "id": mongoengine.IntField(primary_key=True),
        "email": mongoengine.StringField(required=True),
        "campo_que_nao_existe_no_postgres": mongoengine.StringField(required=True),
    }


def test_schema_desalinhado_aborta_sem_escrever(ambiente_migracao):
    app, tabelas = ambiente_migracao
    _inserir(tabelas[User], id=1, email="ana@example.com", name="Ana", foto_perfil=None,
             username="ana", password_hash="hash", google_id=None, theme="indigo",
             tutorial_comunidade_visto=False, eh_super_admin=False, email_confirmado=True,
             token_confirmacao=None, token_confirmacao_expira_em=None,
             token_redefinicao_senha=None, token_redefinicao_expira_em=None)

    with pytest.raises(ErroDeMigracao, match="schema desalinhado"):
        migrar_tabela(
            db.engine, MetaData(), _DocumentoFalso,
            dry_run=False, force=False, log=lambda *_: None,
        )

    assert User.objects.count() == 0
