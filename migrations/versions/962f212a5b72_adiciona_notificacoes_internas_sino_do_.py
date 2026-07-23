"""adiciona notificacoes internas (sino do dashboard)

Revision ID: 962f212a5b72
Revises: 4afe31e1b4bf
Create Date: 2026-07-22 02:43:53.022801

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '962f212a5b72'
down_revision = '4afe31e1b4bf'
branch_labels = None
depends_on = None


def upgrade():
    # (o diff em escala_funcoes.grupo_id e espurio, ver migracao anterior)
    op.create_table('notificacoes',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('usuario_id', sa.Integer(), nullable=False),
    sa.Column('titulo', sa.String(length=120), nullable=False),
    sa.Column('mensagem', sa.Text(), nullable=False),
    sa.Column('lida', sa.Boolean(), nullable=False),
    sa.Column('criada_em', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['usuario_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    op.drop_table('notificacoes')
