"""adiciona eh_convidado a escala_funcoes

Marca uma atribuicao de Funcao feita a partir da busca de uma conta (User) ja
existente na plataforma (ver escala.routes.adicionar_convidado), em vez de
escolhida do diretorio fixo da comunidade -- ver app/escala/models.py::Funcao.

Usa op.add_column com sa.Column(server_default=sa.false()) em vez de SQL cru
(op.execute) de proposito: o compilador de DDL do SQLAlchemy ja gera o
literal booleano certo por dialeto sozinho, evitando o problema ja conhecido
nesta base de "BOOLEAN ... DEFAULT 0" quebrar no Postgres (ver
889df47f5510/90778b537d1f e app/plantao/CLAUDE.md).

Revision ID: 2d3548d68fe6
Revises: 9309a0b3893f
Create Date: 2026-07-28 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2d3548d68fe6'
down_revision = '9309a0b3893f'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'escala_funcoes',
        sa.Column('eh_convidado', sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade():
    with op.batch_alter_table('escala_funcoes', schema=None) as batch_op:
        batch_op.drop_column('eh_convidado')
