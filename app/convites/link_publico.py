"""Link de acesso direto (Comunidade ou Ministerio) -- metodo de entrada
ALTERNATIVO ao convite por e-mail (app/convites/models.py::Convite):

- Convite por e-mail: pra uma pessoa especifica, com papel especifico
  (admin/lider/membro), exige aceite.
- Link de acesso direto: qualquer um com o link entra como "membro" comum
  (nunca admin/lider -- o link nao serve pra promover ninguem); abrir o link
  ja conta como aceite. O token mora no proprio escopo
  (Comunidade/Ministerio.token_convite_publico); gerar outro invalida o
  anterior.

Quem ainda nao tem conta: a visita anonima guarda a entrada pendente na
sessao, e login/cadastro/Google concluem a entrada sozinhos (ver
auth.routes._redirecionar_apos_login), sem pedir mais um clique.
"""
from datetime import datetime, timedelta, timezone

from flask import flash, session, url_for

from app.notificacoes import Notificacao

SESSAO_ENTRADA_PENDENTE = "entrada_por_link"

# Opcoes de quem gera o link (Fase 3): validade em dias (0 = sem prazo) e
# limite de entradas (0 = sem limite).
VALIDADES = {1: "1 dia", 7: "7 dias", 30: "30 dias", 0: "Sem prazo"}
LIMITES = {0: "Sem limite", 5: "5 pessoas", 10: "10 pessoas", 25: "25 pessoas", 50: "50 pessoas"}
PAPEIS_MINISTERIO = {"membro": "membro", "lider": "líder"}


class LinkIndisponivel(Exception):
    """O link expirou ou chegou no limite de entradas."""


def configurar_link(escopo, dias, limite, papel="membro"):
    """Gera token novo (o antigo para) com as regras escolhidas."""
    escopo.gerar_novo_link_convite()
    escopo.convite_expira_em = datetime.now(timezone.utc) + timedelta(days=dias) if dias else None
    escopo.convite_limite_usos = limite or None
    escopo.convite_usos = 0
    if hasattr(escopo, "convite_papel"):
        escopo.convite_papel = papel if papel in PAPEIS_MINISTERIO else "membro"


def motivo_link_indisponivel(escopo):
    expira = escopo.convite_expira_em
    if expira is not None:
        if expira.tzinfo is None:
            expira = expira.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > expira:
            return "Este link de convite expirou. Peça um novo a quem te enviou."
    if escopo.convite_limite_usos and (escopo.convite_usos or 0) >= escopo.convite_limite_usos:
        return "Este link de convite já foi usado pelo número máximo de pessoas. Peça um novo a quem te enviou."
    return None


def _reservar_uso(escopo):
    """Conta 1 entrada (atomico: duas pessoas ao mesmo tempo nao passam do limite)."""
    motivo = motivo_link_indisponivel(escopo)
    if motivo:
        raise LinkIndisponivel(motivo)
    filtro = {"id": escopo.id}
    if escopo.convite_limite_usos:
        filtro["convite_usos__lt"] = escopo.convite_limite_usos
    if not type(escopo).objects(**filtro).update(inc__convite_usos=1):
        raise LinkIndisponivel("Este link de convite já foi usado pelo número máximo de pessoas. "
                               "Peça um novo a quem te enviou.")


def descricao_link(escopo):
    """"Vale até 05/12 · 3 de 10 entradas · entra como líder"."""
    partes = []
    if escopo.convite_expira_em:
        expira = escopo.convite_expira_em
        if expira.tzinfo is None:
            expira = expira.replace(tzinfo=timezone.utc)
        partes.append(f"vale até {(expira - timedelta(hours=3)):%d/%m %H:%M}")
    else:
        partes.append("sem prazo")
    usos = escopo.convite_usos or 0
    if escopo.convite_limite_usos:
        partes.append(f"{usos} de {escopo.convite_limite_usos} entradas")
    else:
        partes.append(f"{usos} entrada{'s' if usos != 1 else ''}")
    papel = getattr(escopo, "convite_papel", None) or "membro"
    partes.append(f"entra como {PAPEIS_MINISTERIO.get(papel, 'membro')}")
    motivo = motivo_link_indisponivel(escopo)
    texto = " · ".join(partes)
    return f"{texto} · {'expirado' if motivo and 'expirou' in motivo else 'esgotado'}" if motivo else texto


def _nome(usuario):
    return usuario.name or usuario.username or usuario.email


def eh_navegacao_direta(request):
    """True quando a pessoa ABRIU o link no navegador (navegacao de pagina
    inteira) -- dai a entrada pode ser automatica, sem botao de confirmar.
    Fica de fora o que nao e intencao da pessoa: pre-carregamento do
    navegador (prefetch/prerender) e carregamentos embutidos (um
    <img src="..."> ou <iframe> em outro site). Preview de link do
    WhatsApp/Telegram nem chega aqui logado (o robo nao tem a sessao).
    Navegador sem os cabecalhos Sec-Fetch-* cai na tela com o botao."""
    if request.headers.get("Sec-Fetch-Mode") != "navigate":
        return False
    if request.headers.get("Sec-Fetch-Dest") != "document":
        return False
    finalidade = (request.headers.get("Sec-Purpose") or request.headers.get("Purpose") or "").lower()
    return "prefetch" not in finalidade and "prerender" not in finalidade


