"""cria tabela ministerios

Revision ID: b5183e354bac
Revises: 8c900fb22a0e
Create Date: 2026-07-22 13:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b5183e354bac'
down_revision = '8c900fb22a0e'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'ministerios',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('comunidade_id', sa.Integer(), nullable=False),
        sa.Column('nome', sa.String(length=120), nullable=False),
        sa.Column('descricao', sa.Text(), nullable=True),
        sa.Column('imagem', sa.String(length=500), nullable=True),
        sa.Column('criada_em', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['comunidade_id'], ['comunidades.id']),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade():
    op.drop_table('ministerios')
