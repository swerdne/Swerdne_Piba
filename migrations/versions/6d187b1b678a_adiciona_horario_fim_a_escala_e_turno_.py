"""adiciona horario_fim a escala e turno_plantao

Revision ID: 6d187b1b678a
Revises: f8240c1baea9
Create Date: 2026-09-21 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6d187b1b678a'
down_revision = 'f8240c1baea9'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('escalas', schema=None) as batch_op:
        batch_op.add_column(sa.Column('horario_fim', sa.Time(), nullable=True))

    with op.batch_alter_table('turnos_plantao', schema=None) as batch_op:
        batch_op.add_column(sa.Column('horario_fim', sa.Time(), nullable=True))


def downgrade():
    with op.batch_alter_table('turnos_plantao', schema=None) as batch_op:
        batch_op.drop_column('horario_fim')

    with op.batch_alter_table('escalas', schema=None) as batch_op:
        batch_op.drop_column('horario_fim')
