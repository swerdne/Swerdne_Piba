"""corrige sequence de id ausente em escalas e escala_funcoes (Postgres)

Achado rodando contra Postgres de verdade: as migrations antigas
c7e3674500d1 (criou escala_grupos, depois renomeada pra escalas em
5f88209bb9c4) e 5f88209bb9c4 (recriou escala_funcoes) usam SQL cru
`CREATE TABLE ... (id INTEGER NOT NULL, ...)` -- no SQLite isso e
suficiente pra virar rowid autoincrement (INTEGER PRIMARY KEY e
tratado como alias de rowid mesmo escrito como PRIMARY KEY (id) em
constraint de tabela), mas no Postgres um INTEGER puro NAO gera valor
sozinho: sem sequence/DEFAULT associado, todo INSERT que nao informa
`id` explicitamente falha com NotNullViolation. As outras tabelas do
projeto foram criadas via op.create_table (Alembic/SQLAlchemy) e ja
tem sequence correta -- so essas duas, que nasceram de SQL cru, ficaram
sem.

So roda no Postgres (SQLite nao tem sequence e nao precisa disso -- o
rowid ja resolve sozinho).

Revision ID: 9309a0b3893f
Revises: 8d229dc8d317
Create Date: 2026-07-24 11:40:00.000000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '9309a0b3893f'
down_revision = '8d229dc8d317'
branch_labels = None
depends_on = None

TABELAS = ("escalas", "escala_funcoes")


def upgrade():
    if op.get_bind().dialect.name != "postgresql":
        return
    for tabela in TABELAS:
        seq = f"{tabela}_id_seq"
        op.execute(f"CREATE SEQUENCE IF NOT EXISTS {seq} OWNED BY {tabela}.id")
        # Comeca do proximo id livre (MAX(id)+1, ou 1 se a tabela estiver vazia)
        # pra nao colidir com linhas ja existentes.
        op.execute(f"SELECT setval('{seq}', COALESCE((SELECT MAX(id) FROM {tabela}), 0) + 1, false)")
        op.execute(f"ALTER TABLE {tabela} ALTER COLUMN id SET DEFAULT nextval('{seq}')")


def downgrade():
    if op.get_bind().dialect.name != "postgresql":
        return
    for tabela in TABELAS:
        op.execute(f"ALTER TABLE {tabela} ALTER COLUMN id DROP DEFAULT")
        op.execute(f"DROP SEQUENCE IF EXISTS {tabela}_id_seq")
