"""torna comunidade_id obrigatorio em escalas e escala_membros

Revision ID: 4ec0b76bcc3a
Revises: e2dd951e4f2c
Create Date: 2026-07-22 09:15:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4ec0b76bcc3a'
down_revision = 'e2dd951e4f2c'
branch_labels = None
depends_on = None


def upgrade():
    # Membros nunca escalados em nenhuma funcao ficam sem como inferir a
    # comunidade (o fluxo atual so criava Membro ao escalar) -- sao lixo
    # orfao, entao sao removidos antes de travar a coluna como obrigatoria.
    op.execute("DELETE FROM escala_membros WHERE comunidade_id IS NULL")

    with op.batch_alter_table('escalas', schema=None) as batch_op:
        batch_op.alter_column('comunidade_id', existing_type=sa.INTEGER(), nullable=False)
        batch_op.drop_column('usuario_id')

    with op.batch_alter_table('escala_membros', schema=None) as batch_op:
        batch_op.alter_column('comunidade_id', existing_type=sa.INTEGER(), nullable=False)


def downgrade():
    with op.batch_alter_table('escala_membros', schema=None) as batch_op:
        batch_op.alter_column('comunidade_id', existing_type=sa.INTEGER(), nullable=True)

    with op.batch_alter_table('escalas', schema=None) as batch_op:
        batch_op.add_column(sa.Column('usuario_id', sa.INTEGER(), nullable=True))
        batch_op.alter_column('comunidade_id', existing_type=sa.INTEGER(), nullable=True)

    conn = op.get_bind()
    conn.execute(sa.text(
        "UPDATE escalas SET usuario_id = ("
        "SELECT c.usuario_id FROM comunidades c WHERE c.id = escalas.comunidade_id"
        ")"
    ))
