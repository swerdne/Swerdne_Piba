"""Bancos de musicas: o OFICIAL da comunidade e o LOCAL de cada ministerio.

- Oficial (Musica.oficial=True, comunidade_id): usado por todos os
  ministerios da comunidade. So o ADMIN da comunidade altera -- inclusive
  aprovando musica de um banco local pra virar oficial.
- Local (Musica.oficial=False, ministerio_id = dono): o LIDER do ministerio
  adiciona/importa/edita a vontade, sem mexer no oficial. Escalas do proprio
  ministerio usam as duas listas (oficial + local).
- Ver: qualquer pessoa da comunidade ve os dois (o admin precisa ver os
  locais pra aprovar).

unificar_banco_da_comunidade migra as musicas antigas (de quando cada
ministerio tinha o proprio banco, so com ministerio_id) pro banco OFICIAL e
junta as repetidas. Roda sozinha na 1a vez que o banco e usado -- sem
comando manual no servidor. Depois vira uma consulta barata que responde
"nada pendente". Musica LOCAL nova ja nasce com comunidade_id, entao nunca
e confundida com antiga.

Juntar repetidas (mesmo nome, ignorando maiuscula/acento/espacos) e
deterministico de proposito: duas requisicoes ao mesmo tempo escolhem a
mesma musica pra ficar. Nada se perde: campo vazio na que fica e preenchido
pela outra, tags e versoes de tom sao somadas, e as escalas que apontavam
pra repetida passam a apontar pra que ficou.
"""
import re

from mongoengine.queryset.visitor import Q

from app.escala.models import ItemRepertorio, Musica, mesmo_tom
from app.escala.temas import _sem_acento

_CAMPOS_TEXTO = ("artista", "tom", "link", "cifra_louvor", "letra_projecao")


def chave_do_nome(nome):
    return re.sub(r"\s+", " ", _sem_acento(nome)).strip()


# --- Qual banco ----------------------------------------------------------------

class Banco:
    """Um banco de musicas: o oficial da `comunidade` (ministerio=None) ou o
    local de um `ministerio`. `pode_editar` ja vem calculado pra conta logada."""

    def __init__(self, comunidade, ministerio=None, pode_editar=False):
        self.comunidade = comunidade
        self.ministerio = ministerio
        self.pode_editar = pode_editar

    @property
    def oficial(self):
        return self.ministerio is None

    @property
    def args(self):
        """Argumentos de url_for pras rotas que valem pros dois bancos."""
        return {"ministerio_id": self.ministerio.id} if self.ministerio else {"comunidade_id": self.comunidade.id}

    @property
    def titulo(self):
        return "Banco de musicas" if self.oficial else f"Banco do {self.ministerio.nome}"

    def musicas(self):
        if self.oficial:
            return musicas_oficiais(self.comunidade.id)
        return Musica.objects(ministerio_id=self.ministerio.id, oficial=False)

    def nova_musica(self, **campos):
        return Musica(
            comunidade_id=self.comunidade.id,
            ministerio_id=self.ministerio.id if self.ministerio else None,
            oficial=self.oficial,
            **campos,
        )


def musicas_oficiais(comunidade_id):
    # `oficial` ausente (musica antiga) conta como oficial.
    return Musica.objects(Q(comunidade_id=comunidade_id) & Q(oficial__ne=False))


def musicas_disponiveis_pra_escala(ministerio):
    """Oficiais da comunidade + locais do proprio ministerio."""
    return Musica.objects(
        Q(comunidade_id=ministerio.comunidade_id)
        & (Q(oficial__ne=False) | Q(oficial=False, ministerio_id=ministerio.id))
    )


def sugestoes_dos_ministerios(comunidade_id):
    """Musicas locais que o admin ainda pode aprovar pro banco oficial."""
    return Musica.objects(comunidade_id=comunidade_id, oficial=False, sugestao_dispensada__ne=True)


# --- Migracao dos bancos antigos ------------------------------------------------

def _peso(musica):
    """Mais conteudo primeiro; empate -> menor id (a mais antiga)."""
    conteudo = (
        bool(musica.cifra_louvor) + bool(musica.letra_projecao)
        + len(musica.versoes_cifra or []) + bool(musica.tom) + bool(musica.artista)
    )
    return (-conteudo, musica.id)


def _juntar(fica, sai):
    for campo in _CAMPOS_TEXTO:
        if not getattr(fica, campo) and getattr(sai, campo):
            setattr(fica, campo, getattr(sai, campo))
    vistas = {_sem_acento(t) for t in fica.tags or []}
    for tag in sai.tags or []:
        if _sem_acento(tag) not in vistas:
            fica.tags.append(tag)
            vistas.add(_sem_acento(tag))
    for versao in sai.versoes_cifra or []:
        ja_tem = (fica.tom and mesmo_tom(versao.tom, fica.tom)) or fica.versao_no_tom(versao.tom)
        if not ja_tem:
            fica.versoes_cifra.append(versao)


def unificar_banco_da_comunidade(comunidade_id):
    """Idempotente. Devolve quantas musicas antigas foram migradas (0 = ja
    estava tudo migrado)."""
    from app.ministerio.models import ministerios_da_comunidade

    ids_ministerios = [m.id for m in ministerios_da_comunidade(comunidade_id)]
    if not ids_ministerios:
        return 0
    pendentes = [m.id for m in Musica.objects(comunidade_id=None, ministerio_id__in=ids_ministerios).only("id")]
    if not pendentes:
        return 0

    Musica.objects(id__in=pendentes).update(set__comunidade_id=comunidade_id, set__oficial=True)

    # So o banco OFICIAL e juntado -- musica local nunca entra aqui.
    grupos = {}
    for musica in musicas_oficiais(comunidade_id):
        grupos.setdefault(chave_do_nome(musica.nome), []).append(musica)

    for repetidas in grupos.values():
        if len(repetidas) < 2:
            continue
        repetidas.sort(key=_peso)
        fica, saem = repetidas[0], repetidas[1:]
        for sai in saem:
            _juntar(fica, sai)
        fica.save()
        ids_saem = [m.id for m in saem]
        ItemRepertorio.objects(musica_id__in=ids_saem).update(set__musica_id=fica.id)
        Musica.objects(id__in=ids_saem).delete()

    return len(pendentes)


# --- Palavras-chave de tema automaticas -----------------------------------------

def preencher_palavras_chave_da_comunidade(comunidade_id):
    """Da as palavras-chave de tema (escala/temas.py) a toda musica da
    comunidade (oficial e local) que ainda nao tem nenhuma -- roda ao abrir o
    banco, uma vez por musica (palavras_chave_verificadas). Nunca mexe em
    tag que alguem escreveu. Devolve quantas ganharam tags."""
    from app.escala.temas import sugerir_tags

    pendentes = list(
        Musica.objects(comunidade_id=comunidade_id, palavras_chave_verificadas__ne=True)
        .only("id", "nome", "tags", "letra_projecao", "cifra_louvor")
    )
    preenchidas = 0
    for musica in pendentes:
        mudancas = {"set__palavras_chave_verificadas": True}
        if not musica.tags:
            tags = sugerir_tags(musica.nome, letra=musica.letra_projecao, cifra=musica.cifra_louvor)
            if tags:
                mudancas["set__tags"] = tags
                preenchidas += 1
        Musica.objects(id=musica.id).update(**mudancas)
    return preenchidas

