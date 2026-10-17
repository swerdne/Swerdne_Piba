"""Mensagens de WhatsApp RECEBIDAS (webhook da Meta Cloud API).

O envio fica em app/whatsapp.py; aqui fica o caminho de volta:

- `processar_webhook(payload)` -- chamado pela rota main.whatsapp_webhook
  (assinatura ja conferida la) com o JSON que a Meta manda.
- Cada mensagem vira uma `MensagemWhatsapp`, ligada aos Membros cujo telefone
  do diretorio bate com o remetente (`membros_do_telefone`) e as comunidades
  deles -- e o que a caixa de entrada da comunidade mostra
  (comunidade.whatsapp).
- Roteador de intencao por palavras-chave (`interpretar_mensagem`):
  confirmar ("confirmo", "pode contar comigo", "beleza"), recusar ("nao vou
  conseguir", "nao da") e troca ("preciso trocar", "quem pode me
  substituir?") mudam TODAS as funcoes da pessoa na PROXIMA escala dela (nao
  cancelada, de hoje em diante) -- mesmo efeito do botao de status do site
  (lideres avisados no sino, RegistroTroca; recusa e troca viram
  troca_solicitada). Perguntas so leem e respondem: musicas do repertorio
  da proxima escala (com links das folhas de cifras/projecao), proximas escalas,
  endereco (Comunidade.endereco/lat/lng) e horarios (dias/horario de culto
  dos ministerios + eventos dos proximos 30 dias). Na duvida (pergunta,
  negacao, incerteza, dupla negacao) nao muda nada: sem resposta
  automatica, fica na caixa de entrada pra lideranca -- igual a pergunta
  de endereco/horario sem dado cadastrado.
"""
import re
import unicodedata
from datetime import datetime, timedelta, timezone

import mongoengine
from flask import current_app, url_for

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
    # Audio recebido (msg.type == "audio", inclusive mensagem de voz): o id da
    # midia na Meta -- o arquivo fica em AudioWhatsapp (ver baixar_audio).
    media_id = mongoengine.StringField(max_length=200)
    media_mime = mongoengine.StringField(max_length=100)
    # O que o audio dizia (app/transcricao.py), quando a transcricao esta ligada.
    transcricao = mongoengine.StringField()
    # O que aconteceu na transcricao (diagnostico, lido pelo banco/caixa de
    # entrada): "ok", "desligada" (sem AZURE_SPEECH_*), "sem_fala", "sem_arquivo"
    # ou "erro: <motivo do Azure>".
    status_transcricao = mongoengine.StringField(max_length=400)

    @property
    def eh_audio(self):
        return bool(self.media_id)
    enviada_por_usuario_id = mongoengine.IntField()  # resposta escrita na caixa de entrada
    lida = mongoengine.BooleanField(default=False)
    criada_em = mongoengine.DateTimeField(default=lambda: datetime.now(timezone.utc))



class AudioWhatsapp(SequentialIdDocument):
    """O arquivo de um audio recebido, separado da mensagem pra lista da
    caixa de entrada nao carregar os bytes. Baixado da Meta logo que chega
    (em segundo plano, ver baixar_audio) ou na hora de tocar, se ainda nao."""
    meta = {"collection": "audios_whatsapp", "indexes": [{"fields": ["mensagem_id"], "unique": True}]}
    _nome_sequencia = "audios_whatsapp"

    mensagem_id = mongoengine.IntField(required=True)
    mime = mongoengine.StringField(max_length=100)
    conteudo = mongoengine.BinaryField(required=True)
    baixado_em = mongoengine.DateTimeField(default=lambda: datetime.now(timezone.utc))


