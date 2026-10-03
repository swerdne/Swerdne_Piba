"""Adicao de pessoas a uma Comunidade/Ministerio pela tela de Papeis --
direta (padrao) ou por convite, conforme a preferencia de privacidade de
quem esta sendo adicionado (User.exige_aprovacao_grupos).

- Conta existente, sem a preferencia ligada: entra NA HORA com o papel
  escolhido, e recebe um aviso (sino + e-mail) dizendo quem adicionou e
  como sair/ativar a aprovacao.
- Sem conta ainda, ou com a preferencia ligada: segue o Convite por e-mail
  de sempre (app/convites/models.py), e so entra se aceitar.
- Ja faz parte com o MESMO papel: nada a fazer. Com papel DIFERENTE: vira
  convite tambem -- mudar o papel de alguem (inclusive rebaixar) sem o
  aceite da pessoa nao e "adicionar", entao nao entra no atalho direto.

Quem pode conceder qual papel continua sendo checado pela rota que chama
(comunidade.routes.papeis / ministerio.routes.papeis), antes de chegar aqui.
"""
import threading

from flask import current_app, url_for

from app.auth.models import User
from app.notificacoes import Notificacao

MODO_ADICIONAR = "adicionar"
MODO_CONVITE = "convite"
MODO_JA_FAZ_PARTE = "ja_faz_parte"


def _papel_atual(escopo_tipo, escopo, usuario):
    """Papel que `usuario` ja tem nesse escopo, ou None."""
    if escopo_tipo == "comunidade":
        from app.comunidade.models import UsuarioComunidade

        if escopo.usuario_id == usuario.id:
            return "admin"  # dono original, mesmo sem linha propria
        linha = UsuarioComunidade.objects(usuario_id=usuario.id, comunidade_id=escopo.id).first()
    else:
        from app.ministerio.models import UsuarioMinisterio

        linha = UsuarioMinisterio.objects(usuario_id=usuario.id, ministerio_id=escopo.id).first()
    return linha.papel if linha else None


def decidir_modo(escopo_tipo, escopo, email, papel):
    """Devolve (modo, usuario, motivo) -- usado tanto pelo POST quanto pela
    pre-visualizacao do formulario (convites.routes.verificar_adicao), pra
    tela mostrar ANTES de enviar exatamente o que vai acontecer. `motivo`
    so e preenchido no MODO_CONVITE: "sem_conta", "exige_aprovacao" ou
    "muda_papel"."""
    usuario = User.objects(email__iexact=(email or "").strip()).first()
    if usuario is None:
        return MODO_CONVITE, None, "sem_conta"

    papel_atual = _papel_atual(escopo_tipo, escopo, usuario)
    if papel_atual == papel:
        return MODO_JA_FAZ_PARTE, usuario, None
    if papel_atual is not None:
        return MODO_CONVITE, usuario, "muda_papel"
    if usuario.exige_aprovacao_grupos:
        return MODO_CONVITE, usuario, "exige_aprovacao"
    return MODO_ADICIONAR, usuario, None


def adicionar_direto(escopo_tipo, escopo, usuario, papel, adicionado_por):
    """Cria a linha de papel (so chamada quando decidir_modo deu
    MODO_ADICIONAR, ou seja, a pessoa ainda nao tinha papel nenhum aqui),
    descarta convite pendente que tenha ficado pra tras e avisa a pessoa."""
    from app.comunidade.models import UsuarioComunidade
    from app.convites.models import Convite, STATUS_PENDENTE

    if escopo_tipo == "comunidade":
        UsuarioComunidade(usuario_id=usuario.id, comunidade_id=escopo.id, papel=papel).save()
        # Tela de gestao (detalhe) so abre pra admin -- membro cai em
        # "escalados", mesmo destino de link_publico.entrar_na_comunidade.
        rota = "comunidade.detalhe" if papel == "admin" else "comunidade.escalados"
        destino = url_for(rota, comunidade_id=escopo.id, _external=True)
    else:
        from app.ministerio.models import UsuarioMinisterio

        UsuarioMinisterio(usuario_id=usuario.id, ministerio_id=escopo.id, papel=papel).save()
        # Mesmo motivo de link_publico.entrar_no_ministerio: sem um papel na
        # Comunidade, a pessoa nao enxergaria o resto da igreja.
        if not UsuarioComunidade.objects(usuario_id=usuario.id, comunidade_id=escopo.comunidade_id).first():
            UsuarioComunidade(usuario_id=usuario.id, comunidade_id=escopo.comunidade_id, papel="membro").save()
        destino = url_for("ministerio.detalhe", ministerio_id=escopo.id, _external=True)

    # Um convite pendente pro mesmo escopo+e-mail perdeu o sentido (a pessoa
    # ja entrou) -- sem isso ele continuaria listado como pendente.
    Convite.objects(
        escopo_tipo=escopo_tipo, escopo_id=escopo.id, email=usuario.email.lower(), status=STATUS_PENDENTE
    ).delete()

    _avisar_pessoa_adicionada(escopo, usuario, papel, adicionado_por, destino)


