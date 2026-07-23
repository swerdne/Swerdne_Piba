"""adiciona campos de geracao por rodizio a escalas

Escala ganha o vinculo (opcional) com o Turno de Rodizio que a gerou -- ver
app/plantao/sincronizacao.py. plantao_turno_id/plantao_periodo identificam a
qual turno/periodo essa ocorrencia corresponde (None = escala manual, criada
fora do rodizio); plantao_fixado trava uma ocorrencia especifica pra o sync
nao sobrescrever (ausencia remanejada ou edicao manual).

Revision ID: 90778b537d1f
Revises: 889df47f5510
Create Date: 2026-07-23 10:05:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '90778b537d1f'
down_revision = '889df47f5510'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE escalas ADD COLUMN plantao_turno_id INTEGER")
    op.execute("ALTER TABLE escalas ADD COLUMN plantao_periodo INTEGER")
    op.execute("ALTER TABLE escalas ADD COLUMN plantao_fixado BOOLEAN NOT NULL DEFAULT 0")


def downgrade():
    with op.batch_alter_table('escalas', schema=None) as batch_op:
        batch_op.drop_column('plantao_fixado')
        batch_op.drop_column('plantao_periodo')
        batch_op.drop_column('plantao_turno_id')
