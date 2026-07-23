"""cria tabela comunidades

Revision ID: d1e05a2400d1
Revises: 5eb4f005b564
Create Date: 2026-07-22 09:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd1e05a2400d1'
down_revision = '5eb4f005b564'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'comunidades',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('nome', sa.String(length=120), nullable=False),
        sa.Column('descricao', sa.Text(), nullable=True),
        sa.Column('imagem', sa.String(length=500), nullable=True),
        sa.Column('usuario_id', sa.Integer(), nullable=False),
        sa.Column('criada_em', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['usuario_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade():
    op.drop_table('comunidades')
