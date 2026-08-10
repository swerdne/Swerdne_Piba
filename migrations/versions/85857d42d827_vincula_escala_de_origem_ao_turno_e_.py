"""vincula escala de origem ao turno e adiciona cor por escala

Revision ID: 85857d42d827
Revises: b7e64bc63936
Create Date: 2026-08-09 20:12:56.315687

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '85857d42d827'
down_revision = 'b7e64bc63936'
branch_labels = None
depends_on = None


def upgrade():
    # NOTA: o autogenerate tambem detectou "add foreign key" em
    # escala_membros.comunidade_id e escalas.{ministerio_id,plantao_turno_id}
    # -- mesmo schema drift pre-existente ja documentado em c7e3674500d1 e
    # b7e64bc63936 (colunas adicionadas via ALTER TABLE ADD COLUMN em
    # migrations antigas, nunca ganharam FK real no schema). Removido daqui
    # de proposito, mesmo motivo: nao misturar uma mudanca de risco alheia
    # numa migration que devia ser so sobre os 2 campos novos abaixo.
    op.add_column('escalas', sa.Column('turno_plantao_origem_id', sa.Integer(), nullable=True))
    op.add_column('escalas', sa.Column('cor_selecionada', sa.String(length=20), nullable=True))
    op.create_foreign_key(
        'fk_escalas_turno_plantao_origem_id', 'escalas', 'turnos_plantao',
        ['turno_plantao_origem_id'], ['id'],
    )


def downgrade():
    op.drop_constraint('fk_escalas_turno_plantao_origem_id', 'escalas', type_='foreignkey')
    op.drop_column('escalas', 'cor_selecionada')
    op.drop_column('escalas', 'turno_plantao_origem_id')
