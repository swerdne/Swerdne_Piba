"""Agenda (.ics): "Adicionar ao calendario" de um evento e os calendarios
para assinar no Google Agenda / iPhone (Perfil > Minhas escalas na agenda).

Assinatura: o link leva o token da conta (User.token_agenda) e nao pede
login -- o Google busca o arquivo sozinho, sem cookie. Por isso o token e
longo e aleatorio, e "Gerar novo link" troca o token (o antigo para de
funcionar). O Google atualiza a assinatura de tempos em tempos (horas); isso
e dele, nao da para forcar daqui.
"""
from datetime import date, datetime, time, timedelta, timezone

FUSO = "America/Sao_Paulo"
DURACAO_PADRAO = timedelta(hours=2)


def escapar(texto):
    return (texto or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _dobrar(linha):
    """Linhas de no maximo 75 bytes (RFC 5545), continuando com espaco."""
    bruto = linha.encode("utf-8")
    if len(bruto) <= 75:
        return linha
    partes, atual = [], b""
    for caractere in linha:
        pedaco = caractere.encode("utf-8")
        if len(atual) + len(pedaco) > (75 if not partes else 74):
            partes.append(atual.decode("utf-8"))
            atual = b""
        atual += pedaco
    partes.append(atual.decode("utf-8"))
    return "\r\n ".join(partes)


def evento_ics(uid, dia, horario=None, horario_fim=None, titulo="", descricao="", local=None, url=None,
               ultimo_dia=None, cancelado=False):
    """Linhas de um VEVENT. Sem horario: dia(s) inteiro(s)."""
    if horario:
        inicio = datetime.combine(dia, horario)
        if horario_fim and horario_fim > horario:
            fim = datetime.combine(ultimo_dia or dia, horario_fim)
        else:
            fim = datetime.combine(ultimo_dia or dia, horario) + DURACAO_PADRAO
        datas = [f"DTSTART;TZID={FUSO}:{inicio:%Y%m%dT%H%M%S}", f"DTEND;TZID={FUSO}:{fim:%Y%m%dT%H%M%S}"]
    else:  # dia inteiro: o fim e exclusivo
        datas = [f"DTSTART;VALUE=DATE:{dia:%Y%m%d}",
                 f"DTEND;VALUE=DATE:{(ultimo_dia or dia) + timedelta(days=1):%Y%m%d}"]
    linhas = ["BEGIN:VEVENT", f"UID:{uid}", f"DTSTAMP:{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}", *datas,
              f"SUMMARY:{escapar(titulo)}"]
    if descricao:
        linhas.append(f"DESCRIPTION:{escapar(descricao)}")
    if local:
        linhas.append(f"LOCATION:{escapar(local)}")
    if url:
        linhas.append(f"URL:{url}")
    if cancelado:
        linhas.append("STATUS:CANCELLED")
    linhas.append("END:VEVENT")
    return linhas


def calendario(nome, eventos):
    """Arquivo .ics completo (texto) com os VEVENTs dados (listas de linhas)."""
    linhas = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//TyBenson//Agenda//PT-BR", "CALSCALE:GREGORIAN",
              "METHOD:PUBLISH", f"X-WR-CALNAME:{escapar(nome)}", f"X-WR-TIMEZONE:{FUSO}",
              # Pede ao app de agenda pra buscar de novo a cada 6 h (o Google decide sozinho).
              "REFRESH-INTERVAL;VALUE=DURATION:PT6H", "X-PUBLISHED-TTL:PT6H"]
    for evento in eventos:
        linhas.extend(evento)
    linhas.append("END:VCALENDAR")
    return "\r\n".join(_dobrar(l) for l in linhas) + "\r\n"


# --- O que entra em cada calendario ------------------------------------------------

JANELA_PASSADO = timedelta(days=30)
JANELA_FUTURO = timedelta(days=365)


def _local_por_ministerio():
    from app.escala.checkin import local_do_checkin

    cache = {}

    def local(ministerio):
        if ministerio is None:
            return None
        if ministerio.id not in cache:
            achado = local_do_checkin(ministerio)
            cache[ministerio.id] = achado.endereco if achado and achado.endereco else None
        return cache[ministerio.id]
    return local


