"""Model (M do MVC): Comunidade.

Camada organizacional anterior a Escala Rapida: toda escala e todo membro do
diretorio pertencem a uma comunidade especifica (ex: uma igreja/ministerio).
Comunidades sao independentes entre si.
"""
from datetime import datetime, timezone

from app.extensions import db

PAPEIS_COMUNIDADE = ("admin", "membro")


class Comunidade(db.Model):
    __tablename__ = "comunidades"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False)
    descricao = db.Column(db.Text, nullable=True)
    imagem = db.Column(db.String(500), nullable=True)
    # Criador original -- mantido como metadado historico. Nao e mais a UNICA
    # fonte de autorizacao (ver UsuarioComunidade/comunidade.routes._eh_admin_da_comunidade):
    # o criador ganha automaticamente uma linha papel=admin em UsuarioComunidade
    # ao criar a comunidade (criar_comunidade abaixo), entao toda checagem
    # passa a consultar essa tabela, nao mais usuario_id direto.
    usuario_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    criada_em = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<Comunidade {self.nome} do usuario {self.usuario_id}>"


class UsuarioComunidade(db.Model):
    """Papel de um usuario (conta com login) dentro de uma Comunidade --
    'admin' pode gerenciar ministerios/membros/permissoes; 'membro' tem
    visibilidade de leitura (mesmo nivel de hoje via Membro vinculado por
    e-mail, ver comunidade.routes._comunidade_visivel_ou_404).

    Concedido SEMPRE via convite aceito (app/convites), exceto a linha do
    criador original, gerada automaticamente por criar_comunidade. Nao
    confundir com Membro (app/escala/models.py) -- Membro e o diretorio de
    pessoas escalaveis, nao precisa de conta nem de papel; os dois so se
    cruzam por coincidencia de e-mail, quando faz sentido."""

    __tablename__ = "usuario_comunidade"

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    comunidade_id = db.Column(db.Integer, db.ForeignKey("comunidades.id"), nullable=False)
    papel = db.Column(db.String(10), nullable=False)
    criado_em = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    usuario = db.relationship("User")
    comunidade = db.relationship(
        "Comunidade", backref=db.backref("papeis_usuarios", cascade="all, delete-orphan")
    )

    __table_args__ = (
        db.UniqueConstraint("usuario_id", "comunidade_id", name="uq_usuario_comunidade"),
    )

    def __repr__(self):
        return f"<UsuarioComunidade {self.usuario_id} papel={self.papel} da comunidade {self.comunidade_id}>"


def criar_comunidade(usuario_id, nome, descricao=None, imagem=None):
    comunidade = Comunidade(usuario_id=usuario_id, nome=nome, descricao=descricao, imagem=imagem)
    db.session.add(comunidade)
    db.session.flush()  # garante comunidade.id antes de criar o papel

    db.session.add(UsuarioComunidade(usuario_id=usuario_id, comunidade_id=comunidade.id, papel="admin"))
    db.session.commit()
    return comunidade
