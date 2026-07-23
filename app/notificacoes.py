"""Notificacoes internas do site (o sino do Dashboard).

Fica fora dos blueprints porque e usado tanto por quem PRODUZ notificacoes
(hoje, so a Escala Rapida) quanto por quem EXIBE (o Dashboard, no main).
"""
from datetime import datetime, timezone

from app.extensions import db


class Notificacao(db.Model):
    __tablename__ = "notificacoes"

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    titulo = db.Column(db.String(120), nullable=False)
    mensagem = db.Column(db.Text, nullable=False)
    lida = db.Column(db.Boolean, nullable=False, default=False)
    criada_em = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    usuario = db.relationship(
        "User", backref=db.backref("notificacoes", cascade="all, delete-orphan")
    )

    def __repr__(self):
        return f"<Notificacao {self.titulo!r} para usuario {self.usuario_id}>"