def baixar_audio(mensagem):
    """AudioWhatsapp da mensagem: o guardado ou, sem ele, baixado da Meta
    agora (e guardado). None se nao der (sem config, midia expirada...) --
    o motivo vai pro log."""
    from app.whatsapp import WhatsappNaoEnviadoError, baixar_midia

    if not mensagem.media_id:
        return None
    guardado = AudioWhatsapp.objects(mensagem_id=mensagem.id).first()
    if guardado is not None:
        return guardado
    try:
        conteudo, mime = baixar_midia(mensagem.media_id)
    except WhatsappNaoEnviadoError as erro:
        current_app.logger.warning("Audio do WhatsApp %s nao baixado: %s", mensagem.id, erro)
        return None
    audio = AudioWhatsapp(mensagem_id=mensagem.id, mime=mime or mensagem.media_mime, conteudo=conteudo)
    try:
        audio.save()
    except mongoengine.NotUniqueError:  # dois downloads ao mesmo tempo: vale o primeiro
        return AudioWhatsapp.objects(mensagem_id=mensagem.id).first()
    return audio


def _em_segundo_plano(funcao, *args):
    """Roda `funcao(*args)` sem atrasar a resposta do webhook (a Meta
    reenvia se demorar). Em teste roda na hora.

    Com um request de mentira apontando pro URL_PUBLICA (nao so app
    context): as respostas montam links com url_for (ex: folhas de cifra do
    repertorio), que fora de um request quebrava -- o audio era transcrito
    e ficava sem resposta. Mesmo contexto na hora e em thread, pra o teste
    pegar isso."""
    import threading

    app = current_app._get_current_object()
    base = app.config.get("URL_PUBLICA") or "http://localhost"

    def trabalho():
        with app.test_request_context("/", base_url=base):
            try:
                funcao(*args)
            except Exception:
                app.logger.exception("Tarefa do WhatsApp em segundo plano falhou")

    if app.testing:
        trabalho()
    else:
        threading.Thread(target=trabalho, daemon=True).start()


def _baixar_audio_por_id(mensagem_id):
    registro = MensagemWhatsapp.objects(id=mensagem_id).first()
    if registro is not None:
        baixar_audio(registro)


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


# Roteador de intencao por palavras-chave (sem IA). Regra de ouro: na duvida,
# None -- a mensagem vai pra caixa de entrada da lideranca, como sempre.
# Mudar status de escala por engano e pior do que nao responder.
CONFIRMAR, RECUSAR, TROCA = "confirmar", "recusar", "troca"
CONSULTA_ESCALA, ENDERECO, HORARIOS = "consulta_escala", "endereco", "horarios"
REPERTORIO = "repertorio"
AJUDA = "ajuda"

# Menu de comandos: a pessoa manda "menu"/"ajuda"/"oi" e recebe a lista;
# o numero sozinho escolhe a opcao (1 e 2 ja valiam como sim/nao antes).
MENU_OPCOES = (
    ("1", "Confirmar minha próxima escala", CONFIRMAR),
    ("2", "Não posso ir / pedir troca", RECUSAR),
    ("3", "Minhas próximas escalas", CONSULTA_ESCALA),
    ("4", "Músicas do repertório", REPERTORIO),
    ("5", "Endereço da igreja", ENDERECO),
    ("6", "Horários dos cultos", HORARIOS),
)
_INTENCAO_POR_NUMERO = {numero: intencao for numero, _, intencao in MENU_OPCOES}
# Menu automatico pra mensagem nao reconhecida: no maximo 1 a cada X, pra
# nao interromper conversa com a lideranca pela caixa de entrada.
INTERVALO_MENU_AUTOMATICO = timedelta(hours=12)
MUDAM_ESCALA = (CONFIRMAR, RECUSAR, TROCA)

_TROCA = re.compile(
    r"\b(troca|trocar|trocaria|substitu\w*|me cobrir|cobrir pra mim|cobrir para mim|no meu lugar|ir no meu)\b"
)
_RECUSA = re.compile(
    r"\b(nao|n)\s+(posso|vou|consigo|conseguirei|irei|poderei|vai dar|da|dou conta|tenho como|estarei"
    r"|comparecerei|rola|vai rolar|vai ser possivel)\b"
    r"|\binfelizmente nao\b|\bimpossivel\b|\bvou faltar\b|\brecuso\b|\bfora da cidade\b"
    r"|\b(estou|to|estarei|vou estar)\s+(doente|viajando|fora|internad\w*|trabalhando|de plantao)\b"
)
_CONFIRMA = re.compile(
    r"\b(confirm\w*|estarei|irei|pode contar|conta comigo|tamo junto|estamos juntos|estou dentro|to dentro"
    r"|vou sim|com certeza|pode deixar|vou estar la)\b"
)
# Palavras curtas que so confirmam/recusam quando a mensagem inteira e feita
# delas (mais cumprimentos/agradecimentos): "ok, valeu" confirma; "ok, mas
# que horas" nao ("mas" e "horas" nao estao em nenhuma das listas).
_SO_CONFIRMA = {"sim", "s", "ok", "okay", "okk", "1", "vou", "presente", "certo", "beleza", "blz", "combinado",
                "fechado", "claro", "positivo", "ciente", "perfeito", "show", "confirmado", "confirmada", "joia"}
