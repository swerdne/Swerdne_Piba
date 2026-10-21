"""Filtro "Ver dias de..." dos calendarios (ministerio e comunidade):
escolher uma pessoa do diretorio e destacar os dias do mes em que ela esta
escalada (e os ensaios dessas escalas), com um resumo embaixo da grade.

Escolha vem em ?pessoa=<membro_id> (os links de mes anterior/proximo levam
junto). So pessoas do diretorio da propria comunidade -- id de outra
comunidade e ignorado. Quem ve o calendario ja ve quem esta em cada escala
(no preview), entao o filtro nao revela nada novo.
"""
from flask import request
from flask_login import current_user

from app.escala.models import STATUS_LABELS, TIPO_FUNCAO, Funcao, diretorio_da_comunidade


def filtro_pessoa_do_calendario(comunidade_id, escalas_do_mes, ensaios_por_dia):
    """Dados pro template: opcoes do seletor (escalados no mes primeiro), a
    pessoa escolhida, os dias/escalas dela e o resumo do mes. 1 consulta
    (as funcoes do mes); o diretorio ja vem em cache por requisicao."""
    diretorio = diretorio_da_comunidade(comunidade_id)
    por_id = {m.id: m for m in diretorio}
    escalas_por_id = {e.id: e for e in escalas_do_mes}

    funcoes = list(Funcao.objects(escala_id__in=list(escalas_por_id), membro_id__ne=None, tipo=TIPO_FUNCAO)
                   .only("escala_id", "membro_id", "nome", "status")) if escalas_por_id else []
    escalados_no_mes = {f.membro_id for f in funcoes if f.membro_id in por_id}

    opcoes_mes = [m for m in diretorio if m.id in escalados_no_mes]
    opcoes_outras = [m for m in diretorio if m.id not in escalados_no_mes]

    email = (getattr(current_user, "email", "") or "").strip().lower()
    eu = next((m for m in diretorio if email and (m.email or "").strip().lower() == email), None)

    pessoa = por_id.get(request.args.get("pessoa", type=int) or 0)
    dados = {
        "filtro_opcoes_mes": opcoes_mes,
        "filtro_opcoes_outras": opcoes_outras,
        "filtro_eu_id": eu.id if eu else None,
        "filtro_pessoa": pessoa,
        "filtro_dias": set(),
        "filtro_dias_ensaio": set(),
        "filtro_escalas": set(),
        "filtro_resumo": [],
    }
    if pessoa is None:
        return dados

    funcoes_da_pessoa = {}
    for f in funcoes:
        if f.membro_id == pessoa.id:
            funcoes_da_pessoa.setdefault(f.escala_id, []).append(f)
    dados["filtro_escalas"] = set(funcoes_da_pessoa)
    dados["filtro_dias"] = {escalas_por_id[i].data for i in funcoes_da_pessoa}
    # Ensaio de uma escala dela (mesmo que a escala seja em outro mes ja vem
    # em ensaios_por_dia) -- destaque mais leve.
    ids_ensaio = {e.id for dia in ensaios_por_dia.values() for _, e, _ in dia}
    if ids_ensaio:
        com_ela = {f.escala_id for f in Funcao.objects(escala_id__in=list(ids_ensaio), membro_id=pessoa.id)
                   .only("escala_id")}
        dados["filtro_dias_ensaio"] = {dia for dia, itens in ensaios_por_dia.items()
                                       if any(e.id in com_ela for _, e, _ in itens)}
        dados["filtro_escalas"] |= com_ela

    resumo = []
    for escala_id, lista in funcoes_da_pessoa.items():
        escala = escalas_por_id[escala_id]
        status = {f.status for f in lista}
        resumo.append({
            "escala": escala,
            "funcoes": ", ".join(f.nome for f in lista),
            "status": STATUS_LABELS.get(next(iter(status)), "") if len(status) == 1 else "Vários",
            "status_chave": next(iter(status)) if len(status) == 1 else "",
        })
    resumo.sort(key=lambda r: (r["escala"].data, r["escala"].horario or ""))
    dados["filtro_resumo"] = resumo
    return dados
