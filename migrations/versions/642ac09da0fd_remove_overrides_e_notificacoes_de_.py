"""remove overrides e notificacoes proprias de plantao

overrides_plantao e plantao_notificacoes_enviadas ficam obsoletas: o rodizio
agora materializa suas ocorrencias em Escala/Funcao reais (ver
app/plantao/sincronizacao.py) -- a excecao pontual de ausencia vira
Escala.plantao_fixado direto na ocorrencia real, e a notificacao 24h/16h
passa a usar o mesmo controle (Escala.notificado_24h_em/16h_em) e o mesmo
agendador (app/escala/agendador.py) da Escala Rapida, sem scheduler proprio.

Projeto ainda nao tem dados de producao (dev local, sem git) -- overrides ja
registrados em dev.db, se houver, sao perdidos por esta migration; nao ha
migracao de dados porque nao ha nada a preservar.

Revision ID: 642ac09da0fd
Revises: 7818b8bc1ef4
Create Date: 2026-07-23 10:15:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '642ac09da0fd'
down_revision = '7818b8bc1ef4'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_table('plantao_notificacoes_enviadas')
    op.drop_table('overrides_plantao')


def downgrade():
    op.create_table('overrides_plantao',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('turno_id', sa.Integer(), nullable=False),
    sa.Column('periodo', sa.Integer(), nullable=False),
    sa.Column('membro_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['membro_id'], ['escala_membros.id'], ),
    sa.ForeignKeyConstraint(['turno_id'], ['turnos_plantao.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('turno_id', 'periodo', name='uq_override_turno_periodo')
    )
    op.create_table('plantao_notificacoes_enviadas',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('turno_id', sa.Integer(), nullable=False),
    sa.Column('periodo', sa.Integer(), nullable=False),
    sa.Column('janela', sa.String(length=3), nullable=False),
    sa.Column('enviado_em', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['turno_id'], ['turnos_plantao.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('turno_id', 'periodo', 'janela', name='uq_notificacao_turno_periodo_janela')
    )
