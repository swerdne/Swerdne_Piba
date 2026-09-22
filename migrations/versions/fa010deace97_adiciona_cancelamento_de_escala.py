"""adiciona cancelamento de escala

Revision ID: fa010deace97
Revises: 6d187b1b678a
Create Date: 2026-09-22 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'fa010deace97'
down_revision = '6d187b1b678a'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('escalas', schema=None) as batch_op:
        batch_op.add_column(sa.Column('cancelada', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column('cancelada_em', sa.DateTime(), nullable=True))


def downgrade():
    with op.batch_alter_table('escalas', schema=None) as batch_op:
        batch_op.drop_column('cancelada_em')
        batch_op.drop_column('cancelada')