_SO_RECUSA = {"nao", "n", "2", "troca", "infelizmente"}
_CORTESIA = {"obrigado", "obrigada", "valeu", "vlw", "deus", "abencoe", "amem", "irmao", "irma", "pastor",
             "pastora", "lider", "ja", "entao", "opa", "oi", "ola", "bom", "boa", "dia", "tarde", "noite",
             "a", "o", "e", "paz", "gracas", "sim", "pra", "voce", "vc", "td", "tudo"}
# Incerteza ("talvez", "acho que", "vou ver"): nunca muda escala.
_INCERTEZA = re.compile(
    r"\b(talvez|acho que|acredito que|depende|se der|se eu|vou ver|vou tentar|nao sei|provavelmente"
    r"|possivelmente|quem sabe|te aviso|depois confirmo|confirmo depois|confirmo mais tarde|ainda vou ver)\b"
)
_NEGACAO = re.compile(r"\b(nao|n|nem|nunca)\b")
# "Nao vou faltar"/"nao posso perder" querem dizer que VAI -- mas parecem
# recusa pras regras acima. Dupla negacao nunca muda escala.
_DUPLA_NEGACAO = re.compile(
    r"\b(nao|n)\s+(vou|posso|irei|vou deixar de)\s+(faltar|esquecer|perder|deixar|ir embora)\b"
)
_CONSULTA_ESCALA = re.compile(
    r"\b(proxim\w* escala\w*|minha escala|minhas escalas|meu culto|minha proxima|estou escalad\w*|to escalad\w*"
    r"|sou escalad\w*|fui escalad\w*|escalad\w* (pra|para) quando|quando (eu )?(sirvo|vou servir|toco|canto|estou|to)"
    r"|qual (e )?(a )?minha (funcao|escala)|que dia (eu )?(sirvo|toco|canto|estou|to))\b"
)
_REPERTORIO = re.compile(
    r"\b(musica\w*|repertorio\w*|cifra\w*|louvores|setlist|playlist|projecao|letras?|tons)\b"
)
_ENDERECO = re.compile(
    r"\b(endereco|onde fica|onde e a igreja|localizacao|como (eu )?chego|qual o local|onde (vai ser|sera|e) o culto)\b"
)
_HORARIOS = re.compile(r"\b(horario\w*|que horas|qual (a )?hora)\b")
_ASSUNTO_CULTO = re.compile(r"\b(culto\w*|igreja|reuniao|reunioes|celebrac\w*|programac\w*)\b")
_JOINHA = {"👍", "👍🏻", "👍🏼", "👍🏽", "👍🏾", "👍🏿", "✅"}
_AJUDA = re.compile(
    r"^(ajuda|menu|comandos?|opcoes|opcao|help|inicio)\b|\b(o que (voce|vc) (faz|sabe|pode)|como funciona"
    r"|quais (sao )?(os )?comandos)\b"
)
# Cumprimento sozinho ("oi", "bom dia, tudo bem?") tambem abre o menu.
_CUMPRIMENTO = {"oi", "ola", "opa", "bom", "boa", "dia", "tarde", "noite", "tudo", "bem", "td", "bele", "e", "ai",
                "paz", "a", "do", "senhor", "irmao", "irma", "pastor", "pastora", "eae", "salve", "oii", "oie"}


