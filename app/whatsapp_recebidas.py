"""Mensagens de WhatsApp RECEBIDAS (webhook da Meta Cloud API).

O envio fica em app/whatsapp.py; aqui fica o caminho de volta:

- `processar_webhook(payload)` -- chamado pela rota main.whatsapp_webhook
  (assinatura ja conferida la) com o JSON que a Meta manda.
- Cada mensagem vira uma `MensagemWhatsapp`, ligada aos Membros cujo telefone
  do diretorio bate com o remetente (`membros_do_telefone`) e as comunidades
  deles -- e o que a caixa de entrada da comunidade mostra
  (comunidade.whatsapp).
- Resposta a aviso de escala: "confirmo"/"sim" confirma, "nao posso"/"nao"
  pede troca (`interpretar_resposta`) em TODAS as funcoes da pessoa na
  PROXIMA escala dela (nao cancelada, de hoje em diante) -- mesmo efeito do
  botao de status do site (lideres avisados no sino, RegistroTroca), e a
  pessoa recebe uma resposta dizendo o que foi feito. Texto que nao e
  confirmacao/recusa nao gera resposta automatica: fica na caixa de entrada
  pra lideranca responder.
"""
import re
import unicodedata
from datetime import datetime, timedelta, timezone

import mongoengine
from flask import current_app

from app.db_utils import SequentialIdDocument

_OFFSET_BRASILIA = timedelta(hours=-3)
# Regra da Meta: texto livre so dentro de 24h da ultima mensagem da pessoa.
JANELA_RESPOSTA = timedelta(hours=24)

RECEBIDA = "recebida"
ENVIADA = "enviada"


class MensagemWhatsapp(SequentialIdDocument):
    meta = {
        "collection": "mensagens_whatsapp",
        "indexes": ["telefone", "comunidade_ids", {"fields": ["wamid"], "unique": True, "sparse": True}],
    }
    _nome_sequencia = "mensagens_whatsapp"

    # Id da mensagem na Meta -- a Meta pode reenviar o mesmo webhook; com ele
    # a mensagem repetida e ignorada (e nao confirma/avisa duas vezes).
    wamid = mongoengine.StringField(max_length=200)
    direcao = mongoengine.StringField(required=True, max_length=10)  # RECEBIDA | ENVIADA
    telefone = mongoengine.StringField(required=True, max_length=30)  # so digitos, com DDI
    nome_perfil = mongoengine.StringField(max_length=120)  # nome do perfil no WhatsApp
    texto = mongoengine.StringField()
    membro_ids = mongoengine.ListField(mongoengine.IntField())
    comunidade_ids = mongoengine.ListField(mongoengine.IntField())
    # "confirmado" / "troca_solicitada" quando a mensagem mudou status de escala.
    acao = mongoengine.StringField(max_length=20)
    escala_id = mongoengine.IntField()
    enviada_por_usuario_id = mongoengine.IntField()  # resposta escrita na caixa de entrada
    lida = mongoengine.BooleanField(default=False)
    criada_em = mongoengine.DateTimeField(default=lambda: datetime.now(timezone.utc))


# --- Telefone ----------------------------------------------------------------

def chave_do_telefone(numero):
    """Chave pra comparar telefones digitados de jeitos diferentes. No Brasil
    = DDD + ultimos 8 digitos: o WhatsApp entrega muitos celulares SEM o 9 da
    frente (5511 8765-4321 pra quem cadastrou 11 98765-4321), e o diretorio
    tem de tudo ("(11) 98765-4321", "+55 11 ...", "11987654321"). Sem DDD nao
    da pra saber de onde e -- None (nao casa com ninguem)."""
    digitos = "".join(c for c in (numero or "") if c.isdigit())
    if digitos.startswith("55") and len(digitos) >= 12:
        digitos = digitos[2:]
    elif (numero or "").strip().startswith("+"):
        return digitos or None  # outro pais: o numero inteiro
    digitos = digitos.lstrip("0")  # 0 de operadora/DDD ("011 ...")
    if len(digitos) < 10:
        return None
    return digitos[:2] + digitos[-8:]


def membros_do_telefone(telefone):
    """Membros (de qualquer comunidade) com esse telefone no diretorio."""
    from app.escala.models import Membro

    chave = chave_do_telefone("+" + telefone.lstrip("+"))
    if chave is None:
        return []
    candidatos = Membro.objects(telefone__nin=[None, ""]).only("id", "nome", "telefone", "comunidade_id")
    return [m for m in candidatos if chave_do_telefone(m.telefone) == chave]


# --- Interpretar a resposta ----------------------------------------------------

def _normalizar(texto):
    sem_acento = unicodedata.normalize("NFD", texto or "").encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", sem_acento).split())


