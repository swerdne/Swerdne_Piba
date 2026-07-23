"""Model (M do MVC): Ministerio.

Camada organizacional dentro de uma Comunidade: agrupa escalas relacionadas
(ex: "Ministerio de Louvor", "Equipe de Midia"). Puramente organizacional --
nao tem ligacao obrigatoria com o campo `departamento` de cada Escala.
"""
from datetime import datetime, timezone

from app.extensions import db


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


def criar_ministerio(comunidade_id, nome, descricao=None, imagem=None):
    ministerio = Ministerio(comunidade_id=comunidade_id, nome=nome, descricao=descricao, imagem=imagem)
    db.session.add(ministerio)
    db.session.commit()
    return ministerio
