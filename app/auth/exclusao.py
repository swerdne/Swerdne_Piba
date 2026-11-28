"""Excluir a propria conta (LGPD), com 15 dias para desistir.

1. Pedido (Perfil > Configuracoes > "Excluir conta", digitando EXCLUIR):
   a conta fica desativada na hora (User.exclusao_pedida_em), a pessoa sai
   das escalas futuras (lideres avisados no sino) e recebe um e-mail com o
   link para cancelar (User.token_cancelar_exclusao).
2. Ate 15 dias: entrar de novo leva a tela "Conta marcada para exclusao",
   com o botao de cancelar; o link do e-mail faz o mesmo sem precisar entrar.
3. Depois de 15 dias (agendador, 1x por dia): papeis, notificacoes,
   presencas de culto e convites sao apagados; o cadastro no diretorio e
   apagado, ou vira "Pessoa removida" (sem e-mail, telefone e foto) quando
   aparece em escala passada -- o historico da comunidade continua contando.
   Por fim a conta (User) e apagada.

Bloqueio: quem e o UNICO admin de uma comunidade precisa promover outra
pessoa (ou excluir a comunidade) antes -- senao ela fica sem ninguem que a
administre. Unico lider de ministerio so recebe o aviso: o admin da
comunidade continua gerenciando o ministerio.
"""
import logging
import secrets
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

PRAZO_DIAS = 15
NOME_ANONIMO = "Pessoa removida"


def _agora():
    return datetime.now(timezone.utc)


def _utc(momento):
    return momento if momento is None or momento.tzinfo else momento.replace(tzinfo=timezone.utc)


def data_da_exclusao(usuario):
    if not usuario.exclusao_pedida_em:
        return None
    return _utc(usuario.exclusao_pedida_em) + timedelta(days=PRAZO_DIAS)


def comunidades_sem_outro_admin(usuario):
    """Comunidades em que a conta e a unica administradora."""
    from app.comunidade.models import Comunidade, UsuarioComunidade

    ids = {u.comunidade_id for u in UsuarioComunidade.objects(usuario_id=usuario.id, papel="admin").only("comunidade_id")}
    ids |= {c.id for c in Comunidade.objects(usuario_id=usuario.id).only("id")}
    sozinha = []
    for comunidade in Comunidade.objects(id__in=list(ids)).order_by("nome"):
        outros = UsuarioComunidade.objects(comunidade_id=comunidade.id, papel="admin", usuario_id__ne=usuario.id).count()
        dono_e_outro = comunidade.usuario_id != usuario.id and _conta_ativa(comunidade.usuario_id)
        if not outros and not dono_e_outro:
            sozinha.append(comunidade)
    return sozinha


def _conta_ativa(usuario_id):
    from app.auth.models import User

    dono = User.objects(id=usuario_id).only("id", "exclusao_pedida_em").first()
    return bool(dono and not dono.exclusao_pedida_em)


def ministerios_sem_outro_lider(usuario):
    """Ministerios em que a conta e a unica lider (so aviso)."""
    from app.ministerio.models import Ministerio, UsuarioMinisterio

    ids = [u.ministerio_id for u in UsuarioMinisterio.objects(usuario_id=usuario.id, papel="lider").only("ministerio_id")]
    sozinha = []
    for ministerio in Ministerio.objects(id__in=ids).order_by("nome"):
        if not UsuarioMinisterio.objects(ministerio_id=ministerio.id, papel="lider", usuario_id__ne=usuario.id).count():
            sozinha.append(ministerio)
    return sozinha


def escalas_futuras(usuario):
    """Funcoes da conta em escalas de hoje em diante (nao canceladas)."""
    from app.escala.models import Escala, Funcao, Membro
    from app.fuso import hoje_brasilia

    ids_membro = [m.id for m in Membro.da_conta((usuario.email or "").lower()).only("id")]
    if not ids_membro:
        return []
    funcoes = list(Funcao.objects(membro_id__in=ids_membro))
    if not funcoes:
        return []
    escalas = {e.id: e for e in Escala.objects(id__in=list({f.escala_id for f in funcoes}), data__gte=hoje_brasilia(),
                                                cancelada__ne=True)}
    return [(f, escalas[f.escala_id]) for f in funcoes if f.escala_id in escalas]


