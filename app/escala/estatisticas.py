"""Estatisticas de comparecimento (tela "Estatisticas" do Ministerio e da
Comunidade), montadas em cima do check-in por localizacao (ver checkin.py).

Regras de contagem:
- So dias ja encerrados (data < hoje em Brasilia) e escalas nao canceladas.
- Uma escala so entra se teve ALGUMA presenca registrada (check-in ou
  "Presente" marcado pelo lider). Sem nenhuma, nao da pra saber se alguem foi
  (escala de antes do check-in existir, ministerio sem local cadastrado) -- ela
  aparece so como "sem registro", senao viraria falta de todo mundo.
- Comparecimento = check-in OU "Presente" marcado pelo lider; falta = o resto.
- Horario de chegada so vem do check-in, e so quando a escala tem horario.
  Check-in a mais de LIMITE_PONTUALIDADE_MIN do horario fica fora das medias
  (a pessoa passou na igreja em outro momento do dia).
- Tres visoes que nunca se misturam (TIPOS): escalas, ensaios e cultos; a
  tela so mostra as dos tipos de check-in ligados no ministerio.
"""
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

from app.escala.models import (
    TIPO_SUBCABECALHO, AlertaFaltas, Ensaio, Escala, Funcao, Membro, PresencaCulto, PresencaEnsaio, RegistroTroca,
)

PERIODOS = {
    "30d": ("Últimos 30 dias", 30),
    "3m": ("3 meses", 91),
    "6m": ("6 meses", 182),
    "1a": ("1 ano", 365),
}
PERIODO_PADRAO = "3m"
TIPOS = {"escalas": "Escalas", "ensaios": "Ensaios", "cultos": "Cultos"}
_TIPO_DO_CHECKIN = {"escalas": "escala", "ensaios": "ensaio", "cultos": "culto"}
TOLERANCIA_PADRAO_MIN = 10
ALERTA_FALTAS_PADRAO = 3
LIMITE_PONTUALIDADE_MIN = 180
MINIMO_ESCALAS_RANKING = 3
DIAS_SEMANA = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
_MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def hoje_brasilia():
    return (datetime.now(timezone.utc) - timedelta(hours=3)).date()


def tolerancia_de(ministerio):
    valor = ministerio.tolerancia_atraso_min
    return TOLERANCIA_PADRAO_MIN if valor is None else valor


def alerta_de(ministerio):
    valor = ministerio.alerta_faltas_seguidas
    return ALERTA_FALTAS_PADRAO if valor is None else valor


@dataclass
class Registro:
    escala_id: object  # id da escala/ensaio, ou (ministerio_id, data) no culto
    data: date
    ministerio_id: int
    funcao_nome: str
    membro_id: int
    compareceu: bool
    checkin: bool
    minutos: int | None  # chegada - horario da escala (negativo = adiantado)
    tolerancia: int


def _minutos_de_chegada(evento, checkin_em):
    """evento: Escala ou Ensaio (data + horario)."""
    if not checkin_em or not evento.horario:
        return None
    chegada = checkin_em
    if chegada.tzinfo is not None:
        chegada = chegada.astimezone(timezone.utc).replace(tzinfo=None)
    chegada -= timedelta(hours=3)
    diferenca = round((chegada - datetime.combine(evento.data, evento.horario)).total_seconds() / 60)
    return diferenca if abs(diferenca) <= LIMITE_PONTUALIDADE_MIN else None


