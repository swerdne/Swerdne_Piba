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

    # Dias da semana que esse ministerio costuma ter culto/evento (CSV de
    # inteiros 0=segunda..6=domingo, mesma convencao de
    # app/plantao/models.py::TurnoPlantao.dias_semana). So um lembrete
    # visual pra quem configura a recorrencia de um Rodizio (ver
    # dias_culto_efetivos) -- nunca restringe quais dias podem ser
    # escolhidos la, so destaca os habituais.
    dias_culto = db.Column(db.String(20), nullable=True)

    comunidade = db.relationship(
        "Comunidade", backref=db.backref("ministerios", cascade="all, delete-orphan")
    )

    @property
    def dias_culto_efetivos(self):
        """Lista de inteiros (0=segunda..6=domingo) -- vazia se nunca
        configurado (diferente de TurnoPlantao.dias_semana_efetivos, aqui
        nao ha uma data-ancora pra cair de volta, entao "nao configurado"
        e so "nenhum destaque", nao um erro)."""
        if not self.dias_culto:
            return []
        return sorted(int(d) for d in self.dias_culto.split(","))

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


class Crianca(db.Model):
    """Uma crianca cadastrada no check-in de um Ministerio (pensado pro
    ministerio Kids, mas nao restrito -- qualquer Ministerio pode ter sua
    propria lista). Cadastrada uma vez pelo lider/voluntario no balcao de
    check-in; reaproveitada em cada culto (ver CheckInCrianca abaixo)."""

    __tablename__ = "ministerio_criancas"

    id = db.Column(db.Integer, primary_key=True)
    ministerio_id = db.Column(db.Integer, db.ForeignKey("ministerios.id"), nullable=False)
    nome = db.Column(db.String(120), nullable=False)
    data_nascimento = db.Column(db.Date, nullable=True)
    responsavel_nome = db.Column(db.String(120), nullable=False)
    responsavel_telefone = db.Column(db.String(30), nullable=True)
    observacoes = db.Column(db.Text, nullable=True)
    criada_em = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    ministerio = db.relationship(
        "Ministerio", backref=db.backref("criancas", cascade="all, delete-orphan")
    )

    @property
    def iniciais(self):
        partes = self.nome.split()
        letras = "".join(p[0] for p in partes[:2])
        return letras.upper() or "?"

    def __repr__(self):
        return f"<Crianca {self.nome} do ministerio {self.ministerio_id}>"


class CheckInCrianca(db.Model):
    """Uma entrada+saida de uma Crianca no balcao de check-in, num dia
    especifico. `codigo_seguranca` e gerado na entrada e entregue ao
    responsavel (escrito/tirado foto) -- na saida, o voluntario confere
    esse mesmo codigo antes de liberar a crianca (ver
    ministerio.routes.fazer_checkout)."""

    __tablename__ = "ministerio_checkins"

    id = db.Column(db.Integer, primary_key=True)
    crianca_id = db.Column(db.Integer, db.ForeignKey("ministerio_criancas.id"), nullable=False)
    data = db.Column(db.Date, nullable=False)
    hora_entrada = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    hora_saida = db.Column(db.DateTime, nullable=True)
    codigo_seguranca = db.Column(db.String(6), nullable=False)
    registrado_por_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    retirado_por_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    crianca = db.relationship(
        "Crianca", backref=db.backref("checkins", cascade="all, delete-orphan", order_by="CheckInCrianca.hora_entrada.desc()")
    )
    registrado_por = db.relationship("User", foreign_keys=[registrado_por_id])
    retirado_por = db.relationship("User", foreign_keys=[retirado_por_id])

    @property
    def esta_presente(self):
        return self.hora_saida is None

    def __repr__(self):
        return f"<CheckInCrianca {self.crianca_id} em {self.data}>"


def criar_ministerio(comunidade_id, nome, descricao=None, imagem=None):
    ministerio = Ministerio(comunidade_id=comunidade_id, nome=nome, descricao=descricao, imagem=imagem)
    db.session.add(ministerio)
    db.session.commit()
    return ministerio