def guardar_entrada_pendente(tipo, token, url_do_link):
    session[SESSAO_ENTRADA_PENDENTE] = {"tipo": tipo, "token": token}
    # Fallback do fluxo antigo (volta pra tela do link se algo falhar).
    session["proximo_apos_login"] = url_do_link


def _notificar(usuarios, quem_entrou, titulo, mensagem):
    for usuario in usuarios:
        if usuario.id == quem_entrou.id:
            continue  # nunca notifica quem entrou sobre a propria entrada
        Notificacao(usuario_id=usuario.id, titulo=titulo[:120], mensagem=mensagem, tipo="novo_membro").save()


def entrar_na_comunidade(usuario, comunidade):
    """Da o papel "membro" (se ainda nao tem nenhum) e avisa os admins.
    Devolve (destino, mensagem). Nunca rebaixa quem ja e admin."""
    from app.comunidade.models import UsuarioComunidade
    from app.comunidade.routes import _admins_da_comunidade, _eh_admin_da_comunidade

    destino_membro = url_for("comunidade.escalados", comunidade_id=comunidade.id)
    if _eh_admin_da_comunidade(comunidade, usuario):
        return url_for("comunidade.detalhe", comunidade_id=comunidade.id), f'Você já faz parte de "{comunidade.nome}".'
    if UsuarioComunidade.objects(usuario_id=usuario.id, comunidade_id=comunidade.id).first():
        return destino_membro, f'Você já faz parte de "{comunidade.nome}".'

    _reservar_uso(comunidade)  # levanta LinkIndisponivel se expirou/esgotou
    UsuarioComunidade(usuario_id=usuario.id, comunidade_id=comunidade.id, papel="membro").save()
    nome = _nome(usuario)
    _notificar(
        _admins_da_comunidade(comunidade), usuario,
        f'{nome} entrou em "{comunidade.nome}"',
        f"{nome} entrou na comunidade pelo link de acesso direto, como membro. "
        "Confirme a entrada no diretório em Pessoas.",
    )
    return destino_membro, f'Você entrou em "{comunidade.nome}"!'


def entrar_no_ministerio(usuario, ministerio):
    """Da o papel "membro" no Ministerio (e na Comunidade dele, se a pessoa
    ainda nao tem papel nenhum la -- sem isso ela nao enxergaria o resto da
    igreja) e avisa os lideres do ministerio (inclui os admins da
    comunidade). Devolve (destino, mensagem). Nunca rebaixa lider/admin."""
    from app.comunidade.models import UsuarioComunidade
    from app.ministerio.models import UsuarioMinisterio
    from app.ministerio.routes import _eh_lider_do_ministerio, _lideres_do_ministerio

    destino = url_for("ministerio.detalhe", ministerio_id=ministerio.id)
    if _eh_lider_do_ministerio(ministerio, usuario) or UsuarioMinisterio.objects(
        usuario_id=usuario.id, ministerio_id=ministerio.id
    ).first():
        return destino, f'Você já faz parte de "{ministerio.nome}".'

    _reservar_uso(ministerio)  # levanta LinkIndisponivel se expirou/esgotou
    papel = ministerio.convite_papel if ministerio.convite_papel in PAPEIS_MINISTERIO else "membro"
    UsuarioMinisterio(usuario_id=usuario.id, ministerio_id=ministerio.id, papel=papel).save()
    if not UsuarioComunidade.objects(usuario_id=usuario.id, comunidade_id=ministerio.comunidade_id).first():
        UsuarioComunidade(usuario_id=usuario.id, comunidade_id=ministerio.comunidade_id, papel="membro").save()

    nome = _nome(usuario)
    _notificar(
        _lideres_do_ministerio(ministerio), usuario,
        f'{nome} entrou em "{ministerio.nome}"',
        f"{nome} entrou no ministério pelo link de convite, como {PAPEIS_MINISTERIO[papel]}.",
    )
    return destino, f'Você entrou em "{ministerio.nome}" como {PAPEIS_MINISTERIO[papel]}!'


def concluir_entrada_pendente(usuario):
    """Chamado logo apos login/cadastro/Google: se a pessoa chegou por um
    link de acesso direto, conclui a entrada. Devolve (destino, mensagem) ou
    None. O token e conferido de novo aqui -- se o link foi revogado nesse
    meio tempo, a entrada nao acontece."""
    from app.comunidade.models import Comunidade
    from app.ministerio.models import Ministerio

    pendente = session.pop(SESSAO_ENTRADA_PENDENTE, None)
    if not pendente or not pendente.get("token"):
        return None
    try:
        if pendente.get("tipo") == "comunidade":
            comunidade = Comunidade.objects(token_convite_publico=pendente["token"]).first()
            if comunidade:
                return entrar_na_comunidade(usuario, comunidade)
        elif pendente.get("tipo") == "ministerio":
            ministerio = Ministerio.objects(token_convite_publico=pendente["token"]).first()
            if ministerio:
                return entrar_no_ministerio(usuario, ministerio)
    except LinkIndisponivel as erro:
        session.pop("proximo_apos_login", None)
        flash(str(erro), "danger")
        return None
    # Link revogado entre a visita e o login: nao volta pra ele (daria 404).
    session.pop("proximo_apos_login", None)
    flash("Esse link de acesso foi desativado. Peça um novo a quem te enviou.", "danger")
    return None
