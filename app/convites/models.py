"""Model (M do MVC): Convite.

Um Convite concede um PAPEL (ver app/comunidade/models.py::PAPEIS_COMUNIDADE,
app/ministerio/models.py::PAPEIS_MINISTERIO) num escopo especifico (uma
Comunidade ou um Ministerio) a um e-mail -- nao exige que a pessoa ja tenha
conta na plataforma (ver ver_convite em routes.py: sem conta, a tela manda
criar uma antes de aceitar). So gera a linha de papel de verdade
(UsuarioComunidade/UsuarioMinisterio) quando ACEITO -- enquanto pendente, a
pessoa nao tem nenhum acesso extra, nao entra no rodizio, nao recebe
notificacao de escala (so o e-mail do proprio convite).

NAO cobre o papel "convidado" (vinculo pontual a 1 Escala/Funcao) -- esse
mecanismo e outro, ja existente e instantaneo (sem convite/aceite), ver
Funcao.eh_convidado em app/escala/models.py e app/escala/CLAUDE.md.
"""
import secrets
from datetime import datetime, timezone

from app.extensions import db

ESCOPOS = ("comunidade", "ministerio")
STATUS_PENDENTE = "pendente"
STATUS_ACEITO = "aceito"
STATUS_RECUSADO = "recusado"


def _gerar_token():
    return secrets.token_urlsafe(32)


class Convite(db.Model):
    __tablename__ = "convites"

    id = db.Column(db.Integer, primary_key=True)
    # "comunidade" ou "ministerio" -- ver ESCOPOS. escopo_id aponta pra
    # Comunidade.id ou Ministerio.id conforme escopo_tipo (nao da pra usar
    # uma FK real de banco pra 2 tabelas diferentes; a resolucao e feita em
    # Python via as properties comunidade/ministerio abaixo).
    escopo_tipo = db.Column(db.String(15), nullable=False)
    escopo_id = db.Column(db.Integer, nullable=False)
    papel = db.Column(db.String(10), nullable=False)

    email = db.Column(db.String(120), nullable=False)
    convidado_por_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    token = db.Column(db.String(64), unique=True, nullable=False, default=_gerar_token)
    status = db.Column(db.String(10), nullable=False, default=STATUS_PENDENTE, server_default=STATUS_PENDENTE)

    criado_em = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    respondido_em = db.Column(db.DateTime, nullable=True)

    convidado_por = db.relationship("User")

    @property
    def comunidade(self):
        """So valido quando escopo_tipo == 'comunidade' -- ver escopo_nome/escopo_obj."""
        from app.comunidade.models import Comunidade
        return db.session.get(Comunidade, self.escopo_id)

    @property
    def ministerio(self):
        """So valido quando escopo_tipo == 'ministerio' -- ver escopo_nome/escopo_obj."""
        from app.ministerio.models import Ministerio
        return db.session.get(Ministerio, self.escopo_id)

    @property
    def escopo_obj(self):
        return self.comunidade if self.escopo_tipo == "comunidade" else self.ministerio

    @property
    def escopo_nome(self):
        obj = self.escopo_obj
        return obj.nome if obj else "(removido)"

    @property
    def usuario_ja_cadastrado(self):
        """Se ja existe uma conta (User) com o e-mail do convite -- usado na
        tela de aceite pra decidir se manda logar ou criar conta."""
        from app.auth.models import User
        return User.query.filter(db.func.lower(User.email) == self.email.lower()).first()

    def __repr__(self):
        return f"<Convite {self.email} papel={self.papel} {self.escopo_tipo}={self.escopo_id} status={self.status}>"


def criar_ou_reenviar_convite(escopo_tipo, escopo_id, papel, email, convidado_por_id):
    """Find-or-create: reaproveita um convite PENDENTE ja existente pro mesmo
    escopo+e-mail (atualiza papel/quem convidou/token, pra reenviar em vez de
    acumular convites duplicados) -- so cria um novo se nao houver nenhum
    pendente."""
    email = email.strip().lower()
    convite = Convite.query.filter_by(
        escopo_tipo=escopo_tipo, escopo_id=escopo_id, email=email, status=STATUS_PENDENTE
    ).first()

    if convite is None:
        convite = Convite(escopo_tipo=escopo_tipo, escopo_id=escopo_id, email=email)
        db.session.add(convite)

    convite.papel = papel
    convite.convidado_por_id = convidado_por_id
    convite.token = _gerar_token()
    db.session.commit()
    return convite
