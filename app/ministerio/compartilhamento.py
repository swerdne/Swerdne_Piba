"""Pra quem vai um repertorio compartilhado: um ou VARIOS alvos de uma vez,
cada alvo sendo um MINISTERIO inteiro ou so quem serve numa FUNCAO dele (ex:
"Teclado", "Projecao") -- ex: todo o Kids + Teclado e Projecao do Louvor.
Quem cai em mais de um alvo recebe uma vez so.

So contas (User) recebem -- o repertorio aparece na tela inicial delas.
- Ministerio inteiro: quem tem papel nele (UsuarioMinisterio, lider ou
  membro) + quem ja foi escalado em alguma escala dele (Membro do
  diretorio com o mesmo e-mail de uma conta).
- Funcao: quem ja foi escalado nessa funcao (mesmo nome, sem diferenciar
  maiuscula/acento) em escalas do ministerio.
Quem envia nunca entra na propria lista.
"""
from app.auth.models import User
from app.escala.models import Escala, Funcao, Membro, TIPO_SUBCABECALHO
from app.escala.temas import _sem_acento
from app.ministerio.models import Ministerio, UsuarioMinisterio


def _chave(nome):
    return " ".join(_sem_acento(nome).split())


def _pessoas_por_funcao_de_varios(ids_ministerios):
    """{ministerio_id: ({chave: {"nome", "usuarios": {ids}}}, {ids ja escalados})}
    de varios ministerios de uma vez -- poucas consultas no total, nao
    algumas por ministerio (a tela de escala/banco/repertorio monta o
    formulario de envio com todos os ministerios da comunidade)."""
    resultado = {mid: ({}, set()) for mid in ids_ministerios}
    ministerio_da_escala = {
        e.id: e.ministerio_id for e in Escala.objects(ministerio_id__in=list(ids_ministerios)).only("id", "ministerio_id")
    }
    if not ministerio_da_escala:
        return resultado
    funcoes = list(
        Funcao.objects(escala_id__in=list(ministerio_da_escala), membro_id__ne=None, tipo__ne=TIPO_SUBCABECALHO)
        .only("nome", "membro_id", "escala_id")
    )
    membros = {m.id: (m.email or "").strip().lower()
               for m in Membro.objects(id__in=list({f.membro_id for f in funcoes})).only("id", "email")}
    emails = {e for e in membros.values() if e}
    conta_por_email = {u.email.lower(): u.id for u in User.objects(email__in=list(emails)).only("id", "email")} if emails else {}

    for funcao in funcoes:
        por_funcao, escalados = resultado[ministerio_da_escala[funcao.escala_id]]
        usuario_id = conta_por_email.get(membros.get(funcao.membro_id, ""))
        grupo = por_funcao.setdefault(_chave(funcao.nome), {"nome": funcao.nome.strip(), "usuarios": set()})
        if usuario_id:
            grupo["usuarios"].add(usuario_id)
            escalados.add(usuario_id)
    return resultado


def _pessoas_por_funcao(ministerio):
    """({chave: {"nome": exibicao, "usuarios": {ids}}}, {ids de quem ja foi escalado})."""
    return _pessoas_por_funcao_de_varios([ministerio.id])[ministerio.id]


def _papeis_de_varios(ids_ministerios):
    com_papel = {mid: set() for mid in ids_ministerios}
    for u in UsuarioMinisterio.objects(ministerio_id__in=list(ids_ministerios)).only("ministerio_id", "usuario_id"):
        com_papel[u.ministerio_id].add(u.usuario_id)
    return com_papel


def _pessoas_do_ministerio(ministerio, escalados):
    return _papeis_de_varios([ministerio.id])[ministerio.id] | escalados


def opcoes_de_envio(comunidade_id, quem_envia_id):
    """Dados pro formulario de envio: [{id, nome, pessoas, funcoes: [{nome,
    pessoas}]}] de cada ministerio da comunidade (contagens sem quem envia)."""
    ministerios = list(Ministerio.objects(comunidade_id=comunidade_id).only("id", "nome").order_by("nome"))
    ids = [m.id for m in ministerios]
    pessoas = _pessoas_por_funcao_de_varios(ids)
    papeis = _papeis_de_varios(ids)
    opcoes = []
    for ministerio in ministerios:
        por_funcao, escalados = pessoas[ministerio.id]
        todos = (papeis[ministerio.id] | escalados) - {quem_envia_id}
        funcoes = sorted(
            ({"nome": g["nome"], "pessoas": len(g["usuarios"] - {quem_envia_id})} for g in por_funcao.values()),
            key=lambda f: _chave(f["nome"]),
        )
        opcoes.append({"id": ministerio.id, "nome": ministerio.nome, "pessoas": len(todos), "funcoes": funcoes})
    return opcoes


def destinatarios(ministerio, funcao, quem_envia_id):
    """Contas que recebem (funcao vazia = ministerio inteiro), sem quem envia."""
    por_funcao, escalados = _pessoas_por_funcao(ministerio)
    if (funcao or "").strip():
        grupo = por_funcao.get(_chave(funcao))
        ids = set(grupo["usuarios"]) if grupo else set()
    else:
        ids = _pessoas_do_ministerio(ministerio, escalados)
    ids.discard(quem_envia_id)
    return list(User.objects(id__in=list(ids))) if ids else []


def descricao_do_envio(ministerio, funcao):
    funcao = (funcao or "").strip()
    return f"{ministerio.nome} · {funcao}" if funcao else f"{ministerio.nome} (todo o ministerio)"


def ler_alvos(valores, comunidade_id):
    """Valores "ministerio_id|funcao" marcados no formulario (funcao vazia =
    ministerio inteiro) -> [(ministerio, funcao)] so de ministerios da
    comunidade, sem repetir. Funcao de um ministerio ja marcado inteiro e
    redundante e sai."""
    pedidos = []
    for valor in valores:
        id_txt, _, funcao = (valor or "").partition("|")
        if id_txt.isdigit():
            pedidos.append((int(id_txt), " ".join(funcao.split())[:80]))
    ministerios = {m.id: m for m in Ministerio.objects(id__in=list({i for i, _ in pedidos}), comunidade_id=comunidade_id)}
    inteiros = {i for i, f in pedidos if not f}
    alvos, vistos = [], set()
    for ministerio_id, funcao in pedidos:
        chave = (ministerio_id, _chave(funcao))
        if ministerio_id not in ministerios or chave in vistos or (funcao and ministerio_id in inteiros):
            continue
        vistos.add(chave)
        alvos.append((ministerios[ministerio_id], funcao))
    return alvos


def destinatarios_de_varios(alvos, quem_envia_id):
    """Uniao das contas de todos os alvos (cada pessoa uma vez so)."""
    por_id = {}
    for ministerio, funcao in alvos:
        for pessoa in destinatarios(ministerio, funcao, quem_envia_id):
            por_id.setdefault(pessoa.id, pessoa)
    return list(por_id.values())


def descricao_de_varios(alvos):
    return ", ".join(descricao_do_envio(m, f) for m, f in alvos)
