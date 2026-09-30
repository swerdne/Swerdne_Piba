"""Notificacoes internas do site (o sino do Dashboard).

Fica fora dos blueprints porque e usado tanto por quem PRODUZ notificacoes
(hoje, so a Escala Rapida) quanto por quem EXIBE (o Dashboard, no main).
"""
from datetime import datetime, timezone

from app.extensions import db


class Notificacao(db.Model):
    __tablename__ = "notificacoes"

    id = db.Column(db.Integer, primary_key=True)
    # Sem ForeignKey("users.id") -- User agora vive no MongoDB, ver
    # `usuario` abaixo (property, no lugar do antigo db.relationship).
    usuario_id = db.Column(db.Integer, nullable=False)
    titulo = db.Column(db.String(120), nullable=False)
    mensagem = db.Column(db.Text, nullable=False)
    lida = db.Column(db.Boolean, nullable=False, default=False)
    criada_em = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    # escala_id: pra que serve a notificacao ser agrupavel por Escala no sino
    # do Dashboard (ver main.routes.dashboard). Nullable porque notificacoes
    # antigas (antes desse campo existir) nao tem como saber a que escala se
    # referiam sem parsear o texto -- ficam sem grupo, tipo "geral".
    # tipo: categoria pra icone/agrupamento na UI -- "escalado", "alteracao",
    # "confirmado", "presente", "troca_solicitada", "troca_aprovada",
    # "troca_recusada". Nullable pelo mesmo motivo (retrocompatibilidade).
    # Sem ForeignKey("escalas.id", ondelete="SET NULL") -- Escala agora vive
    # no MongoDB, sem SET NULL automatico do banco: se a Escala referenciada
    # for apagada, escala_id fica com um id que nao existe mais, mas
    # `escala` abaixo ja devolve None nesse caso (mesmo resultado pra quem
    # le, so o campo cru em si nao fica limpo).
    escala_id = db.Column(db.Integer, nullable=True)
    tipo = db.Column(db.String(30), nullable=True)

    @property
    def usuario(self):
        from app.auth.models import User
        return User.objects(id=self.usuario_id).first()

    @property
    def escala(self):
        if not self.escala_id:
            return None
        from app.escala.models import Escala
        return Escala.objects(id=self.escala_id).first()

    def __repr__(self):
        return f"<Notificacao {self.titulo!r} para usuario {self.usuario_id}>"
