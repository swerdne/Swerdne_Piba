"""Model (M do MVC): Ministerio.

Camada organizacional dentro de uma Comunidade: agrupa escalas relacionadas
(ex: "Ministerio de Louvor", "Equipe de Midia"). Puramente organizacional --
nao tem ligacao obrigatoria com o campo `departamento` de cada Escala.
"""
from datetime import datetime, timezone

from app.extensions import db

PAPEIS_MINISTERIO = ("lider", "membro")


class Ministerio(db.Model):
    __tablename__ = "ministerios"

    id = db.Column(db.Integer, primary_key=True)
    comunidade_id = db.Column(db.Integer, db.ForeignKey("comunidades.id"), nullable=False)
    nome = db.Column(db.String(120), nullable=False)
    descricao = db.Column(db.Text, nullable=True)
    imagem = db.Column(db.String(500), nullable=True)
    criada_em = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    comunidade = db.relationship(
        "Comunidade", backref=db.backref("ministerios", cascade="all, delete-orphan")
    )

    def __repr__(self):
        return f"<Ministerio {self.nome} da comunidade {self.comunidade_id}>"


class UsuarioMinisterio(db.Model):
    """Papel de um usuario (conta com login) dentro de um Ministerio --
    'lider' gerencia escalas/turnos/membros daquele ministerio; 'membro'
    participa (visualiza as escalas em que esta inserido). Nao existe papel
    'convidado' aqui de proposito -- convidado e sempre escopado a 1 unica
    Escala/Funcao, mecanismo separado e ja existente (Funcao.eh_convidado,
    ver app/escala/CLAUDE.md), nao um papel de ministerio.

    Concedido sempre via convite aceito (app/convites) -- nunca criado
    automaticamente. Quem administra a Comunidade (dono original ou
    UsuarioComunidade papel=admin) tem as mesmas permissoes de um lider em
    QUALQUER ministerio dela, mesmo sem uma linha aqui -- ver
    ministerio.routes._eh_lider_do_ministerio."""

    __tablename__ = "usuario_ministerio"

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    ministerio_id = db.Column(db.Integer, db.ForeignKey("ministerios.id"), nullable=False)
    papel = db.Column(db.String(10), nullable=False)
    criado_em = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    usuario = db.relationship("User")
    ministerio = db.relationship(
        "Ministerio", backref=db.backref("papeis_usuarios", cascade="all, delete-orphan")
    )

    __table_args__ = (
        db.UniqueConstraint("usuario_id", "ministerio_id", name="uq_usuario_ministerio"),
    )

    def __repr__(self):
        return f"<UsuarioMinisterio {self.usuario_id} papel={self.papel} do ministerio {self.ministerio_id}>"


def criar_ministerio(comunidade_id, nome, descricao=None, imagem=None):
    ministerio = Ministerio(comunidade_id=comunidade_id, nome=nome, descricao=descricao, imagem=imagem)
    db.session.add(ministerio)
    db.session.commit()
    return ministerio