def _so_palavras(normal, essenciais):
    """A mensagem inteira e feita de `essenciais` + cortesia, com pelo menos 1 essencial?"""
    palavras = normal.replace("ta bom", "certo").replace("ta certo", "certo").replace("ta otimo", "certo").split()
    return any(p in essenciais for p in palavras) and all(p in essenciais or p in _CORTESIA for p in palavras)


def interpretar_mensagem(texto):
    """Uma das intencoes acima ou None (nao reconhecida -> caixa de entrada).

    Ordem: numero do menu / so cumprimento > troca > recusa > musicas do
    repertorio > pergunta da propria escala > endereco > horarios > pedido
    de ajuda > confirmacao. Confirmacao e a mais cautelosa: nunca com "?",
    com uma negacao em qualquer lugar ("nao confirmo ainda") ou com
    incerteza ("acho que vou") -- nesses casos fica None."""
    bruto = (texto or "").strip()
    if bruto in _JOINHA:
        return CONFIRMAR
    if bruto in {"👎", "❌"}:
        return RECUSAR
    normal = _normalizar(bruto)
    if not normal:
        return AJUDA if bruto == "?" else None
    if normal in _INTENCAO_POR_NUMERO:
        return _INTENCAO_POR_NUMERO[normal]
    if all(p in _CUMPRIMENTO for p in normal.split()):
        return AJUDA
    pergunta = "?" in bruto
    incerto = bool(_INCERTEZA.search(normal)) or bool(_DUPLA_NEGACAO.search(normal))

    if _TROCA.search(normal):
        return None if incerto else TROCA
    if normal in _SO_RECUSA or _so_palavras(normal, _SO_RECUSA) or _RECUSA.search(normal):
        return None if incerto else RECUSAR
    # Perguntas so ganham da confirmacao quando sao pergunta mesmo: "vou
    # estudar as musicas, pode contar" e confirmacao, nao pedido de repertorio.
    sem_confirmacao = pergunta or not _CONFIRMA.search(normal)
    if _REPERTORIO.search(normal) and sem_confirmacao:
        return REPERTORIO
    if _CONSULTA_ESCALA.search(normal) and sem_confirmacao:
        return CONSULTA_ESCALA
    if _ENDERECO.search(normal):
        return ENDERECO
    if _HORARIOS.search(normal) and _ASSUNTO_CULTO.search(normal):
        return HORARIOS
    # Pedido de ajuda so depois das outras: "ajuda, preciso trocar" e troca.
    if _AJUDA.search(normal):
        return AJUDA
    if pergunta or incerto or _NEGACAO.search(normal):
        return None
    if _so_palavras(normal, _SO_CONFIRMA) or _CONFIRMA.search(normal):
        return CONFIRMAR
    return None


def interpretar_resposta(texto):
    """Compatibilidade: so "confirmar"/"recusar"/None (troca conta como recusa)."""
    intencao = interpretar_mensagem(texto)
    if intencao == TROCA:
        return RECUSAR
    return intencao if intencao in (CONFIRMAR, RECUSAR) else None


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
    if acao == CONFIRMAR:
        if all(f.status == "presente" for f in funcoes):
            return f"Sua presença em {onde} já está registrada. Obrigado!"
        return f"✅ Confirmado: {nomes} em {onde}. Obrigado!"
    if acao == TROCA:
        return (f"🔄 Pedido de troca registrado: {nomes} em {onde}. A liderança foi avisada e vai combinar "
                "quem te substitui. Você continua na escala até eles confirmarem a troca.")
    return (f"Certo, avisamos a liderança que você não pode estar em {onde} ({nomes}). "
            "Eles vão providenciar a troca.")


# --- Perguntas (so leitura, nada muda) ------------------------------------------------

_DIAS_SEMANA = ("segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo")
_DIAS_SEMANA_CURTO = ("seg", "ter", "qua", "qui", "sex", "sáb", "dom")
_STATUS_NO_WHATSAPP = {"confirmado": "confirmado", "presente": "presente", "troca_solicitada": "troca pedida"}


