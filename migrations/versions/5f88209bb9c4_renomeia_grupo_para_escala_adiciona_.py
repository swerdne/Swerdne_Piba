"""renomeia grupo para escala, adiciona departamento data horario

Revision ID: 5f88209bb9c4
Revises: 962f212a5b72
Create Date: 2026-07-22 03:26:16.311075

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '5f88209bb9c4'
down_revision = '962f212a5b72'
branch_labels = None
depends_on = None


def upgrade():
    # Colunas novas direto com NOT NULL + DEFAULT (SQLite preenche as linhas
    # existentes com o default no mesmo comando -- evita precisar de um passo
    # separado soh para backfill).
    op.execute("ALTER TABLE escala_grupos ADD COLUMN departamento VARCHAR(40) NOT NULL DEFAULT 'Louvor'")
    op.execute("ALTER TABLE escala_grupos ADD COLUMN data DATE")
    op.execute("ALTER TABLE escala_grupos ADD COLUMN horario TIME")
    # SQLite nao aceita CURRENT_TIMESTAMP como default em ADD COLUMN (precisa
    # ser uma constante) -- usa uma data fixa soh para preencher linhas antigas.
    op.execute("ALTER TABLE escala_grupos ADD COLUMN criada_em TIMESTAMP NOT NULL DEFAULT '2026-01-01 00:00:00'")
    op.execute("ALTER TABLE escala_grupos ADD COLUMN notificado_24h_em TIMESTAMP")
    op.execute("ALTER TABLE escala_grupos ADD COLUMN notificado_16h_em TIMESTAMP")

    # O nome de uma escala agora pode se repetir (ex: "Culto Domingo" toda
    # semana) -- a restricao antiga de nome unico por usuario nao faz mais sentido.
    with op.batch_alter_table('escala_grupos', schema=None) as batch_op:
        batch_op.drop_constraint('uq_escala_grupos_usuario_nome', type_='unique')

    op.execute("ALTER TABLE escala_grupos RENAME TO escalas")
    op.execute("ALTER TABLE escala_funcoes RENAME COLUMN grupo_id TO escala_id")

    # Higienizacao: a FK de escala_funcoes ficou apontando para um nome de
    # tabela orfao ("escala_grupos_old") de uma migracao anterior que fez
    # CREATE+DROP em vez de RENAME. Sem impacto funcional (o SQLite nao aplica
    # foreign keys neste projeto), mas o texto do schema fica correto assim.
    op.execute("ALTER TABLE escala_funcoes RENAME TO escala_funcoes_old")
    op.execute(
        """
        CREATE TABLE escala_funcoes (
            id INTEGER NOT NULL,
            escala_id INTEGER NOT NULL,
            nome VARCHAR(80) NOT NULL,
            ordem INTEGER NOT NULL,
            membro_id INTEGER,
            status VARCHAR(20),
            notificado_em TIMESTAMP,
            PRIMARY KEY (id),
            FOREIGN KEY(escala_id) REFERENCES escalas (id),
            FOREIGN KEY(membro_id) REFERENCES escala_membros (id)
        )
        """
    )
    op.execute(
        "INSERT INTO escala_funcoes (id, escala_id, nome, ordem, membro_id, status, notificado_em) "
        "SELECT id, escala_id, nome, ordem, membro_id, status, notificado_em FROM escala_funcoes_old"
    )
    op.execute("DROP TABLE escala_funcoes_old")


def downgrade():
    op.execute("ALTER TABLE escala_funcoes RENAME COLUMN escala_id TO grupo_id")
    op.execute("ALTER TABLE escalas RENAME TO escala_grupos")

    with op.batch_alter_table('escala_grupos', schema=None) as batch_op:
        batch_op.create_unique_constraint('uq_escala_grupos_usuario_nome', ['usuario_id', 'nome'])
        batch_op.drop_column('notificado_16h_em')
        batch_op.drop_column('notificado_24h_em')
        batch_op.drop_column('criada_em')
        batch_op.drop_column('horario')
        batch_op.drop_column('data')
        batch_op.drop_column('departamento')
