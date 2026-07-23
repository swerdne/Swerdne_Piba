"""adiciona tipo (funcao/subcabecalho) a escala_funcoes

Revision ID: 8c900fb22a0e
Revises: 4ec0b76bcc3a
Create Date: 2026-07-22 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '8c900fb22a0e'
down_revision = '4ec0b76bcc3a'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE escala_funcoes ADD COLUMN tipo VARCHAR(20) NOT NULL DEFAULT 'funcao'")


def downgrade():
    with op.batch_alter_table('escala_funcoes', schema=None) as batch_op:
        batch_op.drop_column('tipo')
