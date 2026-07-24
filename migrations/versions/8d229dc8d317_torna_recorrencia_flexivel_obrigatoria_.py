"""torna recorrencia flexivel obrigatoria e remove recorrencia antiga

Ultima etapa do padrao nullable -> backfill -> not null: agora que todo
turno existente ja tem intervalo_recorrencia/unidade_recorrencia/
termino_tipo preenchidos (migration anterior), torna essas 3 colunas
obrigatorias e remove a coluna `recorrencia` antiga (String diaria/semanal/
mensal), substituida pelo sistema flexivel -- ver app/plantao/models.py.

Revision ID: 8d229dc8d317
Revises: 645d608def33
Create Date: 2026-07-23 16:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '8d229dc8d317'
down_revision = '645d608def33'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('turnos_plantao', schema=None) as batch_op:
        batch_op.alter_column('intervalo_recorrencia', existing_type=sa.Integer(), nullable=False)
        batch_op.alter_column('unidade_recorrencia', existing_type=sa.String(length=10), nullable=False)
        batch_op.alter_column('termino_tipo', existing_type=sa.String(length=15), nullable=False)
        batch_op.drop_column('recorrencia')


def downgrade():
    with op.batch_alter_table('turnos_plantao', schema=None) as batch_op:
        batch_op.add_column(sa.Column('recorrencia', sa.String(length=10), nullable=True))
        batch_op.alter_column('intervalo_recorrencia', existing_type=sa.Integer(), nullable=True)
        batch_op.alter_column('unidade_recorrencia', existing_type=sa.String(length=10), nullable=True)
        batch_op.alter_column('termino_tipo', existing_type=sa.String(length=15), nullable=True)

    conn = op.get_bind()
    conn.execute(sa.text(
        "UPDATE turnos_plantao SET recorrencia = CASE unidade_recorrencia "
        "WHEN 'dia' THEN 'diaria' WHEN 'semana' THEN 'semanal' ELSE 'mensal' END"
    ))
    with op.batch_alter_table('turnos_plantao', schema=None) as batch_op:
        batch_op.alter_column('recorrencia', existing_type=sa.String(length=10), nullable=False)
