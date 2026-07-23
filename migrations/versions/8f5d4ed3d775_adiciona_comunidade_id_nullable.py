"""adiciona comunidade_id a escalas e escala_membros (nullable, backfill depois)

Revision ID: 8f5d4ed3d775
Revises: d1e05a2400d1
Create Date: 2026-07-22 09:05:00.000000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '8f5d4ed3d775'
down_revision = 'd1e05a2400d1'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE escalas ADD COLUMN comunidade_id INTEGER")
    op.execute("ALTER TABLE escala_membros ADD COLUMN comunidade_id INTEGER")


def downgrade():
    with op.batch_alter_table('escalas', schema=None) as batch_op:
        batch_op.drop_column('comunidade_id')

    with op.batch_alter_table('escala_membros', schema=None) as batch_op:
        batch_op.drop_column('comunidade_id')
