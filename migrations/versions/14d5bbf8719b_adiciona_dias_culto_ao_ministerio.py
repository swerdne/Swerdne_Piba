"""adiciona dias_culto ao ministerio

Revision ID: 14d5bbf8719b
Revises: e7f5efc91f21
Create Date: 2026-09-20 18:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '14d5bbf8719b'
down_revision = 'e7f5efc91f21'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('ministerios', schema=None) as batch_op:
        batch_op.add_column(sa.Column('dias_culto', sa.String(length=20), nullable=True))


def downgrade():
    with op.batch_alter_table('ministerios', schema=None) as batch_op:
        batch_op.drop_column('dias_culto')
