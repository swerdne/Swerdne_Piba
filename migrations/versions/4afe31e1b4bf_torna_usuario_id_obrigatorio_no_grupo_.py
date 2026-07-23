"""torna usuario_id obrigatorio no grupo da escala

Revision ID: 4afe31e1b4bf
Revises: c7e3674500d1
Create Date: 2026-07-22 02:21:33.624286

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4afe31e1b4bf'
down_revision = 'c7e3674500d1'
branch_labels = None
depends_on = None


def upgrade():
    # (o diff em escala_funcoes.grupo_id e espurio -- reflexo da reconstrucao
    # manual da tabela escala_grupos na migracao anterior, nao uma mudanca real)
    with op.batch_alter_table('escala_grupos', schema=None) as batch_op:
        batch_op.alter_column('usuario_id',
               existing_type=sa.INTEGER(),
               nullable=False)


def downgrade():
    with op.batch_alter_table('escala_grupos', schema=None) as batch_op:
        batch_op.alter_column('usuario_id',
               existing_type=sa.INTEGER(),
               nullable=True)
