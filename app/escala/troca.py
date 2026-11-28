"""Troca de escala entre membros: A pede, B (o colega sugerido) aceita, o
lider aprova -- com aviso no sino em cada passo e historico no RegistroTroca.

1. A marca "Troca solicitada" na propria funcao e sugere B (opcional).
   Com B sugerido e com conta no app: Funcao.troca_aceite = "pendente" e B
   recebe no sino o link para a tela de responder (escala.responder_troca).
   Sem sugestao, ou B sem conta: o lider decide direto, como antes.
2. B aceita ou recusa: A e os lideres sao avisados.
3. O lider aprova (escolhendo quem assume -- ja vem B) ou recusa. O lider
   pode decidir antes da resposta de B (ex.: B nao respondeu a tempo); a
   tela mostra em que pe o aceite esta.
Cada passo vira uma linha em RegistroTroca.etapas (data e hora de Brasilia).
"""
from datetime import datetime, timedelta, timezone

from flask import url_for

SITUACOES = {
    "pedida": "Aguardando o líder",
    "aguardando_colega": "Aguardando o colega aceitar",
    "aceita_colega": "Colega aceitou, aguardando o líder",
    "recusada_colega": "Colega recusou, aguardando o líder",
    "aprovada": "Aprovada",
    "recusada": "Recusada pelo líder",
    "cancelada": "Cancelada por quem pediu",
}


def _carimbo():
    return (datetime.now(timezone.utc) - timedelta(hours=3)).strftime("%d/%m %H:%M")


def registro_da_funcao(funcao):
    from app.escala.models import RegistroTroca

    if not funcao.troca_registro_id:
        return None
    return RegistroTroca.objects(id=funcao.troca_registro_id).first()


def anotar(registro, texto, situacao=None):
    if registro is None:
        return
    registro.etapas = list(registro.etapas or []) + [f"{_carimbo()} · {texto}"[:300]]
    if situacao:
        registro.situacao = situacao
    registro.save()


def conta_do_membro(membro):
    from app.auth.models import User

    if membro is None or not membro.email:
        return None
    return User.objects(email__iexact=membro.email.strip()).first()


def iniciar_pedido(funcao):
    """Chamado quando o proprio escalado pede a troca (escala.atualizar_status)."""
    from app.escala.models import Membro, RegistroTroca
    from app.notificacoes import Notificacao

    escala = funcao.escala
    pessoa = funcao.membro
    sugerido = Membro.objects(id=funcao.troca_sugestao_membro_id).first() if funcao.troca_sugestao_membro_id else None
    registro = RegistroTroca(
        ministerio_id=escala.ministerio_id, escala_id=escala.id, membro_id=funcao.membro_id,
        funcao_nome=funcao.nome, substituto_id=sugerido.id if sugerido else None,
    )
    texto = f"{pessoa.nome} pediu troca"
    if sugerido:
        texto += f" e sugeriu {sugerido.nome}"
    if funcao.troca_motivo:
        texto += f' (motivo: "{funcao.troca_motivo[:120]}")'
    registro.etapas = [f"{_carimbo()} · {texto}"[:300]]

    conta_sugerida = conta_do_membro(sugerido)
    if conta_sugerida is not None:
        funcao.troca_aceite = "pendente"
        registro.situacao = "aguardando_colega"
    else:
        funcao.troca_aceite = None
        registro.situacao = "pedida"
        if sugerido:
            registro.etapas.append(f"{_carimbo()} · {sugerido.nome} não tem conta no app: o líder decide direto")
    registro.save()
    funcao.troca_registro_id = registro.id
    funcao.save()

    if conta_sugerida is not None:
        data = escala.data.strftime("%d/%m") if escala.data else "data a definir"
        Notificacao(
            usuario_id=conta_sugerida.id,
            titulo=f"{pessoa.nome} pediu para você assumir {funcao.nome_exibido}"[:120],
            mensagem=f"{escala.nome} ({data}). Toque para aceitar ou recusar; depois o líder aprova.",
            escala_id=escala.id, tipo="troca_solicitada",
            link=url_for("escala.responder_troca", funcao_id=funcao.id),
        ).save()
    return registro


def responder(funcao, aceitou):
    """B (o colega sugerido) aceita ou recusa."""
    from app.escala.routes import _notificar_lideres_do_ministerio
    from app.notificacoes import Notificacao

    escala = funcao.escala
    sugerido = funcao.troca_sugestao_membro
    funcao.troca_aceite = "aceita" if aceitou else "recusada"
    funcao.save()
    verbo = "aceitou" if aceitou else "recusou"
    anotar(registro_da_funcao(funcao), f"{sugerido.nome} {verbo} assumir",
           "aceita_colega" if aceitou else "recusada_colega")

    titulo = f"{sugerido.nome} {verbo} assumir {funcao.nome_exibido}"[:120]
    mensagem = f"Troca pedida por {funcao.membro.nome} em {escala.nome}. " + (
        "Falta o líder aprovar." if aceitou else "O líder decide quem assume.")
    conta_a = conta_do_membro(funcao.membro)
    if conta_a is not None:
        Notificacao(usuario_id=conta_a.id, titulo=titulo, mensagem=mensagem, escala_id=escala.id,
                    tipo="troca_aprovada" if aceitou else "troca_recusada").save()
    _notificar_lideres_do_ministerio(escala, titulo, mensagem, tipo="troca_solicitada", funcao=funcao)


def concluir(funcao, aprovada, quem_assume=None):
    """Lider aprovou (com quem assume) ou recusou: fecha o historico."""
    registro = registro_da_funcao(funcao)
    if aprovada:
        anotar(registro, f"Líder aprovou: {quem_assume.nome} assume", "aprovada")
        if registro is not None and quem_assume is not None:
            registro.substituto_id = quem_assume.id
            registro.save()
    else:
        anotar(registro, "Líder recusou a troca", "recusada")
    funcao.troca_aceite = None
    funcao.troca_registro_id = None


def cancelar(funcao):
    """Quem pediu mudou o status de volta (desistiu da troca)."""
    anotar(registro_da_funcao(funcao), f"{funcao.membro.nome} desistiu da troca", "cancelada")
    funcao.troca_aceite = None
    funcao.troca_registro_id = None
