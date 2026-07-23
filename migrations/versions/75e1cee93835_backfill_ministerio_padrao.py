"""backfill: cria um ministerio por (comunidade, departamento) e vincula escalas

Cada combinacao distinta de comunidade+departamento ja usada em escalas
existentes vira um Ministerio ("Ministerio de {departamento}") -- preserva o
agrupamento que ja existia implicitamente por departamento antes do conceito
de Ministerio existir.

Revision ID: 75e1cee93835
Revises: 17431ac0c7b2
Create Date: 2026-07-22 13:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '75e1cee93835'
down_revision = '17431ac0c7b2'
branch_labels = None
depends_on = None

_CRIADA_EM_MARCADOR = '2026-01-01 00:00:00'


def upgrade():
    conn = op.get_bind()

    pares = conn.execute(sa.text(
        "SELECT DISTINCT comunidade_id, departamento FROM escalas"
    )).fetchall()

    ministerio_por_par = {}
    for comunidade_id, departamento in pares:
        resultado = conn.execute(
            sa.text(
                "INSERT INTO ministerios (nome, descricao, imagem, comunidade_id, criada_em) "
                "VALUES (:nome, NULL, NULL, :comunidade_id, :criada_em)"
            ),
            {
                "nome": f"Ministerio de {departamento}",
                "comunidade_id": comunidade_id,
                "criada_em": _CRIADA_EM_MARCADOR,
            },
        )
        ministerio_por_par[(comunidade_id, departamento)] = resultado.lastrowid

    for (comunidade_id, departamento), ministerio_id in ministerio_por_par.items():
        conn.execute(
            sa.text(
                "UPDATE escalas SET ministerio_id = :ministerio_id "
                "WHERE comunidade_id = :comunidade_id AND departamento = :departamento"
            ),
            {"ministerio_id": ministerio_id, "comunidade_id": comunidade_id, "departamento": departamento},
        )


def downgrade():
    conn = op.get_bind()
    conn.execute(sa.text("UPDATE escalas SET ministerio_id = NULL"))
    conn.execute(sa.text("DELETE FROM ministerios WHERE criada_em = :criada_em"), {"criada_em": _CRIADA_EM_MARCADOR})
