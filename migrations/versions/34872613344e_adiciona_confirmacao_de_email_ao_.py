"""adiciona confirmacao de email ao cadastro

Revision ID: 34872613344e
Revises: d78e7cdd121e
Create Date: 2026-08-12 21:50:27.593834

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '34872613344e'
down_revision = 'd78e7cdd121e'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('email_confirmado', sa.Boolean(), server_default=sa.text('true'), nullable=False))
        batch_op.add_column(sa.Column('token_confirmacao', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('token_confirmacao_expira_em', sa.DateTime(), nullable=True))
        batch_op.create_unique_constraint('uq_users_token_confirmacao', ['token_confirmacao'])


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_constraint('uq_users_token_confirmacao', type_='unique')
        batch_op.drop_column('token_confirmacao_expira_em')
        batch_op.drop_column('token_confirmacao')
        batch_op.drop_column('email_confirmado')