def coletar(ministerios, inicio, fim):
    """(registros, escalas_sem_registro, ids de todas as escalas do periodo,
    nomes) -- nomes None = os ids sao de Membro (montar busca os nomes)."""
    tolerancias = {m.id: tolerancia_de(m) for m in ministerios}
    escalas = list(Escala.objects(
        ministerio_id__in=list(tolerancias), data__gte=inicio, data__lte=fim, cancelada__ne=True,
    ).only("id", "ministerio_id", "data", "horario"))
    por_id = {e.id: e for e in escalas}
    funcoes_por_escala = defaultdict(list)
    if por_id:
        for f in Funcao.objects(escala_id__in=list(por_id), membro_id__ne=None, tipo__ne=TIPO_SUBCABECALHO).only(
            "escala_id", "nome", "membro_id", "status", "checkin_em",
        ):
            funcoes_por_escala[f.escala_id].append(f)

    registros, sem_registro = [], 0
    for escala_id, funcoes in funcoes_por_escala.items():
        if not any(f.status == "presente" or f.checkin_em for f in funcoes):
            sem_registro += 1
            continue
        escala = por_id[escala_id]
        for f in funcoes:
            registros.append(Registro(
                escala_id=escala_id, data=escala.data, ministerio_id=escala.ministerio_id,
                funcao_nome=f.nome, membro_id=f.membro_id,
                compareceu=f.status == "presente" or bool(f.checkin_em),
                checkin=bool(f.checkin_em), minutos=_minutos_de_chegada(escala, f.checkin_em),
                tolerancia=tolerancias[escala.ministerio_id],
            ))
    return registros, sem_registro, list(por_id), None


def coletar_ensaios(ministerios, inicio, fim):
    """Mesmo formato de coletar(), para os ensaios: quem esta escalado na
    escala do ensaio e esperado nele; comparecimento = check-in no ensaio.
    Ensaio sem nenhum check-in fica "sem registro" (check-in desligado ou
    ninguem usou). `escala_id` do Registro guarda o id do ENSAIO."""
    tolerancias = {m.id: tolerancia_de(m) for m in ministerios}
    escalas = {e.id: e for e in Escala.objects(ministerio_id__in=list(tolerancias), cancelada__ne=True).only("id", "ministerio_id")}
    ensaios = list(Ensaio.objects(
        escala_id__in=list(escalas), data__gte=inicio, data__lte=fim, cancelado__ne=True,
    ).only("id", "escala_id", "data", "horario")) if escalas else []
    if not ensaios:
        return [], 0, [], None
    ids_escala = list({en.escala_id for en in ensaios})
    funcoes_por_escala = defaultdict(list)
    for f in Funcao.objects(escala_id__in=ids_escala, membro_id__ne=None, tipo__ne=TIPO_SUBCABECALHO).only("escala_id", "nome", "membro_id"):
        funcoes_por_escala[f.escala_id].append(f)
    presencas = {}
    for p in PresencaEnsaio.objects(ensaio_id__in=[en.id for en in ensaios]).only("ensaio_id", "membro_id", "checkin_em"):
        presencas[(p.ensaio_id, p.membro_id)] = p.checkin_em

    registros, sem_registro = [], 0
    for ensaio in ensaios:
        funcoes = funcoes_por_escala.get(ensaio.escala_id, [])
        if not funcoes:
            continue
        if not any((ensaio.id, f.membro_id) in presencas for f in funcoes):
            sem_registro += 1
            continue
        ministerio_id = escalas[ensaio.escala_id].ministerio_id
        for f in funcoes:
            checkin_em = presencas.get((ensaio.id, f.membro_id))
            registros.append(Registro(
                escala_id=ensaio.id, data=ensaio.data, ministerio_id=ministerio_id,
                funcao_nome=f.nome, membro_id=f.membro_id, compareceu=checkin_em is not None,
                checkin=checkin_em is not None, minutos=_minutos_de_chegada(ensaio, checkin_em),
                tolerancia=tolerancias[ministerio_id],
            ))
    return registros, sem_registro, [], None


