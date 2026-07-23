"""torna ministerio_id obrigatorio em escalas, remove comunidade_id

Revision ID: bd3fc02901ea
Revises: 75e1cee93835
Create Date: 2026-07-22 13:15:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'bd3fc02901ea'
down_revision = '75e1cee93835'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('escalas', schema=None) as batch_op:
        batch_op.alter_column('ministerio_id', existing_type=sa.INTEGER(), nullable=False)
        batch_op.drop_column('comunidade_id')


def downgrade():
    with op.batch_alter_table('escalas', schema=None) as batch_op:
        batch_op.add_column(sa.Column('comunidade_id', sa.INTEGER(), nullable=True))
        batch_op.alter_column('ministerio_id', existing_type=sa.INTEGER(), nullable=True)

    conn = op.get_bind()
    conn.execute(sa.text(
        "UPDATE escalas SET comunidade_id = ("
        "SELECT m.comunidade_id FROM ministerios m WHERE m.id = escalas.ministerio_id"
        ")"
    ))
