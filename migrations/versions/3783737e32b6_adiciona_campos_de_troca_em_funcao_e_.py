"""adiciona campos de troca em Funcao e escala_id/tipo em Notificacao

Revision ID: 3783737e32b6
Revises: 11380c7a46c9
Create Date: 2026-08-27 12:25:47.422040

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3783737e32b6'
down_revision = '11380c7a46c9'
branch_labels = None
depends_on = None


def upgrade():
    # Nota: o autogenerate tambem detectou 3 foreign keys ausentes em
    # escala_membros/escalas (drift entre o model e o banco, mesmo caso ja
    # visto na migration 11380c7a46c9 -- residuo de quando o projeto rodava
    # so em SQLite). Removidas dessa migration de proposito, mesmo motivo.
    with op.batch_alter_table('escala_funcoes', schema=None) as batch_op:
        batch_op.add_column(sa.Column('troca_motivo', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('troca_sugestao_membro_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(None, 'escala_membros', ['troca_sugestao_membro_id'], ['id'])

    with op.batch_alter_table('notificacoes', schema=None) as batch_op:
        batch_op.add_column(sa.Column('escala_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('tipo', sa.String(length=30), nullable=True))
        batch_op.create_foreign_key(None, 'escalas', ['escala_id'], ['id'], ondelete='SET NULL')


def downgrade():
    with op.batch_alter_table('notificacoes', schema=None) as batch_op:
        batch_op.drop_constraint(None, type_='foreignkey')
        batch_op.drop_column('tipo')
        batch_op.drop_column('escala_id')

    with op.batch_alter_table('escala_funcoes', schema=None) as batch_op:
        batch_op.drop_constraint(None, type_='foreignkey')
        batch_op.drop_column('troca_sugestao_membro_id')
        batch_op.drop_column('troca_motivo')