def coletar_cultos(ministerios, inicio, fim):
    """Mesmo formato de coletar(), para o check-in de culto: cada dia de
    culto (Ministerio.dias_culto) e uma ocorrencia; esperados = contas com
    papel no ministerio + quem fez check-in nele. Dia sem nenhum check-in
    fica "sem registro". `membro_id` do Registro guarda o id da CONTA (User)."""
    from app.auth.models import User
    from app.ministerio.models import UsuarioMinisterio

    ativos = [m for m in ministerios if m.dias_culto_efetivos]
    if not ativos:
        return [], 0, [], {}
    ids = [m.id for m in ativos]
    presencas = {
        (p.ministerio_id, p.data, p.usuario_id): p.checkin_em
        for p in PresencaCulto.objects(ministerio_id__in=ids, data__gte=inicio, data__lte=fim)
    }
    esperados = defaultdict(set)
    for um in UsuarioMinisterio.objects(ministerio_id__in=ids).only("ministerio_id", "usuario_id"):
        esperados[um.ministerio_id].add(um.usuario_id)
    for ministerio_id, _, usuario_id in presencas:
        esperados[ministerio_id].add(usuario_id)

    registros, sem_registro = [], 0
    for m in ativos:
        dias, tolerancia, dia = set(m.dias_culto_efetivos), tolerancia_de(m), inicio
        while dia <= fim:
            if dia.weekday() in dias and esperados[m.id]:
                if not any((m.id, dia, u) in presencas for u in esperados[m.id]):
                    sem_registro += 1
                else:
                    culto = SimpleNamespace(data=dia, horario=m.culto_horario)
                    for usuario_id in esperados[m.id]:
                        checkin_em = presencas.get((m.id, dia, usuario_id))
                        registros.append(Registro(
                            escala_id=(m.id, dia), data=dia, ministerio_id=m.id, funcao_nome=m.nome,
                            membro_id=usuario_id, compareceu=checkin_em is not None, checkin=checkin_em is not None,
                            minutos=_minutos_de_chegada(culto, checkin_em), tolerancia=tolerancia,
                        ))
            dia += timedelta(days=1)
    contas = {u for grupo in esperados.values() for u in grupo}
    nomes = {u.id: u.name or u.username or u.email for u in User.objects(id__in=list(contas))}
    return registros, sem_registro, [], nomes


def tipos_ligados(ministerios):
    """Visoes que a tela mostra: as dos tipos de check-in ligados em algum
    dos ministerios (nenhum ligado = so Escalas, presenca marcada a mao)."""
    from app.escala.checkin import checkin_padrao

    ligados = [t for t, tipo_checkin in _TIPO_DO_CHECKIN.items()
               if any(checkin_padrao(m, tipo_checkin) for m in ministerios)]
    return ligados or ["escalas"]


def _taxa(presencas, total):
    return round(100 * presencas / total) if total else None


def _media(valores):
    return round(sum(valores) / len(valores)) if valores else None


def _faixa(registro):
    if registro.minutos < 0:
        return "adiantado"
    return "no_horario" if registro.minutos <= registro.tolerancia else "atrasado"


def _inicio_do_balde(dia, mensal):
    return dia.replace(day=1) if mensal else dia - timedelta(days=dia.weekday())


def _serie(registros, inicio, fim, mensal):
    baldes = {}
    dia = _inicio_do_balde(inicio, mensal)
    while dia <= fim:
        baldes[dia] = [0, 0, 0]  # escalados, presentes, check-ins
        dia = (dia.replace(day=28) + timedelta(days=4)).replace(day=1) if mensal else dia + timedelta(days=7)
    for r in registros:
        balde = baldes[_inicio_do_balde(r.data, mensal)]
        balde[0] += 1
        balde[1] += r.compareceu
        balde[2] += r.checkin
    rotulo = (lambda d: f"{_MESES[d.month - 1]}/{d:%y}") if mensal else (lambda d: d.strftime("%d/%m"))
    return {
        "rotulos": [rotulo(d) for d in baldes],
        # Periodo sem nenhum evento contado fica vazio no grafico (None), nao
        # 0 -- senao a semana atual, ainda sem culto/escala encerrada, parecia
        # uma queda de comparecimento.
        "escalados": [b[0] or None for b in baldes.values()],
        "presentes": [b[1] if b[0] else None for b in baldes.values()],
        "checkins": [b[2] if b[0] else None for b in baldes.values()],
        "taxa": [_taxa(b[1], b[0]) for b in baldes.values()],
    }


def _sequencia_de_faltas(registros_da_pessoa):
    """Faltas seguidas mais recentes (por escala) e a escala onde ela comecou."""
    por_escala = {}
    for r in registros_da_pessoa:
        atual = por_escala.get(r.escala_id)
        por_escala[r.escala_id] = (r.data, r.compareceu or (atual[1] if atual else False))
    seguidas, inicio = 0, None
    for escala_id, (_, compareceu) in sorted(por_escala.items(), key=lambda item: (item[1][0], item[0]), reverse=True):
        if compareceu:
            break
        seguidas, inicio = seguidas + 1, escala_id
    return seguidas, inicio


