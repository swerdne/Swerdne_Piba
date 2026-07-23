"""Models de dominio do modulo main.

Exemplo de uma entidade. Adapte conforme a regra de negocio do seu projeto.
"""
from app.extensions import db


class Item(db.Model):
    __tablename__ = "items"

    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(120), nullable=False)
    descricao = db.Column(db.Text)

    def __repr__(self):
        return f"<Item {self.titulo}>"