_RECUSA = re.compile(
    r"\b(nao|n)\s+(posso|vou|consigo|irei|poderei|vai dar|da)\b|\brecuso\b|\bpreciso de troca\b|\bpedir troca\b"
)
_CONFIRMA = re.compile(r"\b(confirm\w*|estarei|irei|pode contar|tamo junto|estou dentro)\b")
_SO_RECUSA = {"nao", "n", "2", "nao posso", "troca"}
_SO_CONFIRMA = {"sim", "s", "ok", "okay", "1", "vou", "presente", "certo", "beleza", "blz", "combinado", "fechado"}


def interpretar_resposta(texto):
    """"confirmar", "recusar" ou None. Recusa tem prioridade ("sim, mas nao
    posso" e recusa). Palavras curtas soltas ("ok", "sim", "nao") so valem
    como a mensagem inteira -- no meio de uma frase podem ser outra coisa."""
    bruto = (texto or "").strip()
    if bruto in {"👍", "👍🏻", "👍🏼", "👍🏽", "👍🏾", "👍🏿", "✅"}:
        return "confirmar"
    if bruto in {"👎", "❌"}:
        return "recusar"
    normal = _normalizar(bruto)
    if not normal:
        return None
    if normal in _SO_RECUSA or _RECUSA.search(normal):
        return "recusar"
    if normal in _SO_CONFIRMA or _CONFIRMA.search(normal):
        return "confirmar"
    return None


# --- Aplicar na escala -----------------------------------------------------------

def _hoje_brasilia():
    return (datetime.now(timezone.utc) + _OFFSET_BRASILIA).date()


def _quando(escala):
    if not escala.data:
        return ""
    texto = escala.data.strftime("%d/%m")
    if escala.horario:
        texto += " às " + escala.horario.strftime("%H:%M")
    return texto


def proxima_escala_dos_membros(membros):
    """(escala, funcoes da pessoa nela) da proxima escala nao cancelada de hoje
    em diante -- ou (None, [])."""
    from app.escala.models import TIPO_FUNCAO, Escala, Funcao

    ids = [m.id for m in membros]
    if not ids:
        return None, []
    funcoes = list(Funcao.objects(membro_id__in=ids, tipo=TIPO_FUNCAO))
    if not funcoes:
        return None, []
    escala = (
        Escala.objects(id__in=list({f.escala_id for f in funcoes}), data__gte=_hoje_brasilia(), cancelada__ne=True)
        .order_by("data", "horario")
        .first()
    )
    if escala is None:
        return None, []
    return escala, [f for f in funcoes if f.escala_id == escala.id]


def aplicar_resposta(acao, funcoes, texto):
    """Muda o status das funcoes como o proprio escalado faria pelo site
    (escala.routes.atualizar_status) e avisa os lideres. Devolve as funcoes
    que mudaram de fato. "Presente" nunca volta pra "confirmado"."""
    from app.escala.models import STATUS_LABELS, RegistroTroca
    from app.escala.routes import _notificar_lideres_do_ministerio

    status_novo = "confirmado" if acao == "confirmar" else "troca_solicitada"
    mudaram = []
    for funcao in funcoes:
        if funcao.status == status_novo or funcao.status == "presente":
            continue
        funcao.status = status_novo
        funcao.limpar_checkin()
        if status_novo == "troca_solicitada":
            motivo = (texto or "").strip()
            funcao.troca_motivo = f"Pelo WhatsApp: {motivo[:480]}" if motivo else "Pelo WhatsApp"
            funcao.troca_sugestao_membro_id = None
        else:
            funcao.troca_motivo = None
            funcao.troca_sugestao_membro_id = None
        funcao.save()
        escala = funcao.escala
        if status_novo == "troca_solicitada":
            RegistroTroca(
                ministerio_id=escala.ministerio_id, escala_id=escala.id,
                membro_id=funcao.membro_id, funcao_nome=funcao.nome,
            ).save()
        titulo = f"{funcao.membro.nome}: {STATUS_LABELS[status_novo]} em {funcao.nome}"
        mensagem = f"{titulo} ({escala.nome}), respondido pelo WhatsApp."
        if status_novo == "troca_solicitada" and funcao.troca_motivo:
            mensagem += f' Mensagem: "{(texto or "").strip()[:300]}"'
        _notificar_lideres_do_ministerio(escala, titulo, mensagem, tipo=status_novo)
        mudaram.append(funcao)
    return mudaram


