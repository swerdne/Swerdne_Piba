"""adiciona ciclo de disponibilidade e segmentos de membro

Revision ID: 44938754d119
Revises: 3783737e32b6
Create Date: 2026-08-30 16:44:30.359066

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '44938754d119'
down_revision = '3783737e32b6'
branch_labels = None
depends_on = None


def upgrade():
    # Nota: o autogenerate tambem detectou 3 foreign keys ausentes em
    # escala_membros/escalas (drift entre o model e o banco, mesmo caso ja
    # visto nas migrations 11380c7a46c9/3783737e32b6 -- residuo de quando o
    # projeto rodava so em SQLite). Removidas dessa migration de proposito,
    # mesmo motivo.
    op.create_table('escala_ciclos_disponibilidade',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('membro_id', sa.Integer(), nullable=False),
    sa.Column('nome', sa.String(length=80), nullable=False),
    sa.Column('data_inicio', sa.Date(), nullable=False),
    sa.ForeignKeyConstraint(['membro_id'], ['escala_membros.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('escala_ciclo_segmentos',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('ciclo_id', sa.Integer(), nullable=False),
    sa.Column('ordem', sa.Integer(), nullable=False),
    sa.Column('nome', sa.String(length=40), nullable=False),
    sa.Column('duracao_dias', sa.Integer(), nullable=False),
    sa.Column('indisponivel', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['ciclo_id'], ['escala_ciclos_disponibilidade.id'], ),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    op.drop_table('escala_ciclo_segmentos')
    op.drop_table('escala_ciclos_disponibilidade')
