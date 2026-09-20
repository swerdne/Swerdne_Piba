"""adiciona token de redefinicao de senha ao user

Revision ID: e7f5efc91f21
Revises: 44938754d119
Create Date: 2026-09-20 05:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e7f5efc91f21'
down_revision = '44938754d119'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('token_redefinicao_senha', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('token_redefinicao_expira_em', sa.DateTime(), nullable=True))
        batch_op.create_unique_constraint('uq_users_token_redefinicao_senha', ['token_redefinicao_senha'])


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_constraint('uq_users_token_redefinicao_senha', type_='unique')
        batch_op.drop_column('token_redefinicao_expira_em')
        batch_op.drop_column('token_redefinicao_senha')
