"""adiciona campos de recorrencia flexivel a turnos_plantao

Substitui a recorrencia simples (diaria/semanal/mensal, sempre a cada 1
unidade) por um sistema estilo Google Agenda: intervalo livre, dias da
semana especificos quando semanal, 3 modos quando mensal (dia fixo / ultimo
dia-da-semana / enesimo dia-da-semana) e termino por nunca/data/numero de
ocorrencias -- ver app/plantao/models.py.

So adiciona as colunas nullable aqui; o backfill a partir da coluna
`recorrencia` antiga (que ainda existe nesta migration) e o remove da coluna
antiga vem nas 2 migrations seguintes, seguindo o padrao ja usado no projeto
pra coluna obrigatoria em tabela populada.

Revision ID: 6e02be038f76
Revises: 642ac09da0fd
Create Date: 2026-07-23 16:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6e02be038f76'
down_revision = '642ac09da0fd'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('turnos_plantao', sa.Column('intervalo_recorrencia', sa.Integer(), nullable=True))
    op.add_column('turnos_plantao', sa.Column('unidade_recorrencia', sa.String(length=10), nullable=True))
    op.add_column('turnos_plantao', sa.Column('dias_semana', sa.String(length=20), nullable=True))
    op.add_column('turnos_plantao', sa.Column('modo_mensal', sa.String(length=20), nullable=True))
    op.add_column('turnos_plantao', sa.Column('termino_tipo', sa.String(length=15), nullable=True))
    op.add_column('turnos_plantao', sa.Column('termino_data', sa.Date(), nullable=True))
    op.add_column('turnos_plantao', sa.Column('termino_ocorrencias', sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table('turnos_plantao', schema=None) as batch_op:
        batch_op.drop_column('termino_ocorrencias')
        batch_op.drop_column('termino_data')
        batch_op.drop_column('termino_tipo')
        batch_op.drop_column('modo_mensal')
        batch_op.drop_column('dias_semana')
        batch_op.drop_column('unidade_recorrencia')
        batch_op.drop_column('intervalo_recorrencia')
