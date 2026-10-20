"""Quem e escalado num ministerio entra nos Papeis dele como "membro"
automaticamente -- sem o fluxo manual de adicionar por e-mail. Papel e por
CONTA (UsuarioMinisterio), entao so vale pra pessoa do diretorio cujo
e-mail bate com uma conta.

Nao inclui: quem ja tem papel no ministerio (nunca rebaixa lider), admin
da comunidade (ja manda em todo ministerio), quem ligou "exigir minha
aprovacao" pra entrar em grupos (User.exige_aprovacao_grupos -- continua
vendo a propria escala normalmente) e convidado pontual (Funcao.eh_convidado,
quem chama nem passa por aqui). Sair das escalas NAO remove dos Papeis:
remover continua sendo decisao manual na tela de Papeis.
"""
from datetime import timedelta

from app.auth.models import User


def _usuario_do_membro(membro):
    if membro is None or not membro.email:
        return None
    return User.objects(email__iexact=membro.email.strip()).first()


def incluir_usuario_no_ministerio(usuario, ministerio):
    """Cria o papel "membro" (e "membro" na comunidade, se nao tinha nada
    la -- igual a adicao direta). Devolve True se incluiu."""
    from app.comunidade.models import UsuarioComunidade
    from app.comunidade.routes import _eh_admin_da_comunidade
    from app.ministerio.models import UsuarioMinisterio

    if usuario is None or usuario.exige_aprovacao_grupos:
        return False
    if UsuarioMinisterio.objects(usuario_id=usuario.id, ministerio_id=ministerio.id).first():
        return False
    if _eh_admin_da_comunidade(ministerio.comunidade, usuario):
        return False
    UsuarioMinisterio(usuario_id=usuario.id, ministerio_id=ministerio.id, papel="membro").save()
    if not UsuarioComunidade.objects(usuario_id=usuario.id, comunidade_id=ministerio.comunidade_id).first():
        UsuarioComunidade(usuario_id=usuario.id, comunidade_id=ministerio.comunidade_id, papel="membro").save()
    return True


def incluir_escalado_no_ministerio(membro, ministerio):
    """Chamado ao escalar alguem (escala.adicionar_membro, aprovar_troca) e
    ao por alguem na fila de um rodizio. Nunca derruba a acao principal."""
    try:
        return incluir_usuario_no_ministerio(_usuario_do_membro(membro), ministerio)
    except Exception:  # noqa: BLE001 -- incluir nos Papeis e um extra
        from flask import current_app

        current_app.logger.exception("Inclusao automatica nos Papeis falhou")
        return False


def sincronizar_escalados_antigos(ministerio, hoje):
    """Uma vez por ministerio (Ministerio.papeis_escalados_sincronizados):
    inclui quem ja estava escalado (escalas dos ultimos 60 dias em diante)
    antes de existir a inclusao automatica. Devolve quantos entraram."""
    from app.escala.models import Escala, Funcao, Membro

    if ministerio.papeis_escalados_sincronizados:
        return 0
    escalas = Escala.objects(ministerio_id=ministerio.id, data__gte=hoje - timedelta(days=60)).only("id")
    membro_ids = set(Funcao.objects(escala_id__in=[e.id for e in escalas], membro_id__ne=None,
                                    eh_convidado__ne=True).distinct("membro_id"))
    emails = {(m.email or "").strip() for m in Membro.objects(id__in=list(membro_ids)).only("email") if m.email}
    candidatos = emails | {e.lower() for e in emails}
    incluidos = 0
    for usuario in User.objects(email__in=list(candidatos)):
        if incluir_usuario_no_ministerio(usuario, ministerio):
            incluidos += 1
    ministerio.papeis_escalados_sincronizados = True
    ministerio.save()
    return incluidos
