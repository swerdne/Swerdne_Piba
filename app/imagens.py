"""Imagens enviadas pelos usuarios (logo de comunidade/ministerio, foto de
perfil), guardadas no MongoDB e servidas por main.imagem (/imagem/<id>).

Antes ficavam em app/static/uploads/, no disco do Azure App Service -- que
e substituido a cada deploy (o pacote so leva o que esta no git). Toda
atualizacao do site apagava as fotos e o banco ficava apontando pra arquivo
inexistente (icone quebrado). No banco elas sobrevivem aos deploys.
"""
import os
import uuid
from datetime import datetime, timezone

import mongoengine
from flask import url_for

PREFIXO_URL = "/imagem/"
PREFIXO_LEGADO = "/static/uploads/"


class ImagemArmazenada(mongoengine.Document):
    meta = {"collection": "imagens"}

    id = mongoengine.StringField(primary_key=True)
    conteudo = mongoengine.BinaryField(required=True)
    tipo = mongoengine.StringField(required=True, max_length=40)
    criada_em = mongoengine.DateTimeField(default=lambda: datetime.now(timezone.utc))


def _tipo_pelo_conteudo(conteudo, nome_arquivo):
    # Pelo conteudo, nao pela extensao: o validador do form so olha o nome.
    if conteudo.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if conteudo.startswith(b"\xff\xd8"):
        return "image/jpeg"
    extensao = nome_arquivo.rsplit(".", 1)[-1].lower() if "." in nome_arquivo else ""
    return "image/png" if extensao == "png" else "image/jpeg"


def salvar_imagem(arquivo):
    """Grava o arquivo enviado (FileStorage) e devolve a URL publica dele."""
    conteudo = arquivo.read()
    imagem = ImagemArmazenada(
        id=uuid.uuid4().hex,
        conteudo=conteudo,
        tipo=_tipo_pelo_conteudo(conteudo, arquivo.filename or ""),
    )
    imagem.save()
    return url_for("main.imagem", imagem_id=imagem.id)


def remover_imagem(url):
    """Apaga a imagem por tras de uma URL salva (nova ou do disco antigo)."""
    if not url:
        return
    if url.startswith(PREFIXO_URL):
        ImagemArmazenada.objects(id=url[len(PREFIXO_URL):]).delete()
    elif url.startswith(PREFIXO_LEGADO):
        caminho = os.path.join("app", url.lstrip("/"))
        if os.path.isfile(caminho):
            try:
                os.remove(caminho)
            except OSError:
                pass


def legado_perdido(url):
    """True pra um caminho antigo em /static/uploads/ cujo arquivo ja sumiu
    do disco (apagado por um deploy) -- melhor tratar como "sem imagem" e
    mostrar o icone padrao do que um <img> quebrado."""
    return bool(url) and url.startswith(PREFIXO_LEGADO) and not os.path.isfile(
        os.path.join("app", url.lstrip("/"))
    )


def _limpar_legado(campo):
    def handler(sender, document, **kwargs):
        if legado_perdido(getattr(document, campo, None)):
            setattr(document, campo, None)
    return handler


_limpeza_registrada = False


def registrar_limpeza_de_legado():
    """Ao carregar Comunidade/Ministerio/User, zera (so em memoria; persiste
    no proximo save) a referencia a um arquivo antigo que nao existe mais.
    Idempotente: create_app roda varias vezes nos testes."""
    global _limpeza_registrada
    if _limpeza_registrada:
        return
    _limpeza_registrada = True
    from app.auth.models import User
    from app.comunidade.models import Comunidade
    from app.ministerio.models import Ministerio

    for modelo, campo in ((Comunidade, "imagem"), (Ministerio, "imagem"), (User, "foto_perfil")):
        handler = _limpar_legado(campo)
        # weak=False: o handler e uma closure local, sem outra referencia viva.
        mongoengine.signals.post_init.connect(handler, sender=modelo, weak=False)
