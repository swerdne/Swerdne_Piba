"""Pra quem vai um repertorio compartilhado: um MINISTERIO inteiro ou so
quem serve numa FUNCAO dele (ex: "Teclado", "Projecao").

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


def _pessoas_por_funcao(ministerio):
    """({chave: {"nome": exibicao, "usuarios": {ids}}}, {ids de quem ja foi escalado})."""
    ids_escalas = [e.id for e in Escala.objects(ministerio_id=ministerio.id).only("id")]
    if not ids_escalas:
        return {}, set()
    funcoes = list(
        Funcao.objects(escala_id__in=ids_escalas, membro_id__ne=None, tipo__ne=TIPO_SUBCABECALHO).only("nome", "membro_id")
    )
    membros = {m.id: (m.email or "").strip().lower()
               for m in Membro.objects(id__in=list({f.membro_id for f in funcoes})).only("id", "email")}
    emails = {e for e in membros.values() if e}
    conta_por_email = {u.email.lower(): u.id for u in User.objects(email__in=list(emails)).only("id", "email")} if emails else {}

    por_funcao, escalados = {}, set()
    for funcao in funcoes:
        usuario_id = conta_por_email.get(membros.get(funcao.membro_id, ""))
        grupo = por_funcao.setdefault(_chave(funcao.nome), {"nome": funcao.nome.strip(), "usuarios": set()})
        if usuario_id:
            grupo["usuarios"].add(usuario_id)
            escalados.add(usuario_id)
    return por_funcao, escalados


def _pessoas_do_ministerio(ministerio, escalados):
    com_papel = {u.usuario_id for u in UsuarioMinisterio.objects(ministerio_id=ministerio.id).only("usuario_id")}
    return com_papel | escalados


def opcoes_de_envio(comunidade_id, quem_envia_id):
    """Dados pro formulario de envio: [{id, nome, pessoas, funcoes: [{nome,
    pessoas}]}] de cada ministerio da comunidade (contagens sem quem envia)."""
    opcoes = []
    for ministerio in Ministerio.objects(comunidade_id=comunidade_id).order_by("nome"):
        por_funcao, escalados = _pessoas_por_funcao(ministerio)
        todos = _pessoas_do_ministerio(ministerio, escalados) - {quem_envia_id}
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