def montar(ministerios, periodo, tipo="escalas"):
    """Tudo o que a tela mostra, ja calculado. tipo: "escalas" ou "ensaios"
    (separados de proposito -- trocas e alerta de faltas so valem pra escalas)."""
    dias = PERIODOS[periodo][1]
    fim = hoje_brasilia() - timedelta(days=1)
    inicio = fim - timedelta(days=dias - 1)
    coletor = {"ensaios": coletar_ensaios, "cultos": coletar_cultos}.get(tipo, coletar)
    registros, sem_registro, ids_escalas, nomes = coletor(ministerios, inicio, fim)

    presencas = sum(r.compareceu for r in registros)
    com_horario = [r for r in registros if r.minutos is not None]
    faixas = {"adiantado": [], "no_horario": [], "atrasado": []}
    for r in com_horario:
        faixas[_faixa(r)].append(r.minutos)

    trocas = defaultdict(int)
    if ids_escalas:
        for t in RegistroTroca.objects(escala_id__in=ids_escalas).only("membro_id"):
            trocas[t.membro_id] += 1

    por_pessoa = defaultdict(list)
    for r in registros:
        por_pessoa[r.membro_id].append(r)
    if nomes is None:
        nomes = {m.id: m.nome for m in Membro.objects(id__in=list(set(por_pessoa) | set(trocas))).only("nome")}
    alerta = min((alerta_de(m) for m in ministerios if alerta_de(m)), default=0) if tipo == "escalas" else 0
    pessoas = []
    for membro_id in set(por_pessoa) | set(trocas):
        dele = por_pessoa.get(membro_id, [])
        chegadas = [r.minutos for r in dele if r.minutos is not None]
        faltas = sum(not r.compareceu for r in dele)
        seguidas, _ = _sequencia_de_faltas(dele)
        pessoas.append({
            "nome": nomes.get(membro_id, "Pessoa removida"),
            "escalas": len(dele),
            "presencas": len(dele) - faltas,
            "checkins": sum(r.checkin for r in dele),
            "faltas": faltas,
            "taxa": _taxa(len(dele) - faltas, len(dele)),
            "chegada_media": _media(chegadas),
            "atrasos": sum(1 for r in dele if r.minutos is not None and _faixa(r) == "atrasado"),
            "trocas": trocas.get(membro_id, 0),
            "faltas_seguidas": seguidas,
            "em_alerta": bool(alerta) and seguidas >= alerta,
        })
    pessoas.sort(key=lambda p: (-(p["taxa"] if p["taxa"] is not None else -1), -p["escalas"], p["nome"]))

    ranking = [p for p in pessoas if p["escalas"] >= MINIMO_ESCALAS_RANKING][:5]

    funcoes = defaultdict(lambda: [0, 0])
    semana = [[0, 0] for _ in range(7)]
    for r in registros:
        funcoes[r.funcao_nome][0] += 1
        funcoes[r.funcao_nome][1] += r.compareceu
        semana[r.data.weekday()][0] += 1
        semana[r.data.weekday()][1] += r.compareceu
    por_funcao = sorted(
        ({"nome": nome, "escalados": t, "presencas": p, "faltas": t - p, "taxa": _taxa(p, t)} for nome, (t, p) in funcoes.items()),
        key=lambda f: (f["taxa"], -f["escalados"]),
    )
    por_dia = [
        {"dia": DIAS_SEMANA[i], "escalados": t, "faltas": t - p, "taxa": _taxa(p, t)}
        for i, (t, p) in enumerate(semana) if t
    ]

    return {
        "inicio": inicio,
        "fim": fim,
        "kpis": {
            "escalas": len({r.escala_id for r in registros}),
            "sem_registro": sem_registro,
            "escalados": len(registros),
            "presencas": presencas,
            "checkins": sum(r.checkin for r in registros),
            "faltas": len(registros) - presencas,
            "taxa": _taxa(presencas, len(registros)),
            "trocas": sum(trocas.values()),
        },
        "serie": _serie(registros, inicio, fim, mensal=dias > 91),
        "pontualidade": {
            "media": _media([r.minutos for r in com_horario]),
            "total": len(com_horario),
            "faixas": {
                chave: {"quantidade": len(v), "percentual": _taxa(len(v), len(com_horario)), "media": _media(v)}
                for chave, v in faixas.items()
            },
        },
        "pessoas": pessoas,
        "ranking": ranking,
        "por_funcao": por_funcao,
        "por_dia": por_dia,
        "alerta": alerta,
        "tipo": tipo,
    }