def pedir_exclusao(usuario):
    """Desativa a conta agora e marca a exclusao para daqui a 15 dias.
    Devolve True se o e-mail com o link de cancelar saiu."""
    from app.escala.models import STATUS_PADRAO
    from app.escala.routes import _notificar_lideres_do_ministerio

    nome = usuario.name or usuario.username or usuario.email
    for funcao, escala in escalas_futuras(usuario):
        funcao_nome = funcao.nome_exibido
        funcao.membro_id = None
        funcao.status = STATUS_PADRAO
        funcao.troca_motivo = None
        funcao.troca_sugestao_membro_id = None
        funcao.limpar_checkin()
        funcao.save()
        try:
            _notificar_lideres_do_ministerio(
                escala, f"{nome} saiu da escala ({funcao_nome})",
                f"{nome} pediu para excluir a conta e saiu de {funcao_nome} em {escala.nome}. A função ficou vaga.",
                tipo="alteracao",
            )
        except Exception:
            logger.exception("Aviso de saida da escala falhou (exclusao de conta %s)", usuario.id)

    usuario.exclusao_pedida_em = _agora()
    usuario.token_cancelar_exclusao = secrets.token_urlsafe(32)
    usuario.save()
    return _enviar_email_de_exclusao(usuario)


def _enviar_email_de_exclusao(usuario):
    from flask import url_for

    from app.emailing import EmailNaoEnviadoError, enviar_email

    link = url_for("auth.cancelar_exclusao", token=usuario.token_cancelar_exclusao, _external=True)
    quando = (data_da_exclusao(usuario) - timedelta(hours=3)).strftime("%d/%m/%Y")
    texto = (
        "Recebemos o pedido para excluir sua conta do TyBenson.\n\n"
        f"A conta já está desativada e será apagada em {quando}. Até lá, se mudar de ideia, "
        f"é só abrir este link e cancelar:\n{link}\n\n"
        "Se não foi você quem pediu, abra o link agora e depois troque sua senha."
    )
    try:
        enviar_email(usuario.email, "Exclusão da sua conta TyBenson", texto)
        return True
    except EmailNaoEnviadoError as erro:
        logger.warning("E-mail de exclusao de conta nao saiu (%s): %s", usuario.id, erro)
        return False


def cancelar_exclusao(usuario):
    usuario.exclusao_pedida_em = None
    usuario.token_cancelar_exclusao = None
    usuario.save()


def concluir_exclusao(usuario):
    """Apaga de vez (chamado depois dos 15 dias)."""
    from app.comunidade.models import UsuarioComunidade
    from app.convites.models import Convite
    from app.db_utils import delete_cascade
    from app.escala.models import Funcao, Membro, PresencaCulto
    from app.imagens import remover_imagem
    from app.ministerio.models import UsuarioMinisterio
    from app.notificacoes import Notificacao

    email = (usuario.email or "").lower()
    for membro in list(Membro.da_conta(email)):
        if Funcao.objects(membro_id=membro.id).count():
            remover_imagem(membro.foto)
            membro.nome = NOME_ANONIMO
            membro.email = None
            membro.telefone = None
            membro.foto = None
            membro.save()
        else:
            remover_imagem(membro.foto)
            delete_cascade(membro)

    UsuarioComunidade.objects(usuario_id=usuario.id).delete()
    UsuarioMinisterio.objects(usuario_id=usuario.id).delete()
    Notificacao.objects(usuario_id=usuario.id).delete()
    PresencaCulto.objects(usuario_id=usuario.id).delete()
    Convite.objects(email=email).delete()
    remover_imagem(usuario.foto_perfil)
    usuario.delete()


def concluir_exclusoes_vencidas():
    """Agendador (1x por dia): apaga as contas com o prazo vencido."""
    from app.auth.models import User

    limite = _agora() - timedelta(days=PRAZO_DIAS)
    apagadas = 0
    for usuario in User.objects(exclusao_pedida_em__lte=limite):
        try:
            concluir_exclusao(usuario)
            apagadas += 1
        except Exception:
            logger.exception("Exclusao definitiva da conta %s falhou -- tenta de novo amanha.", usuario.id)
    if apagadas:
        logger.info("Exclusao de contas: %s apagada(s) depois do prazo.", apagadas)
    return apagadas
