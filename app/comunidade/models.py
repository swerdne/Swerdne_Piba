"""Model (M do MVC): Comunidade.

Camada organizacional anterior a Escala Rapida: toda escala e todo membro do
diretorio pertencem a uma comunidade especifica (ex: uma igreja/ministerio).
Comunidades sao independentes entre si.
"""
from datetime import datetime, timezone

from app.extensions import db


class Comunidade(db.Model):
    __tablename__ = "comunidades"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False)
    descricao = db.Column(db.Text, nullable=True)
    imagem = db.Column(db.String(500), nullable=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    criada_em = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<Comunidade {self.nome} do usuario {self.usuario_id}>"


def criar_comunidade(usuario_id, nome, descricao=None, imagem=None):
    comunidade = Comunidade(usuario_id=usuario_id, nome=nome, descricao=descricao, imagem=imagem)
    db.session.add(comunidade)
    db.session.commit()
    return comunidade