def _nome(usuario):
    return usuario.name or usuario.username or usuario.email


def _avisar_pessoa_adicionada(escopo, usuario, papel, adicionado_por, destino):
    """Sino + e-mail pra pessoa nao ser pega de surpresa por ter entrado
    num grupo sem ter aceitado nada."""
    titulo = f'Voce foi adicionado(a) a "{escopo.nome}"'
    mensagem = (
        f'{_nome(adicionado_por)} adicionou voce a "{escopo.nome}" como {papel}. '
        "Se preferir aprovar antes de ser adicionado(a) a grupos, ative essa opcao em Configuracoes."
    )
    Notificacao(usuario_id=usuario.id, titulo=titulo[:120], mensagem=mensagem, tipo="adicionado_grupo").save()

    corpo = f"{mensagem}\n\nAcesse:\n{destino}"
    _enviar_email_em_segundo_plano(usuario.email, titulo, corpo)


def _enviar_email_em_segundo_plano(destinatario, assunto, corpo):
    """O aviso e so informativo (a pessoa ja entrou) -- nao vale segurar a
    resposta de quem esta adicionando ate a API de e-mail responder (ate
    ~12s de timeout, ver app/emailing.py). Falha so e ignorada, mesmo
    padrao do resto do projeto."""
    from app.emailing import enviar_email, EmailNaoEnviadoError

    app_obj = current_app._get_current_object()

    def _enviar():
        with app_obj.app_context():
            try:
                enviar_email(destinatario, assunto, corpo)
            except EmailNaoEnviadoError:
                pass

    threading.Thread(target=_enviar, daemon=True).start()


def adicionar_ou_convidar(escopo_tipo, escopo, papel, email, adicionado_por):
    """Ponto de entrada das rotas de Papeis. Devolve (mensagem, categoria)
    pro flash -- a mensagem deixa explicito se a pessoa JA ENTROU ou se so
    recebeu um convite, pra quem adicionou nao achar que ela ja esta no
    grupo quando nao esta."""
    from app.convites.models import criar_ou_reenviar_convite
    from app.convites.routes import _enviar_email_de_convite

    modo, usuario, motivo = decidir_modo(escopo_tipo, escopo, email, papel)

    if modo == MODO_JA_FAZ_PARTE:
        return f'{_nome(usuario)} ja faz parte de "{escopo.nome}" como {papel}.', "success"

    if modo == MODO_ADICIONAR:
        adicionar_direto(escopo_tipo, escopo, usuario, papel, adicionado_por)
        return f'{_nome(usuario)} foi adicionado(a) a "{escopo.nome}" como {papel}.', "success"

    convite = criar_ou_reenviar_convite(
        escopo_tipo=escopo_tipo, escopo_id=escopo.id, papel=papel, email=email,
        convidado_por_id=adicionado_por.id,
    )
    _enviar_email_de_convite(convite)
    explicacao = {
        "sem_conta": "ainda nao tem conta -- entra depois de se cadastrar e aceitar",
        "exige_aprovacao": "exige aprovacao pra entrar em grupos -- so entra depois de aceitar",
        "muda_papel": "ja faz parte com outro papel -- a mudanca so vale depois de aceitar",
    }[motivo]
    return f"Convite enviado para {convite.email} (a pessoa {explicacao}).", "success"
