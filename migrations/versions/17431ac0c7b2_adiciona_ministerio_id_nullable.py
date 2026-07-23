"""adiciona ministerio_id a escalas (nullable, backfill depois)

Revision ID: 17431ac0c7b2
Revises: b5183e354bac
Create Date: 2026-07-22 13:05:00.000000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '17431ac0c7b2'
down_revision = 'b5183e354bac'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE escalas ADD COLUMN ministerio_id INTEGER")


def downgrade():
    with op.batch_alter_table('escalas', schema=None) as batch_op:
        batch_op.drop_column('ministerio_id')