def _texto_de_resposta(acao, escala, funcoes):
    if escala is None:
        return "Não encontramos nenhuma escala futura no seu nome. Se achar que é um engano, fale com a liderança."
    nomes = ", ".join(f.nome for f in funcoes)
    quando = _quando(escala)
    onde = f"{escala.nome}" + (f" ({quando})" if quando else "")
    if acao == "confirmar":
        if all(f.status == "presente" for f in funcoes):
            return f"Sua presença em {onde} já está registrada. Obrigado!"
        return f"✅ Confirmado: {nomes} em {onde}. Obrigado!"
    return (f"Certo, avisamos a liderança que você não pode estar em {onde} ({nomes}). "
            "Eles vão providenciar a troca.")


# --- Webhook -----------------------------------------------------------------------

def _texto_da_mensagem(msg):
    tipo = msg.get("type")
    if tipo == "text":
        return (msg.get("text") or {}).get("body", "")
    if tipo == "button":
        return (msg.get("button") or {}).get("text", "")
    if tipo == "interactive":
        interativo = msg.get("interactive") or {}
        escolha = interativo.get("button_reply") or interativo.get("list_reply") or {}
        return escolha.get("title", "")
    if tipo == "reaction":
        return (msg.get("reaction") or {}).get("emoji", "")
    return f"[{tipo or 'mensagem'} -- abra no WhatsApp pra ver]"


def registrar_enviada(telefone, texto, comunidade_ids, membro_ids=(), usuario_id=None):
    return MensagemWhatsapp(
        direcao=ENVIADA, telefone=telefone.lstrip("+"), texto=texto, lida=True,
        comunidade_ids=list(comunidade_ids), membro_ids=list(membro_ids),
        enviada_por_usuario_id=usuario_id,
    ).save()


def _responder(telefone, texto, comunidade_ids, membro_ids):
    from app.whatsapp import WhatsappNaoEnviadoError, enviar_whatsapp

    try:
        enviar_whatsapp("+" + telefone, texto)
    except WhatsappNaoEnviadoError as erro:
        current_app.logger.warning("Resposta automatica de WhatsApp nao enviada: %s", erro)
        return
    current_app.logger.info("Resposta automatica de WhatsApp enviada para %s.", _mascarar(telefone))
    registrar_enviada(telefone, texto, comunidade_ids, membro_ids)


TEXTO_NUMERO_DESCONHECIDO = (
    "Olá! Recebemos sua mensagem, mas este número de WhatsApp não está cadastrado no diretório "
    "de nenhuma comunidade. Peça à liderança para conferir seu telefone (com DDD) no cadastro de membros."
)


def _mascarar(telefone):
    """Telefone pro log sem expor o numero inteiro: 5511*****4321."""
    return telefone[:4] + "*****" + telefone[-4:] if len(telefone) > 8 else telefone


def _responder_numero_desconhecido(telefone):
    """Avisa quem nao esta em diretorio nenhum -- sem isso a pessoa manda
    "confirmo" e fica sem resposta nenhuma, achando que o sistema quebrou.
    No maximo 1 aviso a cada 24h por numero, pra nao responder toda mensagem."""
    desde = datetime.now(timezone.utc) - JANELA_RESPOSTA
    if MensagemWhatsapp.objects(telefone=telefone, direcao=ENVIADA, criada_em__gte=desde).first():
        return
    _responder(telefone, TEXTO_NUMERO_DESCONHECIDO, [], [])


def processar_mensagem(msg, nomes_perfil):
    telefone = (msg.get("from") or "").lstrip("+")
    wamid = msg.get("id")
    if not telefone:
        current_app.logger.warning("WhatsApp recebido sem remetente ('from'), ignorado: %s", msg)
        return None
    if wamid and MensagemWhatsapp.objects(wamid=wamid).first():
        current_app.logger.info("WhatsApp %s repetido (a Meta reenviou), ignorado.", wamid)
        return None
    texto = _texto_da_mensagem(msg)
    membros = membros_do_telefone(telefone)
    comunidade_ids = sorted({m.comunidade_id for m in membros})
    current_app.logger.info(
        "WhatsApp recebido de %s (tipo %s): %d membro(s) com esse telefone, comunidade(s) %s.",
        _mascarar(telefone), msg.get("type"), len(membros), comunidade_ids or "nenhuma",
    )
    registro = MensagemWhatsapp(
        wamid=wamid, direcao=RECEBIDA, telefone=telefone, nome_perfil=nomes_perfil.get(telefone),
        texto=texto, membro_ids=[m.id for m in membros], comunidade_ids=comunidade_ids,
    )
    try:
        registro.save()
    except mongoengine.NotUniqueError:
        return None  # a mesma mensagem chegou em dois webhooks ao mesmo tempo

    if not membros:
        current_app.logger.warning(
            "WhatsApp de %s: telefone nao bate com nenhum Membro de diretorio (confira se esta "
            "cadastrado com DDD). Mensagem guardada, mas nao aparece em comunidade nenhuma.",
            _mascarar(telefone),
        )
        _responder_numero_desconhecido(telefone)
        return registro

    acao = interpretar_resposta(texto)
    if acao is None:
        current_app.logger.info("WhatsApp de %s nao e confirmacao/recusa: foi pra caixa de entrada.",
                                _mascarar(telefone))
        return registro  # fica na caixa de entrada pra lideranca

    escala, funcoes = proxima_escala_dos_membros(membros)
    current_app.logger.info("WhatsApp de %s: acao %s, proxima escala %s.", _mascarar(telefone), acao,
                            escala.id if escala else "nenhuma")
    if escala is not None:
        aplicar_resposta(acao, funcoes, texto)
        registro.acao = "confirmado" if acao == "confirmar" else "troca_solicitada"
        registro.escala_id = escala.id
        registro.lida = True  # ja resolvida sozinha; nao precisa de atencao
        registro.save()
    _responder(telefone, _texto_de_resposta(acao, escala, funcoes), comunidade_ids, registro.membro_ids)
    return registro


