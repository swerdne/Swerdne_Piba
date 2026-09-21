"""adiciona token de convite publico a comunidade

Revision ID: f8240c1baea9
Revises: 14d5bbf8719b
Create Date: 2026-09-21 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f8240c1baea9'
down_revision = '14d5bbf8719b'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('comunidades', schema=None) as batch_op:
        batch_op.add_column(sa.Column('token_convite_publico', sa.String(length=64), nullable=True))
        batch_op.create_unique_constraint('uq_comunidades_token_convite_publico', ['token_convite_publico'])


def downgrade():
    with op.batch_alter_table('comunidades', schema=None) as batch_op:
        batch_op.drop_constraint('uq_comunidades_token_convite_publico', type_='unique')
        batch_op.drop_column('token_convite_publico')
