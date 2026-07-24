"""adiciona usuario_id ao grupo da escala (nullable, backfill depois)

Revision ID: c7e3674500d1
Revises: 9e9b5511e38e
Create Date: 2026-07-22 02:18:27.946962

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c7e3674500d1'
down_revision = '9e9b5511e38e'
branch_labels = None
depends_on = None


def upgrade():
    # Feito com SQL manual (em vez de batch_alter_table) porque a constraint
    # UNIQUE(nome) antiga nao tem nome no SQLite, e o modo batch do Alembic
    # exige nome para (re)criar/derrubar constraints.
    op.execute("ALTER TABLE escala_grupos RENAME TO escala_grupos_old")
    op.execute(
        """
        CREATE TABLE escala_grupos (
            id INTEGER NOT NULL,
            usuario_id INTEGER,
            nome VARCHAR(80) NOT NULL,
            ordem INTEGER NOT NULL,
            PRIMARY KEY (id),
            CONSTRAINT uq_escala_grupos_usuario_nome UNIQUE (usuario_id, nome),
            FOREIGN KEY(usuario_id) REFERENCES users (id)
        )
        """
    )
    op.execute(
        "INSERT INTO escala_grupos (id, usuario_id, nome, ordem) "
        "SELECT id, NULL, nome, ordem FROM escala_grupos_old"
    )
    # No Postgres a FK escala_funcoes.grupo_id -> escala_grupos_old (o RENAME
    # nao muda o OID, so o nome de exibicao) ainda depende dessa tabela --
    # sem CASCADE o DROP falha (DependentObjectsStillExist). So derruba a
    # CONSTRAINT orfa (nao a tabela/dado de escala_funcoes); ela e recriada
    # apontando pro nome certo na migration seguinte (5f88209bb9c4), que ja
    # documentava esse orfao como inofensivo no SQLite (FK nao e enforced
    # aqui) -- so deixou de ser inofensivo quando passamos a rodar em cima de
    # um banco que aplica FK de verdade. SQLite nao aceita a clausula CASCADE
    # em DROP TABLE, entao so usa no Postgres.
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TABLE escala_grupos_old CASCADE")
    else:
        op.execute("DROP TABLE escala_grupos_old")


def downgrade():
    op.execute("ALTER TABLE escala_grupos RENAME TO escala_grupos_new")
    op.execute(
        """
        CREATE TABLE escala_grupos (
            id INTEGER NOT NULL,
            nome VARCHAR(80) NOT NULL,
            ordem INTEGER NOT NULL,
            PRIMARY KEY (id),
            UNIQUE (nome)
        )
        """
    )
    op.execute(
        "INSERT INTO escala_grupos (id, nome, ordem) SELECT id, nome, ordem FROM escala_grupos_new"
    )
    # Mesmo motivo do upgrade() -- ver comentario acima.
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TABLE escala_grupos_new CASCADE")
    else:
        op.execute("DROP TABLE escala_grupos_new")
