"""adiciona eventos da comunidade

Revision ID: 1d89018f9c8f
Revises: 410a58795ae3
Create Date: 2026-09-23 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '1d89018f9c8f'
down_revision = '410a58795ae3'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'comunidade_eventos',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('comunidade_id', sa.Integer(), nullable=False),
        sa.Column('nome', sa.String(length=120), nullable=False),
        sa.Column('descricao', sa.Text(), nullable=True),
        sa.Column('data', sa.Date(), nullable=False),
        sa.Column('data_fim', sa.Date(), nullable=True),
        sa.Column('horario', sa.Time(), nullable=True),
        sa.Column('local', sa.String(length=200), nullable=True),
        sa.Column('criado_em', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['comunidade_id'], ['comunidades.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade():
    op.drop_table('comunidade_eventos')