def processar_webhook(payload):
    """Percorre o JSON do webhook. Status de entrega ("sent", "read"...) sao
    ignorados -- so mensagens recebidas interessam aqui."""
    processadas = []
    if not payload:
        current_app.logger.warning("Webhook do WhatsApp sem JSON no corpo, ignorado.")
        return processadas
    for entrada in payload.get("entry") or []:
        for mudanca in entrada.get("changes") or []:
            valor = mudanca.get("value") or {}
            mensagens = valor.get("messages") or []
            status = valor.get("statuses") or []
            current_app.logger.info("Webhook do WhatsApp (campo %s): %d mensagem(ns), %d status de entrega.",
                                    mudanca.get("field"), len(mensagens), len(status))
            # Status "failed" e o unico lugar onde a Meta conta por que uma
            # resposta NOSSA nao chegou (ex: numero fora da lista de teste,
            # janela de 24h, pagamento) -- o envio em si devolveu 200.
            for s in status:
                if s.get("status") == "failed":
                    current_app.logger.warning("Meta nao entregou WhatsApp para %s: %s",
                                               _mascarar(s.get("recipient_id") or ""), s.get("errors"))
            nomes = {
                (c.get("wa_id") or "").lstrip("+"): (c.get("profile") or {}).get("name")
                for c in valor.get("contacts") or []
            }
            for msg in mensagens:
                registro = processar_mensagem(msg, nomes)
                if registro is not None:
                    processadas.append(registro)
    return processadas


# --- Caixa de entrada (comunidade.whatsapp) --------------------------------------------

def conversas_da_comunidade(comunidade_id):
    """Uma entrada por telefone, a mais recente primeiro: ultima mensagem,
    quantas recebidas nao lidas e o nome (diretorio > perfil do WhatsApp)."""
    from app.escala.models import Membro

    mensagens = MensagemWhatsapp.objects(comunidade_ids=comunidade_id).order_by("-criada_em")
    conversas = {}
    for m in mensagens:
        c = conversas.setdefault(m.telefone, {"telefone": m.telefone, "ultima": m, "nao_lidas": 0,
                                               "membro_ids": set(), "nome_perfil": None})
        if m.direcao == RECEBIDA and not m.lida:
            c["nao_lidas"] += 1
        c["membro_ids"].update(m.membro_ids or [])
        c["nome_perfil"] = c["nome_perfil"] or m.nome_perfil
    ids = {i for c in conversas.values() for i in c["membro_ids"]}
    nomes = {m.id: m.nome for m in Membro.objects(id__in=list(ids), comunidade_id=comunidade_id).only("id", "nome")}
    for c in conversas.values():
        nomes_membros = [nomes[i] for i in c["membro_ids"] if i in nomes]
        c["nome"] = nomes_membros[0] if nomes_membros else (c["nome_perfil"] or "+" + c["telefone"])
    return list(conversas.values())


def nao_lidas_da_comunidade(comunidade_id):
    return MensagemWhatsapp.objects(comunidade_ids=comunidade_id, direcao=RECEBIDA, lida=False).count()


def pode_responder_livre(mensagens):
    """Dentro da janela de 24h desde a ultima mensagem RECEBIDA?"""
    recebidas = [m.criada_em for m in mensagens if m.direcao == RECEBIDA and m.criada_em]
    if not recebidas:
        return False
    ultima = max(recebidas)
    if ultima.tzinfo is None:
        ultima = ultima.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - ultima < JANELA_RESPOSTA
