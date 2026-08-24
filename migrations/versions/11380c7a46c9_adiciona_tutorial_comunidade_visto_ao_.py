"""adiciona tutorial_comunidade_visto ao User

Revision ID: 11380c7a46c9
Revises: 34872613344e
Create Date: 2026-08-24 01:09:13.713709

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '11380c7a46c9'
down_revision = '34872613344e'
branch_labels = None
depends_on = None


def upgrade():
    # Nota: o autogenerate tambem detectou 3 foreign keys ausentes em
    # escala_membros/escalas (drift entre o model e o banco, provavel residuo
    # de quando o projeto rodava so em SQLite -- ver CLAUDE.md sobre FK nao
    # enforced por padrao la). Removidas dessa migration de proposito: fora
    # de escopo aqui e arriscado aplicar sem investigar dado orfao antes.
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('tutorial_comunidade_visto', sa.Boolean(), server_default=sa.text('false'), nullable=False))


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('tutorial_comunidade_visto')
