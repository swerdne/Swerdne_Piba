"""adiciona repertorio de musicas a escala

Revision ID: 1b6258685dda
Revises: fa010deace97
Create Date: 2026-09-23 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '1b6258685dda'
down_revision = 'fa010deace97'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'escala_repertorio',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('escala_id', sa.Integer(), nullable=False),
        sa.Column('nome_musica', sa.String(length=150), nullable=False),
        sa.Column('tom', sa.String(length=10), nullable=True),
        sa.Column('link', sa.String(length=500), nullable=True),
        sa.Column('ordem', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['escala_id'], ['escalas.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade():
    op.drop_table('escala_repertorio')