def _eventos_da_comunidade(ids_comunidade, inicio, fim, url_evento):
    from app.comunidade.models import Evento

    saida = []
    for ev in Evento.objects(comunidade_id__in=list(ids_comunidade), data__lte=fim, data__gte=inicio - timedelta(days=30)):
        if ev.ultimo_dia < inicio:
            continue
        saida.append(evento_ics(
            f"evento-{ev.id}@tybenson", ev.data, ev.horario, None, ev.nome, ev.descricao or "", ev.local,
            url_evento(ev), ultimo_dia=ev.ultimo_dia,
        ))
    return saida


def agenda_pessoal(usuario, url_escala, url_evento):
    """As escalas da pessoa (uma entrada por escala, com as funcoes dela) e os
    eventos das comunidades em que ela esta."""
    from app.comunidade.models import UsuarioComunidade
    from app.escala.models import Escala, Funcao, Membro
    from app.fuso import hoje_brasilia
    from app.ministerio.models import Ministerio

    hoje = hoje_brasilia()
    inicio, fim = hoje - JANELA_PASSADO, hoje + JANELA_FUTURO
    membros = list(Membro.da_conta((usuario.email or "").lower()).only("id", "comunidade_id"))
    funcoes_por_escala = {}
    if membros:
        for f in Funcao.objects(membro_id__in=[m.id for m in membros]):
            funcoes_por_escala.setdefault(f.escala_id, []).append(f)
    escalas = list(Escala.objects(id__in=list(funcoes_por_escala), data__gte=inicio, data__lte=fim)) if funcoes_por_escala else []
    ministerios = {m.id: m for m in Ministerio.objects(id__in=list({e.ministerio_id for e in escalas}))} if escalas else {}
    local = _local_por_ministerio()

    eventos = []
    for escala in escalas:
        ministerio = ministerios.get(escala.ministerio_id)
        nomes = ", ".join(f.nome_exibido for f in funcoes_por_escala[escala.id])
        titulo = f"{escala.nome} · {nomes}"
        descricao = (f"Ministério: {ministerio.nome}\n" if ministerio else "") + f"Sua função: {nomes}\n{url_escala(escala)}"
        eventos.append(evento_ics(
            f"escala-{escala.id}-pessoa-{usuario.id}@tybenson", escala.data, escala.horario, escala.horario_fim,
            titulo, descricao, local(ministerio), url_escala(escala), cancelado=bool(escala.cancelada),
        ))

    ids_comunidade = {m.comunidade_id for m in membros}
    ids_comunidade |= {u.comunidade_id for u in UsuarioComunidade.objects(usuario_id=usuario.id).only("comunidade_id")}
    eventos += _eventos_da_comunidade(ids_comunidade, inicio, fim, url_evento)
    return calendario("Minhas escalas (TyBenson)", eventos)


def agenda_do_ministerio(ministerio, url_escala, url_evento):
    """Todas as escalas do ministerio, com quem esta escalado, e os eventos da comunidade."""
    from app.escala.models import Escala, Funcao, Membro, TIPO_FUNCAO
    from app.fuso import hoje_brasilia

    hoje = hoje_brasilia()
    inicio, fim = hoje - JANELA_PASSADO, hoje + JANELA_FUTURO
    escalas = list(Escala.objects(ministerio_id=ministerio.id, data__gte=inicio, data__lte=fim))
    funcoes = list(Funcao.objects(escala_id__in=[e.id for e in escalas], tipo=TIPO_FUNCAO)) if escalas else []
    membros = {m.id: m.nome for m in Membro.objects(id__in=list({f.membro_id for f in funcoes if f.membro_id})).only("id", "nome")}
    local = _local_por_ministerio()(ministerio)

    eventos = []
    for escala in escalas:
        linhas = [f"{f.nome_exibido}: {membros.get(f.membro_id, 'vaga')}"
                  for f in sorted((f for f in funcoes if f.escala_id == escala.id), key=lambda f: f.ordem or 0)]
        descricao = "\n".join(linhas + [url_escala(escala)])
        eventos.append(evento_ics(
            f"escala-{escala.id}@tybenson", escala.data, escala.horario, escala.horario_fim,
            escala.nome, descricao, local, url_escala(escala), cancelado=bool(escala.cancelada),
        ))
    eventos += _eventos_da_comunidade({ministerio.comunidade_id}, inicio, fim, url_evento)
    return calendario(f"{ministerio.nome} (TyBenson)", eventos)
