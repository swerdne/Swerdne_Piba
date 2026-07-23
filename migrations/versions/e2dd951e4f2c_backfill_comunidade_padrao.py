"""backfill: cria uma comunidade padrao por usuario e vincula escalas/membros

Cria uma Comunidade "Minha Comunidade" para cada usuario_id que ja possui
escalas hoje, e preenche comunidade_id em `escalas` e `escala_membros` a
partir dela -- necessario porque o proximo passo torna essa coluna
obrigatoria (NOT NULL) e o app deixa de ter qualquer nocao de usuario_id
direto no dono de uma escala.

Revision ID: e2dd951e4f2c
Revises: 8f5d4ed3d775
Create Date: 2026-07-22 09:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e2dd951e4f2c'
down_revision = '8f5d4ed3d775'
branch_labels = None
depends_on = None

_CRIADA_EM_MARCADOR = '2026-01-01 00:00:00'


def upgrade():
    conn = op.get_bind()

    usuarios = conn.execute(sa.text("SELECT DISTINCT usuario_id FROM escalas")).fetchall()
    comunidade_por_usuario = {}
    for (usuario_id,) in usuarios:
        resultado = conn.execute(
            sa.text(
                "INSERT INTO comunidades (nome, descricao, imagem, usuario_id, criada_em) "
                "VALUES ('Minha Comunidade', NULL, NULL, :usuario_id, :criada_em)"
            ),
            {"usuario_id": usuario_id, "criada_em": _CRIADA_EM_MARCADOR},
        )
        comunidade_por_usuario[usuario_id] = resultado.lastrowid

    for usuario_id, comunidade_id in comunidade_por_usuario.items():
        conn.execute(
            sa.text("UPDATE escalas SET comunidade_id = :comunidade_id WHERE usuario_id = :usuario_id"),
            {"comunidade_id": comunidade_id, "usuario_id": usuario_id},
        )

    # Um Membro nao tem usuario_id direto -- deriva-se via a funcao/escala
    # em que ele ja esta escalado hoje.
    linhas = conn.execute(sa.text(
        "SELECT DISTINCT ef.membro_id, e.usuario_id FROM escala_funcoes ef "
        "JOIN escalas e ON e.id = ef.escala_id WHERE ef.membro_id IS NOT NULL"
    )).fetchall()
    for membro_id, usuario_id in linhas:
        comunidade_id = comunidade_por_usuario.get(usuario_id)
        if comunidade_id:
            conn.execute(
                sa.text("UPDATE escala_membros SET comunidade_id = :comunidade_id WHERE id = :membro_id"),
                {"comunidade_id": comunidade_id, "membro_id": membro_id},
            )


def downgrade():
    conn = op.get_bind()
    conn.execute(sa.text("UPDATE escalas SET comunidade_id = NULL"))
    conn.execute(sa.text("UPDATE escala_membros SET comunidade_id = NULL"))
    conn.execute(
        sa.text("DELETE FROM comunidades WHERE nome = 'Minha Comunidade' AND criada_em = :criada_em"),
        {"criada_em": _CRIADA_EM_MARCADOR},
    )
