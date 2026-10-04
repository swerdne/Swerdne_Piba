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
"""
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from app.escala.models import TIPO_SUBCABECALHO, AlertaFaltas, Ensaio, Escala, Funcao, Membro, PresencaEnsaio, RegistroTroca

PERIODOS = {
    "30d": ("Últimos 30 dias", 30),
    "3m": ("3 meses", 91),
    "6m": ("6 meses", 182),
    "1a": ("1 ano", 365),
}
PERIODO_PADRAO = "3m"
TIPOS = {"escalas": "Escalas", "ensaios": "Ensaios"}
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
    escala_id: int
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
    """(registros, escalas_sem_registro, ids de todas as escalas do periodo)."""
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
    return registros, sem_registro, list(por_id)


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
        return [], 0, []
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
    return registros, sem_registro, []


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
        "escalados": [b[0] for b in baldes.values()],
        "presentes": [b[1] for b in baldes.values()],
        "checkins": [b[2] for b in baldes.values()],
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
    coletor = coletar_ensaios if tipo == "ensaios" else coletar
    registros, sem_registro, ids_escalas = coletor(ministerios, inicio, fim)

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
    nomes = {m.id: m.nome for m in Membro.objects(id__in=list(set(por_pessoa) | set(trocas))).only("nome")}
    alerta = 0 if tipo == "ensaios" else min((alerta_de(m) for m in ministerios if alerta_de(m)), default=0)
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
        registros, _, _ = coletar([ministerio], fim - timedelta(days=180), fim)
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


def tela_estatisticas(ministerios, titulo, voltar_url, url_tela, ministerio_config=None):
    """GET mostra a tela (filtros ?periodo= e, na Comunidade, ?ministerio=);
    POST salva tolerancia/alerta de `ministerio_config` (so na tela do Ministerio)."""
    from flask import flash, redirect, render_template, request

    from app.escala.forms import ConfigEstatisticasForm

    form = None
    if ministerio_config is not None:
        form = ConfigEstatisticasForm()
        if request.method == "POST":
            if form.validate_on_submit():
                ministerio_config.tolerancia_atraso_min = form.tolerancia_atraso_min.data
                ministerio_config.alerta_faltas_seguidas = form.alerta_faltas_seguidas.data
                ministerio_config.save()
                flash("Ajustes das estatísticas salvos.", "success")
                return redirect(url_tela(periodo=request.args.get("periodo")) + "#ajustes")
        else:
            form.tolerancia_atraso_min.data = tolerancia_de(ministerio_config)
            form.alerta_faltas_seguidas.data = alerta_de(ministerio_config)

    periodo = request.args.get("periodo")
    if periodo not in PERIODOS:
        periodo = PERIODO_PADRAO
    selecionado = None
    if ministerio_config is None and len(ministerios) > 1:
        selecionado = next((m for m in ministerios if str(m.id) == request.args.get("ministerio")), None)
    alvo = [selecionado] if selecionado else ministerios
    tipo = request.args.get("tipo")
    if tipo not in TIPOS:
        tipo = "escalas"

    return render_template(
        "escala/estatisticas.html",
        titulo=titulo,
        voltar_url=voltar_url,
        url_tela=url_tela,
        dados=montar(alvo, periodo, tipo) if alvo else None,
        periodo=periodo,
        tipo=tipo,
        tipos=TIPOS,
        periodos=PERIODOS,
        ministerios=ministerios if ministerio_config is None and len(ministerios) > 1 else [],
        selecionado=selecionado,
        tolerancias=sorted({tolerancia_de(m) for m in alvo}),
        form=form,
    )
