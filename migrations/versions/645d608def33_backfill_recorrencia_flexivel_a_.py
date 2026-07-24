"""backfill recorrencia flexivel a partir da recorrencia antiga

Migracao de DADO (nao so schema): o valor certo de unidade_recorrencia/
dias_semana/modo_mensal depende da `recorrencia` antiga E de `data_inicio`
de cada turno, entao precisa ser calculado linha a linha -- nao da pra usar
um DEFAULT constante (diferente de outras colunas deste modulo que nao
tinham dado correlato pra derivar). SQL puro via sa.text(), sem importar
models da aplicacao, seguindo o padrao ja usado em 75e1cee93835.

Mapeamento: "diaria" -> intervalo=1, unidade="dia". "semanal" -> intervalo=1,
unidade="semana", dias_semana=[weekday de data_inicio]. "mensal" ->
intervalo=1, unidade="mes", modo_mensal="dia_fixo". Todos: termino_tipo="nunca".

Revision ID: 645d608def33
Revises: 6e02be038f76
Create Date: 2026-07-23 16:05:00.000000

"""
from datetime import date

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '645d608def33'
down_revision = '6e02be038f76'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    linhas = conn.execute(sa.text("SELECT id, recorrencia, data_inicio FROM turnos_plantao")).fetchall()

    for turno_id, recorrencia, data_inicio_str in linhas:
        data_inicio = date.fromisoformat(data_inicio_str)

        if recorrencia == "diaria":
            unidade, dias_semana, modo_mensal = "dia", None, None
        elif recorrencia == "semanal":
            unidade, dias_semana, modo_mensal = "semana", str(data_inicio.weekday()), None
        elif recorrencia == "mensal":
            unidade, dias_semana, modo_mensal = "mes", None, "dia_fixo"
        else:
            # recorrencia desconhecida (nao deveria acontecer) -- cai em diaria
            # pra nao deixar a linha com unidade_recorrencia NULL na proxima migration.
            unidade, dias_semana, modo_mensal = "dia", None, None

        conn.execute(
            sa.text(
                "UPDATE turnos_plantao SET intervalo_recorrencia=1, unidade_recorrencia=:unidade, "
                "dias_semana=:dias_semana, modo_mensal=:modo_mensal, termino_tipo='nunca' "
                "WHERE id=:id"
            ),
            {"unidade": unidade, "dias_semana": dias_semana, "modo_mensal": modo_mensal, "id": turno_id},
        )


def downgrade():
    conn = op.get_bind()
    conn.execute(sa.text(
        "UPDATE turnos_plantao SET intervalo_recorrencia=NULL, unidade_recorrencia=NULL, "
        "dias_semana=NULL, modo_mensal=NULL, termino_tipo=NULL"
    ))
