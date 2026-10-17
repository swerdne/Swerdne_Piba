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



# --- Busca no banco (palavras-chave, trecho da letra, erro de digitacao) -----
#
# A tela filtra na hora por nome/artista/tom/tags (JS, sem servidor); esta
# busca soma o que so o servidor acha: TRECHO DA LETRA ("Deus fiel"), varias
# palavras ao mesmo tempo (todas precisam aparecer) e erro de digitacao
# ("ressureicao" acha "ressurreicao"). Sem biblioteca externa.

_PALAVRAS_VAZIAS = {"a", "o", "e", "de", "da", "do", "das", "dos", "em", "no", "na", "nos", "nas", "um", "uma",
                    "que", "pra", "para", "por", "com", "se", "ao", "as", "os"}
_ROTULO_LETRA = re.compile(r"^\s*\[[^\]]*\]\s*$")
MAX_RESULTADOS_BUSCA = 60


def _palavras(texto):
    return re.findall(r"[a-z0-9]+", _sem_acento(texto or ""))


def _texto_da_letra(musica):
    """Letra sem acordes: a de projecao ou, sem ela, a cifra sem as linhas de acordes."""
    from app.escala.models import eh_linha_de_acordes

    if musica.letra_projecao:
        bruto = musica.letra_projecao
    else:
        bruto = "\n".join(l for l in (musica.cifra_louvor or "").split("\n") if not eh_linha_de_acordes(l))
    return "\n".join(l for l in bruto.split("\n") if not _ROTULO_LETRA.match(l))


def _distancia_ate(a, b, limite):
    """Distancia de edicao (Levenshtein) entre a e b, parando cedo: devolve
    limite+1 assim que passar do limite (a maioria das comparacoes)."""
    if abs(len(a) - len(b)) > limite:
        return limite + 1
    anterior = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        atual = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            atual[j] = min(anterior[j] + 1, atual[j - 1] + 1, anterior[j - 1] + (ca != cb))
        if min(atual) > limite:
            return limite + 1
        anterior = atual
    return anterior[-1]


def _tolerancia(palavra):
    """Quantos erros aceitar: palavra curta precisa vir certa."""
    return 0 if len(palavra) < 4 else (1 if len(palavra) < 8 else 2)


def buscar_no_banco(musicas, termo):
    """[{"id", "onde"}] das musicas que tem TODAS as palavras do termo (no
    nome/artista/tom/tags ou na letra, exata, comeco de palavra ou com poucos
    erros), da mais relevante pra menos. `onde` = "nome", "tema" ou "letra"
    (pra tela dizer por que apareceu).

    Indice invertido (palavra -> musicas): a comparacao com erro de digitacao
    roda 1 vez por palavra do VOCABULARIO do banco, nao por musica."""
    termos = [p for p in _palavras(termo) if p not in _PALAVRAS_VAZIAS] or _palavras(termo)
    if not termos:
        return []
    frase = " ".join(_palavras(termo))

    pesos = {"nome": 3, "tema": 3, "letra": 1}
    indice = {}  # palavra -> {musica_id: melhor campo}
    letras, nomes = {}, {}
    for musica in musicas:
        nomes[musica.id] = musica.nome or ""
        letra = _palavras(_texto_da_letra(musica))
        letras[musica.id] = " ".join(letra)
        campos = (("nome", _palavras(" ".join([musica.nome or "", musica.artista or "", musica.tom or ""]))),
                  ("tema", _palavras(" ".join(musica.tags or []))), ("letra", letra))
        for campo, palavras in campos:
            for palavra in set(palavras):
                atual = indice.setdefault(palavra, {}).get(musica.id)
                if atual is None or pesos[campo] > pesos[atual]:
                    indice[palavra][musica.id] = campo

    pontos, onde = None, {}
    for palavra in termos:
        limite = _tolerancia(palavra)
        achados = {}  # musica_id -> (pontos, campo)
        for vocab, por_musica in indice.items():
            if vocab == palavra or (len(palavra) >= 3 and vocab.startswith(palavra)):
                fator = 2
            elif limite and _distancia_ate(palavra, vocab, limite) <= limite:
                fator = 1
            else:
                continue
            for musica_id, campo in por_musica.items():
                candidato = (pesos[campo] * fator, campo)
                if candidato > achados.get(musica_id, (0, "")):
                    achados[musica_id] = candidato
        if pontos is None:
            pontos = {m: p for m, (p, _) in achados.items()}
        else:  # todas as palavras precisam aparecer
            pontos = {m: pontos[m] + achados[m][0] for m in pontos if m in achados}
        for musica_id, (_, campo) in achados.items():
            if musica_id in pontos and (musica_id not in onde or onde[musica_id] == "letra"):
                onde[musica_id] = campo
        if not pontos:
            return []

    if len(termos) > 1:
        for musica_id in pontos:
            if frase in letras[musica_id]:
                pontos[musica_id] += 4  # o trecho inteiro, na ordem, na letra
    ordem = sorted(pontos, key=lambda m: (-pontos[m], _sem_acento(nomes[m])))
    return [{"id": m, "onde": onde[m]} for m in ordem[:MAX_RESULTADOS_BUSCA]]
