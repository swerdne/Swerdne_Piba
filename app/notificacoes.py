"""Notificacoes internas do site (o sino do Dashboard).

Fica fora dos blueprints porque e usado tanto por quem PRODUZ notificacoes
(hoje, so a Escala Rapida) quanto por quem EXIBE (o Dashboard, no main).
"""
from datetime import datetime, timezone

import mongoengine
from app.db_utils import SequentialIdDocument


class Notificacao(SequentialIdDocument):
    meta = {"collection": "notificacoes", "indexes": ["usuario_id"]}
    _nome_sequencia = "notificacoes"

    usuario_id = mongoengine.IntField(required=True)
    titulo = mongoengine.StringField(required=True, max_length=120)
    mensagem = mongoengine.StringField(required=True)
    lida = mongoengine.BooleanField(required=True, default=False)
    criada_em = mongoengine.DateTimeField(default=lambda: datetime.now(timezone.utc))

    # escala_id: pra que serve a notificacao ser agrupavel por Escala no sino
    # do Dashboard (ver main.routes.dashboard). None pra notificacoes
    # antigas (antes desse campo existir) que nao tem como saber a que
    # escala se referiam sem parsear o texto -- ficam sem grupo, tipo "geral".
    # tipo: categoria pra icone/agrupamento na UI -- "escalado", "alteracao",
    # "confirmado", "presente", "troca_solicitada", "troca_aprovada",
    # "troca_recusada". None pelo mesmo motivo (retrocompatibilidade).
    # Sem cascade/reverse_delete_rule -- se a Escala referenciada for
    # apagada, escala_id fica com um id que nao existe mais, mas `escala`
    # abaixo ja devolve None nesse caso (mesmo resultado pra quem le, so o
    # campo cru em si nao fica limpo).
    escala_id = mongoengine.IntField()
    tipo = mongoengine.StringField(max_length=30)

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