def verificar_faltas_seguidas():
    """Avisa (sino) os lideres quando alguem chega a N faltas seguidas no
    ministerio -- uma vez por sequencia. Chamado pelo agendador; so olha
    ministerios que tiveram escala nos ultimos 2 dias."""
    from app.ministerio.models import Ministerio
    from app.ministerio.routes import _lideres_do_ministerio
    from app.notificacoes import Notificacao

    fim = hoje_brasilia() - timedelta(days=1)
    recentes = Escala.objects(data__gte=fim - timedelta(days=1), data__lte=fim, cancelada__ne=True).distinct("ministerio_id")
    for ministerio in Ministerio.objects(id__in=recentes):
        limite = alerta_de(ministerio)
        if not limite:
            continue
        registros, _, _, _ = coletar([ministerio], fim - timedelta(days=180), fim)
        por_pessoa = defaultdict(list)
        for r in registros:
            por_pessoa[r.membro_id].append(r)
        for membro_id, dele in por_pessoa.items():
            seguidas, escala_inicio_id = _sequencia_de_faltas(dele)
            if seguidas < limite:
                continue
            if AlertaFaltas.objects(ministerio_id=ministerio.id, membro_id=membro_id, escala_inicio_id=escala_inicio_id).first():
                continue
            AlertaFaltas(ministerio_id=ministerio.id, membro_id=membro_id, escala_inicio_id=escala_inicio_id).save()
            membro = Membro.objects(id=membro_id).first()
            nome = membro.nome if membro else "Uma pessoa"
            titulo = f"{nome}: {seguidas} faltas seguidas"[:120]
            mensagem = (f"{nome} faltou às últimas {seguidas} escalas de {ministerio.nome}. "
                        "Veja em Estatísticas de comparecimento.")
            for lider in _lideres_do_ministerio(ministerio):
                Notificacao(usuario_id=lider.id, titulo=titulo, mensagem=mensagem, tipo="faltas_seguidas").save()


def tela_estatisticas(ministerios, titulo, voltar_url, url_tela, url_ajustes=None):
    """Filtros ?periodo=, ?tipo= (so os tipos ligados) e, na Comunidade,
    ?ministerio=. Os ajustes (tolerancia, alerta) ficam na secao "Check-in"
    da tela do ministerio -- `url_ajustes` leva ate la."""
    from flask import render_template, request

    periodo = request.args.get("periodo")
    if periodo not in PERIODOS:
        periodo = PERIODO_PADRAO
    selecionado = None
    if len(ministerios) > 1:
        selecionado = next((m for m in ministerios if str(m.id) == request.args.get("ministerio")), None)
    alvo = [selecionado] if selecionado else ministerios
    visiveis = tipos_ligados(alvo) if alvo else ["escalas"]
    tipo = request.args.get("tipo")
    if tipo not in visiveis:
        tipo = visiveis[0]

    return render_template(
        "escala/estatisticas.html",
        titulo=titulo,
        voltar_url=voltar_url,
        url_tela=url_tela,
        url_ajustes=url_ajustes,
        dados=montar(alvo, periodo, tipo) if alvo else None,
        periodo=periodo,
        tipo=tipo,
        tipos={chave: TIPOS[chave] for chave in visiveis},
        periodos=PERIODOS,
        ministerios=ministerios if len(ministerios) > 1 else [],
        selecionado=selecionado,
        tolerancias=sorted({tolerancia_de(m) for m in alvo}),
    )
