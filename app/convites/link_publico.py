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
from flask import flash, session, url_for

from app.notificacoes import Notificacao

SESSAO_ENTRADA_PENDENTE = "entrada_por_link"


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
        return url_for("comunidade.detalhe", comunidade_id=comunidade.id), f'Voce ja faz parte de "{comunidade.nome}".'
    if UsuarioComunidade.objects(usuario_id=usuario.id, comunidade_id=comunidade.id).first():
        return destino_membro, f'Voce ja faz parte de "{comunidade.nome}".'

    UsuarioComunidade(usuario_id=usuario.id, comunidade_id=comunidade.id, papel="membro").save()
    nome = _nome(usuario)
    _notificar(
        _admins_da_comunidade(comunidade), usuario,
        f'{nome} entrou em "{comunidade.nome}"',
        f"{nome} entrou na comunidade pelo link de acesso direto, como membro.",
    )
    return destino_membro, f'Voce entrou em "{comunidade.nome}"!'


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
        return destino, f'Voce ja faz parte de "{ministerio.nome}".'

    UsuarioMinisterio(usuario_id=usuario.id, ministerio_id=ministerio.id, papel="membro").save()
    if not UsuarioComunidade.objects(usuario_id=usuario.id, comunidade_id=ministerio.comunidade_id).first():
        UsuarioComunidade(usuario_id=usuario.id, comunidade_id=ministerio.comunidade_id, papel="membro").save()

    nome = _nome(usuario)
    _notificar(
        _lideres_do_ministerio(ministerio), usuario,
        f'{nome} entrou em "{ministerio.nome}"',
        f"{nome} entrou no ministerio pelo link de acesso direto, como membro.",
    )
    return destino, f'Voce entrou em "{ministerio.nome}"!'


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
    if pendente.get("tipo") == "comunidade":
        comunidade = Comunidade.objects(token_convite_publico=pendente["token"]).first()
        if comunidade:
            return entrar_na_comunidade(usuario, comunidade)
    elif pendente.get("tipo") == "ministerio":
        ministerio = Ministerio.objects(token_convite_publico=pendente["token"]).first()
        if ministerio:
            return entrar_no_ministerio(usuario, ministerio)
    # Link revogado entre a visita e o login: nao volta pra ele (daria 404).
    session.pop("proximo_apos_login", None)
    flash("Esse link de acesso foi desativado. Peca um novo a quem te enviou.", "danger")
    return None