def proximas_escalas_dos_membros(membros, limite=3):
    """[(escala, funcoes da pessoa nela)] das proximas escalas nao canceladas."""
    from app.escala.models import TIPO_FUNCAO, Escala, Funcao

    funcoes = list(Funcao.objects(membro_id__in=[m.id for m in membros], tipo=TIPO_FUNCAO)) if membros else []
    if not funcoes:
        return []
    escalas = (Escala.objects(id__in=list({f.escala_id for f in funcoes}), data__gte=_hoje_brasilia(),
                              cancelada__ne=True).order_by("data", "horario").limit(limite))
    return [(e, [f for f in funcoes if f.escala_id == e.id]) for e in escalas]


def _texto_proximas_escalas(membros):
    proximas = proximas_escalas_dos_membros(membros)
    if not proximas:
        return "Você não tem nenhuma escala marcada de hoje em diante."
    linhas = ["📅 Suas próximas escalas:"]
    for escala, funcoes in proximas:
        quando = ""
        if escala.data:
            quando = f"{_DIAS_SEMANA_CURTO[escala.data.weekday()]}, {_quando(escala)}"
        ministerio = escala.ministerio.nome if escala.ministerio else ""
        funcoes_txt = ", ".join(
            f.nome + (f" ({_STATUS_NO_WHATSAPP[f.status]})" if f.status in _STATUS_NO_WHATSAPP else "")
            for f in funcoes
        )
        linhas.append(f"• {escala.nome}{f' ({ministerio})' if ministerio else ''} — {quando} — {funcoes_txt}")
    linhas.append("Para a próxima, responda \"confirmo\" ou \"não posso\".")
    return "\n".join(linhas)


def _texto_repertorio(membros):
    """Musicas (nome + tom do dia + momento) da proxima escala da pessoa que
    ja tem repertorio, entre as 3 proximas -- e os links das folhas de
    cifras/projecao no site (abrem pra quem esta escalado, com login). A
    cifra inteira nao vai: mensagem enorme."""
    proximas = proximas_escalas_dos_membros(membros)
    if not proximas:
        return "Você não tem nenhuma escala marcada de hoje em diante, então não há repertório pra mostrar."
    for escala, _ in proximas:
        itens = escala.repertorio
        if itens:
            break
    else:
        escala = proximas[0][0]
        quando = _quando(escala)
        return (f"O repertório de {escala.nome}{f' ({quando})' if quando else ''} ainda não foi definido. "
                "Assim que a liderança montar, ele aparece aqui e no site.")

    quando = _quando(escala)
    linhas = [f"🎵 Repertório de {escala.nome}{f' ({quando})' if quando else ''}:"]
    for n, item in enumerate(itens, 1):
        tom = item.tom or (item.musica.tom if item.musica else None)
        extras = " · ".join(p for p in (f"Tom: {tom}" if tom else "", item.momento or "") if p)
        linhas.append(f"{n}. {item.nome_musica}{f' — {extras}' if extras else ''}")
    site = current_app.config.get("URL_PUBLICA") or ""
    linhas.append("")
    linhas.append(f"Cifras: {site}{url_for('escala.folha_repertorio', escala_id=escala.id, tipo='cifras')}")
    linhas.append(f"Projeção: {site}{url_for('escala.folha_repertorio', escala_id=escala.id, tipo='projecao')}")
    linhas.append("(entre com a sua conta do site pra abrir)")
    return "\n".join(linhas)


def texto_do_menu(membros, introducao=None):
    """Lista de comandos com atalho por numero."""
    primeiro_nome = (membros[0].nome or "").split()[0].title() if membros and membros[0].nome else ""
    linhas = [introducao or f"Olá{', ' + primeiro_nome if primeiro_nome else ''}! 👋 Posso te ajudar com:"]
    linhas += [f"{numero} - {rotulo}" for numero, rotulo, _ in MENU_OPCOES]
    linhas.append("Responda com o número ou escreva do seu jeito (ex: \"quais as músicas do culto?\").")
    return "\n".join(linhas)


def _comunidades(comunidade_ids):
    from app.comunidade.models import Comunidade

    return list(Comunidade.objects(id__in=list(comunidade_ids))) if comunidade_ids else []


