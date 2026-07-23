"""cria unique constraint turno+periodo em escalas

Isolada da migration anterior (que so adiciona colunas) porque
create_unique_constraint faz table-rebuild no SQLite via batch_alter_table --
operacao de risco diferente de um ADD COLUMN simples, mais facil de revisar/
reverter separada.

Revision ID: 7818b8bc1ef4
Revises: 90778b537d1f
Create Date: 2026-07-23 10:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7818b8bc1ef4'
down_revision = '90778b537d1f'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('escalas', schema=None) as batch_op:
        batch_op.create_unique_constraint(
            'uq_escala_plantao_turno_periodo', ['plantao_turno_id', 'plantao_periodo']
        )


def downgrade():
    with op.batch_alter_table('escalas', schema=None) as batch_op:
        batch_op.drop_constraint('uq_escala_plantao_turno_periodo', type_='unique')
