"""adiciona departamento e nome_funcao a turnos_plantao

TurnoPlantao passa a gerar suas proprias Escala (ver
app/plantao/sincronizacao.py) -- precisa de um departamento (herda a cor no
calendario do ministerio, mesmo esquema de Escala.departamento) e de um nome
para a unica Funcao criada em cada ocorrencia gerada.

Nao ha dado correlato no banco de onde derivar um departamento por turno
existente (diferente do padrao de 3 migrations usado para ministerio_id, que
tinha como calcular o valor certo por linha via JOIN) -- turnos pre-existentes
recebem 'Louvor'/'Responsavel' como placeholder e devem ser revisados
manualmente na tela de edicao do turno.

Revision ID: 889df47f5510
Revises: 20ea5b90cf00
Create Date: 2026-07-23 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '889df47f5510'
down_revision = '20ea5b90cf00'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE turnos_plantao ADD COLUMN departamento VARCHAR(40) NOT NULL DEFAULT 'Louvor'")
    op.execute("ALTER TABLE turnos_plantao ADD COLUMN nome_funcao VARCHAR(80) NOT NULL DEFAULT 'Responsavel'")


def downgrade():
    with op.batch_alter_table('turnos_plantao', schema=None) as batch_op:
        batch_op.drop_column('nome_funcao')
        batch_op.drop_column('departamento')
