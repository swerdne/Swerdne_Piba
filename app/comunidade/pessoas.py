"""Tela "Pessoas" (comunidade.membros e ministerio.papeis): junta numa lista
so o diretorio de escalacao (Membro, pode nao ter conta) e as contas com
papel (UsuarioComunidade/UsuarioMinisterio), casando os dois pelo e-mail --
antes eram telas separadas (Membros x Papeis e convites) mostrando as mesmas
pessoas duas vezes.
"""
from app.auth.models import User


def chave_email(email):
    return (email or "").strip().lower()


def pre_carregar_usuarios(linhas):
    """Preenche `linha.usuario` de todas as linhas de papel com 1 consulta
    (sem isso cada linha da tela era uma ida ao banco). Usa o mesmo cache da
    property (db_utils.relacao_em_cache)."""
    ids = list({linha.usuario_id for linha in linhas})
    usuarios = {u.id: u for u in User.objects(id__in=ids)} if ids else {}
    for linha in linhas:
        setattr(linha, "_cache_usuario", (linha.usuario_id, usuarios.get(linha.usuario_id)))
    return linhas


def nome_da_conta(usuario):
    return usuario.name or usuario.username or usuario.email


def _item(nome, email, membro, conta, convite):
    categorias = []
    if conta is not None and conta.papel in ("admin", "lider"):
        categorias.append("admin")
    if conta is None:
        categorias.append("sem-acesso")
    if membro is None:
        categorias.append("fora-diretorio")
    return {
        "nome": nome,
        "email": email or "",
        "membro": membro,
        "conta": conta,
        "convite": convite,
        "categorias": " ".join(categorias),
    }


def lista_de_pessoas(diretorio, contas, convites=(), ignorar_contas=()):
    """Uma linha por pessoa: Membro do diretorio (com a conta de mesmo e-mail,
    se houver) + contas que nao estao no diretorio. `ignorar_contas` = ids de
    contas ja mostradas em outro lugar (ex: "Aguardando entrar no diretorio").
    Ordem alfabetica."""
    contas_por_email = {
        chave_email(c.usuario.email): c for c in contas if c.usuario is not None and c.usuario.email
    }
    convites_por_email = {chave_email(c.email): c for c in convites}
    itens, usadas = [], set()
    for membro in diretorio:
        chave = chave_email(membro.email)
        conta = contas_por_email.get(chave) if chave else None
        if conta is not None:
            usadas.add(conta.id)
        convite = convites_por_email.get(chave) if chave and conta is None else None
        itens.append(_item(membro.nome, membro.email, membro, conta, convite))
    for conta in contas:
        if conta.id in usadas or conta.id in ignorar_contas or conta.usuario is None:
            continue
        itens.append(_item(nome_da_conta(conta.usuario), conta.usuario.email, None, conta, None))
    itens.sort(key=lambda item: item["nome"].lower())
    return itens


def garantir_no_diretorio(comunidade_id, email, nome=None):
    """Coloca no diretorio de escalacao da comunidade quem foi adicionado por
    e-mail (Papeis do ministerio) -- sem isso a pessoa tinha papel mas nao
    aparecia pra ser escalada. Nao duplica (casa por e-mail). Devolve o
    Membro e se foi criado agora."""
    from app.escala.models import Membro

    email = (email or "").strip()
    existente = Membro.objects(comunidade_id=comunidade_id, email__iexact=email).first()
    if existente is not None:
        return existente, False
    if not nome:
        usuario = User.objects(email__iexact=email).first()
        nome = nome_da_conta(usuario) if usuario else email.split("@")[0]
    membro = Membro(comunidade_id=comunidade_id, nome=nome[:120], email=email)
    membro.save()
    return membro, True


def contar_categorias(itens):
    """Quantas pessoas em cada filtro da tela (chips Admins/Sem acesso/...)."""
    contagem = {"admin": 0, "sem-acesso": 0, "fora-diretorio": 0}
    for item in itens:
        for categoria in item["categorias"].split():
            contagem[categoria] = contagem.get(categoria, 0) + 1
    return contagem
