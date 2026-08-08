"""substitui fila individual por equipes no rodizio

Revision ID: b7e64bc63936
Revises: 2d3548d68fe6
Create Date: 2026-08-05 21:23:55.264959

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b7e64bc63936'
down_revision = '2d3548d68fe6'
branch_labels = None
depends_on = None


def upgrade():
    # NOTA: o autogenerate tambem detectou "add foreign key" em
    # escala_membros.comunidade_id e escalas.{plantao_turno_id,ministerio_id}
    # -- mesmo schema drift pre-existente ja documentado em c7e3674500d1 (colunas
    # adicionadas via ALTER TABLE ADD COLUMN em migrations antigas, nunca
    # ganharam FK real no schema). Removido daqui de proposito, mesmo motivo:
    # nao misturar uma mudanca de risco alheia numa migration que devia ser
    # so sobre a fila do rodizio.
    op.create_table('turno_plantao_equipes',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('turno_id', sa.Integer(), nullable=False),
    sa.Column('posicao', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['turno_id'], ['turnos_plantao.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('turno_plantao_equipe_membros',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('equipe_turno_id', sa.Integer(), nullable=False),
    sa.Column('membro_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['equipe_turno_id'], ['turno_plantao_equipes.id'], ),
    sa.ForeignKeyConstraint(['membro_id'], ['escala_membros.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

    # Migra os dados: cada posicao da fila antiga (turno_id, posicao, membro_id)
    # vira uma equipe de 1 integrante -- rotacao individual continua funcionando
    # identico, so que agora e o caso particular de "equipe com 1 pessoa" (ver
    # app/plantao/models.py::EquipeTurno). (turno_id, posicao) identifica cada
    # linha antiga sem ambiguidade (o app sempre manteve posicoes contiguas e
    # unicas por turno), entao o join abaixo re-liga cada nova equipe ao
    # membro_id original sem precisar rastrear ids gerados um a um.
    op.execute(
        "INSERT INTO turno_plantao_equipes (turno_id, posicao) "
        "SELECT turno_id, posicao FROM turno_plantao_membros"
    )
    op.execute(
        "INSERT INTO turno_plantao_equipe_membros (equipe_turno_id, membro_id) "
        "SELECT e.id, m.membro_id "
        "FROM turno_plantao_membros m "
        "JOIN turno_plantao_equipes e ON e.turno_id = m.turno_id AND e.posicao = m.posicao"
    )

    op.drop_table('turno_plantao_membros')


def downgrade():
    op.create_table('turno_plantao_membros',
    sa.Column('id', sa.INTEGER(), autoincrement=True, nullable=False),
    sa.Column('turno_id', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.Column('membro_id', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.Column('posicao', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.ForeignKeyConstraint(['membro_id'], ['escala_membros.id'], name=op.f('turno_plantao_membros_membro_id_fkey')),
    sa.ForeignKeyConstraint(['turno_id'], ['turnos_plantao.id'], name=op.f('turno_plantao_membros_turno_id_fkey')),
    sa.PrimaryKeyConstraint('id', name=op.f('turno_plantao_membros_pkey'))
    )

    # Best-effort: so reconstroi de volta o formato 1-membro-por-posicao pras
    # equipes que tinham exatamente 1 integrante (o formato antigo nao tem
    # como representar uma equipe com mais de 1 pessoa na mesma posicao --
    # equipes com 2+ integrantes perdem membros extras nesse downgrade).
    op.execute(
        "INSERT INTO turno_plantao_membros (turno_id, membro_id, posicao) "
        "SELECT e.turno_id, em.membro_id, e.posicao "
        "FROM turno_plantao_equipes e "
        "JOIN turno_plantao_equipe_membros em ON em.equipe_turno_id = e.id "
        "WHERE (SELECT COUNT(*) FROM turno_plantao_equipe_membros em2 WHERE em2.equipe_turno_id = e.id) = 1"
    )

    op.drop_table('turno_plantao_equipe_membros')
    op.drop_table('turno_plantao_equipes')