def _texto_endereco(comunidade_ids):
    """Endereco cadastrado da comunidade (o mesmo do check-in) -- None se nao
    tem nenhum (a pergunta vai pra caixa de entrada)."""
    linhas = []
    for comunidade in _comunidades(comunidade_ids):
        if not comunidade.endereco and comunidade.latitude is None:
            continue
        linha = f"📍 {comunidade.nome}: {comunidade.endereco or 'veja no mapa'}"
        if comunidade.latitude is not None and comunidade.longitude is not None:
            linha += f"\nhttps://maps.google.com/?q={comunidade.latitude:.6f},{comunidade.longitude:.6f}"
        linhas.append(linha)
    return "\n\n".join(linhas) or None


def _texto_horarios(comunidade_ids):
    """Dias/horario de culto dos ministerios (check-in de culto) e eventos da
    comunidade nos proximos 30 dias -- None se nao ha nada cadastrado."""
    from app.comunidade.models import Evento
    from app.ministerio.models import Ministerio

    linhas = []
    for comunidade in _comunidades(comunidade_ids):
        cultos = {}
        for m in Ministerio.objects(comunidade_id=comunidade.id):
            if m.dias_culto_efetivos and m.culto_horario:
                dias = ", ".join(_DIAS_SEMANA[d] for d in m.dias_culto_efetivos)
                cultos.setdefault(f"{dias} às {m.culto_horario.strftime('%H:%M')}", []).append(m.nome)
        hoje = _hoje_brasilia()
        eventos = list(Evento.objects(comunidade_id=comunidade.id, data__gte=hoje,
                                      data__lte=hoje + timedelta(days=30)).order_by("data").limit(3))
        if not cultos and not eventos:
            continue
        linhas.append(f"⛪ {comunidade.nome}")
        for quando, nomes in cultos.items():
            linhas.append(f"• Culto: {quando} ({', '.join(nomes)})")
        for e in eventos:
            hora = f" às {e.horario.strftime('%H:%M')}" if e.horario else ""
            local = f" — {e.local}" if e.local else ""
            linhas.append(f"• {e.nome}: {_DIAS_SEMANA_CURTO[e.data.weekday()]}, {e.data.strftime('%d/%m')}{hora}{local}")
    return "\n".join(linhas) or None


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
    if tipo == "audio":
        return "🎤 Mensagem de voz" if (msg.get("audio") or {}).get("voice") else "🎤 Áudio"
    return f"[{tipo or 'mensagem'} -- abra no WhatsApp pra ver]"


def registrar_enviada(telefone, texto, comunidade_ids, membro_ids=(), usuario_id=None, acao=None):
    return MensagemWhatsapp(
        direcao=ENVIADA, telefone=telefone.lstrip("+"), texto=texto, lida=True,
        comunidade_ids=list(comunidade_ids), membro_ids=list(membro_ids),
        enviada_por_usuario_id=usuario_id, acao=acao,
    ).save()


def _responder(telefone, texto, comunidade_ids, membro_ids, acao=None):
    from app.whatsapp import WhatsappNaoEnviadoError, enviar_whatsapp

    try:
        enviar_whatsapp("+" + telefone, texto)
    except WhatsappNaoEnviadoError as erro:
        current_app.logger.warning("Resposta automatica de WhatsApp nao enviada: %s", erro)
        return
    current_app.logger.info("Resposta automatica de WhatsApp enviada para %s.", _mascarar(telefone))
    registrar_enviada(telefone, texto, comunidade_ids, membro_ids, acao=acao)


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


