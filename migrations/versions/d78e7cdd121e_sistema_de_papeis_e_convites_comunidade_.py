"""sistema de papeis e convites (comunidade, ministerio, super admin)

Revision ID: d78e7cdd121e
Revises: 85857d42d827
Create Date: 2026-08-10 13:31:46.724285

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd78e7cdd121e'
down_revision = '85857d42d827'
branch_labels = None
depends_on = None


def upgrade():
    # NOTA: o autogenerate tambem detectou "add foreign key" em
    # escala_membros.comunidade_id e escalas.{ministerio_id,plantao_turno_id}
    # -- mesmo schema drift pre-existente ja documentado em c7e3674500d1,
    # b7e64bc63936 e 85857d42d827 (colunas adicionadas via ALTER TABLE ADD
    # COLUMN em migrations antigas, nunca ganharam FK real no schema).
    # Removido daqui de proposito, mesmo motivo de sempre: nao misturar uma
    # mudanca de risco alheia numa migration que devia ser so sobre papeis/convites.
    op.add_column('users', sa.Column('eh_super_admin', sa.Boolean(), server_default=sa.text('false'), nullable=False))

    op.create_table('usuario_comunidade',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('usuario_id', sa.Integer(), nullable=False),
    sa.Column('comunidade_id', sa.Integer(), nullable=False),
    sa.Column('papel', sa.String(length=10), nullable=False),
    sa.Column('criado_em', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['comunidade_id'], ['comunidades.id'], ),
    sa.ForeignKeyConstraint(['usuario_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('usuario_id', 'comunidade_id', name='uq_usuario_comunidade')
    )
    op.create_table('usuario_ministerio',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('usuario_id', sa.Integer(), nullable=False),
    sa.Column('ministerio_id', sa.Integer(), nullable=False),
    sa.Column('papel', sa.String(length=10), nullable=False),
    sa.Column('criado_em', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['ministerio_id'], ['ministerios.id'], ),
    sa.ForeignKeyConstraint(['usuario_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('usuario_id', 'ministerio_id', name='uq_usuario_ministerio')
    )
    op.create_table('convites',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('escopo_tipo', sa.String(length=15), nullable=False),
    sa.Column('escopo_id', sa.Integer(), nullable=False),
    sa.Column('papel', sa.String(length=10), nullable=False),
    sa.Column('email', sa.String(length=120), nullable=False),
    sa.Column('convidado_por_id', sa.Integer(), nullable=False),
    sa.Column('token', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=10), server_default='pendente', nullable=False),
    sa.Column('criado_em', sa.DateTime(), nullable=False),
    sa.Column('respondido_em', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['convidado_por_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('token')
    )

    # Backfill: o criador original de cada Comunidade ja existente (usuario_id,
    # ate agora a UNICA fonte de autorizacao) ganha uma linha papel=admin --
    # dai em diante toda checagem passa a consultar usuario_comunidade (ver
    # comunidade.routes._eh_admin_da_comunidade), que tambem mantem
    # Comunidade.usuario_id como fallback pra qualquer ambiente onde, por
    # algum motivo, esse backfill nao tenha rodado.
    op.execute(
        "INSERT INTO usuario_comunidade (usuario_id, comunidade_id, papel, criado_em) "
        "SELECT usuario_id, id, 'admin', criada_em FROM comunidades"
    )


def downgrade():
    op.drop_table('convites')
    op.drop_table('usuario_ministerio')
    op.drop_table('usuario_comunidade')
    op.drop_column('users', 'eh_super_admin')
