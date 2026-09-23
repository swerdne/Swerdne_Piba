"""adiciona checkin de criancas

Revision ID: 410a58795ae3
Revises: 1b6258685dda
Create Date: 2026-09-23 10:05:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '410a58795ae3'
down_revision = '1b6258685dda'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'ministerio_criancas',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('ministerio_id', sa.Integer(), nullable=False),
        sa.Column('nome', sa.String(length=120), nullable=False),
        sa.Column('data_nascimento', sa.Date(), nullable=True),
        sa.Column('responsavel_nome', sa.String(length=120), nullable=False),
        sa.Column('responsavel_telefone', sa.String(length=30), nullable=True),
        sa.Column('observacoes', sa.Text(), nullable=True),
        sa.Column('criada_em', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['ministerio_id'], ['ministerios.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'ministerio_checkins',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('crianca_id', sa.Integer(), nullable=False),
        sa.Column('data', sa.Date(), nullable=False),
        sa.Column('hora_entrada', sa.DateTime(), nullable=False),
        sa.Column('hora_saida', sa.DateTime(), nullable=True),
        sa.Column('codigo_seguranca', sa.String(length=6), nullable=False),
        sa.Column('registrado_por_id', sa.Integer(), nullable=False),
        sa.Column('retirado_por_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['crianca_id'], ['ministerio_criancas.id'], ),
        sa.ForeignKeyConstraint(['registrado_por_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['retirado_por_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade():
    op.drop_table('ministerio_checkins')
    op.drop_table('ministerio_criancas')