def _nao_reconhecida(registro, telefone, membros, comunidade_ids, prefixo=""):
    """Fica na caixa de entrada pra lideranca (continua nao lida) e a pessoa
    recebe o menu -- no maximo 1x a cada INTERVALO_MENU_AUTOMATICO, pra nao
    interromper conversa com um lider."""
    desde = datetime.now(timezone.utc) - INTERVALO_MENU_AUTOMATICO
    menu_recente = MensagemWhatsapp.objects(telefone=telefone, direcao=ENVIADA, acao="menu",
                                            criada_em__gte=desde).first()
    current_app.logger.info("WhatsApp de %s nao reconhecido: foi pra caixa de entrada%s.", _mascarar(telefone),
                            "" if menu_recente else " e recebeu o menu")
    if not menu_recente:
        introducao = "Recebi sua mensagem e passei para a liderança 🙏 Se for uma destas, é só responder com o número:"
        _responder(telefone, prefixo + texto_do_menu(membros, introducao), comunidade_ids, registro.membro_ids,
                   acao="menu")
    return registro


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
    audio = (msg.get("audio") or {}) if msg.get("type") == "audio" else {}
    registro = MensagemWhatsapp(
        wamid=wamid, direcao=RECEBIDA, telefone=telefone, nome_perfil=nomes_perfil.get(telefone),
        texto=texto, membro_ids=[m.id for m in membros], comunidade_ids=comunidade_ids,
        media_id=str(audio.get("id") or "")[:200] or None, media_mime=str(audio.get("mime_type") or "")[:100] or None,
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

    if registro.media_id:
        from app.transcricao import transcricao_ligada

        if transcricao_ligada():
            # Baixa, transcreve e responde em segundo plano (pode levar
            # alguns segundos -- o webhook nao espera).
            _em_segundo_plano(_tratar_audio, registro.id)
            return registro
        # Sem AZURE_SPEECH_*: so guarda pra ouvir na caixa de entrada.
        current_app.logger.info("Audio de %s: transcricao desligada (sem AZURE_SPEECH_KEY/REGION).", _mascarar(telefone))
        registro.status_transcricao = "desligada"
        registro.save()
        _em_segundo_plano(_baixar_audio_por_id, registro.id)
        return _audio_nao_entendido(registro, telefone, comunidade_ids, TEXTO_AUDIO_SEM_TRANSCRICAO)

    return _tratar_texto(registro, telefone, texto, membros, comunidade_ids)


def _tratar_audio(mensagem_id):
    """Audio de quem esta no diretorio: baixa, transcreve (Azure Speech) e
    trata o texto como se tivesse sido escrito -- a resposta comeca com o
    que foi entendido, pra pessoa conferir. Sem fala reconhecivel ou com
    falha: caixa de entrada + menu, como mensagem nao reconhecida."""
    from app.transcricao import TranscricaoIndisponivel, transcrever

    registro = MensagemWhatsapp.objects(id=mensagem_id).first()
    if registro is None:
        return
    telefone = registro.telefone
    membros = membros_do_telefone(telefone)
    comunidade_ids = sorted({m.comunidade_id for m in membros})
    audio = baixar_audio(registro)
    texto, status = None, "sem_arquivo"
    if audio is not None:
        try:
            texto = transcrever(audio.conteudo, audio.mime or registro.media_mime)
            status = "ok" if texto else "sem_fala"
        except TranscricaoIndisponivel as erro:
            current_app.logger.warning("Audio do WhatsApp %s nao transcrito: %s", registro.id, erro)
            status = f"erro: {erro}"[:400]
    registro.status_transcricao = status
    if not texto:
        registro.save()
        current_app.logger.info("Audio de %s sem transcricao (%s): foi pra caixa de entrada.", _mascarar(telefone), status)
        return _audio_nao_entendido(registro, telefone, comunidade_ids)
    registro.transcricao = texto[:2000]
    registro.save()
    current_app.logger.info("Audio de %s transcrito (%d caracteres).", _mascarar(telefone), len(texto))
    return _tratar_texto(registro, telefone, texto, membros, comunidade_ids,
                         prefixo=f"🎤 Entendi: “{texto[:300]}”\n\n")


TEXTO_AUDIO_NAO_ENTENDIDO = ("🎤 Recebi seu áudio, mas não consegui entender agora. Ele ficou para a liderança ouvir. "
                             "Se quiser uma resposta na hora, mande de novo falando perto do celular ou escreva "
                             "(ex: \"qual minha próxima escala?\", ou \"menu\").")
TEXTO_AUDIO_SEM_TRANSCRICAO = ("🎤 Recebi seu áudio e passei para a liderança ouvir. Para eu responder na hora, "
                               "escreva a mensagem (ex: \"confirmo\", \"qual minha próxima escala?\" ou \"menu\").")
# Aviso de audio nao entendido: no maximo 1 a cada X por numero (varios
# audios seguidos nao viram varias respostas iguais).
INTERVALO_AVISO_AUDIO = timedelta(minutes=30)


def _audio_nao_entendido(registro, telefone, comunidade_ids, texto=TEXTO_AUDIO_NAO_ENTENDIDO):
    """Audio que o sistema nao conseguiu entender (ou transcricao
    desligada): fica nao lido na caixa de entrada e a pessoa recebe um aviso
    curto -- nunca silencio (o menu automatico tem limite de 12h)."""
    desde = datetime.now(timezone.utc) - INTERVALO_AVISO_AUDIO
    if not MensagemWhatsapp.objects(telefone=telefone, direcao=ENVIADA, acao="aviso_audio",
                                    criada_em__gte=desde).first():
        _responder(telefone, texto, comunidade_ids, registro.membro_ids, acao="aviso_audio")
    return registro


def _tratar_texto(registro, telefone, texto, membros, comunidade_ids, prefixo=""):
    """Roteador de intencao aplicado ao texto (escrito ou transcrito do
    audio). `prefixo` vai no comeco de toda resposta."""

    def responder(resposta, acao=None):
        _responder(telefone, prefixo + resposta, comunidade_ids, registro.membro_ids, acao=acao)

    intencao = interpretar_mensagem(texto)

    if intencao == AJUDA:
        current_app.logger.info("WhatsApp de %s: pediu o menu.", _mascarar(telefone))
        registro.acao = "informacao"
        registro.lida = True
        registro.save()
        responder(texto_do_menu(membros), acao="menu")
        return registro

    # Perguntas: so leitura. Sem dado cadastrado (endereco/horarios), cai na
    # caixa de entrada como mensagem nao reconhecida.
    if intencao in (CONSULTA_ESCALA, REPERTORIO, ENDERECO, HORARIOS):
        if intencao == CONSULTA_ESCALA:
            resposta = _texto_proximas_escalas(membros)
        elif intencao == REPERTORIO:
            resposta = _texto_repertorio(membros)
        elif intencao == ENDERECO:
            resposta = _texto_endereco(comunidade_ids)
        else:
            resposta = _texto_horarios(comunidade_ids)
        current_app.logger.info("WhatsApp de %s: pergunta %s, %s.", _mascarar(telefone), intencao,
                                "respondida" if resposta else "sem dado cadastrado, foi pra caixa de entrada")
        if resposta is None:
            return _nao_reconhecida(registro, telefone, membros, comunidade_ids, prefixo)
        registro.acao = "consulta" if intencao in (CONSULTA_ESCALA, REPERTORIO) else "informacao"
        registro.lida = True  # respondida sozinha
        registro.save()
        responder(resposta)
        return registro

    if intencao not in MUDAM_ESCALA:
        return _nao_reconhecida(registro, telefone, membros, comunidade_ids, prefixo)

    escala, funcoes = proxima_escala_dos_membros(membros)
    current_app.logger.info("WhatsApp de %s: acao %s, proxima escala %s.", _mascarar(telefone), intencao,
                            escala.id if escala else "nenhuma")
    if escala is not None:
        # Troca e recusa usam o mesmo fluxo do site (troca_solicitada: lideres
        # avisados no sino, aprovam escolhendo o substituto).
        aplicar_resposta(CONFIRMAR if intencao == CONFIRMAR else RECUSAR, funcoes, texto)
        registro.acao = "confirmado" if intencao == CONFIRMAR else "troca_solicitada"
        registro.escala_id = escala.id
        registro.lida = True  # ja resolvida sozinha; nao precisa de atencao
        registro.save()
    responder(_texto_de_resposta(intencao, escala, funcoes))
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
        # A previa mostra o que a pessoa escreveu, nao o menu automatico que
        # saiu logo depois (mesmo segundo) -- senao a pergunta some da lista.
        if c["ultima"].direcao == ENVIADA and c["ultima"].acao == "menu" and m.criada_em and c["ultima"].criada_em \
                and abs((c["ultima"].criada_em - m.criada_em).total_seconds()) < 60:
            c["ultima"] = m
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
