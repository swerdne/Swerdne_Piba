"""Palavras-chave de TEMA pra musica (amor, cruz, graca...), sugeridas pela
letra -- vao pro campo `Musica.tags`, que a busca do banco de musicas ja
usa (ministerio/repertorio.html). Assim da pra achar "uma musica que fala
de cruz" na hora de montar o repertorio.

So sugestao: na importacao aparece num campo editavel do card; no banco, o
botao "Gerar palavras-chave" so preenche musica SEM tags (nunca mexe no que
alguem escreveu).

Como decide: cada tema tem raizes de palavras (sem acento, comparadas no
INICIO da palavra -- "cruz" pega "cruzes", mas "graca" nao pega
"engracado"). Conta em quantas LINHAS diferentes da letra o tema aparece
(refrao repetido 6x nao infla), +2 se aparece no titulo. Precisa de pelo
menos 2 pontos; ficam os 4 temas mais fortes.
"""
import re
import unicodedata

# tag -> raizes (sem acento, minusculas). Expressao com espaco casa a frase.
TEMAS = {
    "amor": ["amor", "amou", "amad", "amar", "amas", "ama ", "amei", "amo "],
    "cruz": ["cruz", "calvario", "cravo", "crucific", "madeiro", "rude cruz"],
    "sangue": ["sangue", "redenc", "redim", "remid", "resgat", "purific", "lavou", "lava-me", "lava me"],
    "graça": ["graca", "misericord", "favor"],
    "perdão": ["perdo", "perdao", "arrepend", "pecad", "culpa", "transgress"],
    "espírito santo": ["espirito santo", "espirito de deus", "consolador", "uncao", "derrama", "sopro", "vento do espirito"],
    "adoração": ["ador", "prostr", "me curvo", "nos curvamos", "exalt", "de joelhos", "me ajoelho"],
    "louvor": ["louv", "cant", "aleluia", "hosana", "brad", "palmas", "danc", "celebr", "jubilo", "alegr"],
    "fé": ["fe ", "fe,", "fe!", "fe.", "creio", "crer", "cremos", "cre ", "confi", "acredit", "fiel", "fidelidade"],
    "esperança": ["esperanc", "espera", "consol", "nao temer", "nao vou temer", "medo", "temor", "refugio",
                  "abrigo", "descans", "aflic", "tempestade", "deserto", "vale"],
    "cura": ["cura", "curou", "curad", "sara", "restaur", "milagre"],
    "vitória": ["vitori", "venc", "guerr", "batalh", "inimig", "leao", "triunf", "conquist"],
    "ressurreição": ["ressurr", "ressusc", "tumulo", "sepulcr", "vivo esta", "ele vive", "venceu a morte"],
    "natal": ["natal", "manjedoura", "belem", "menino", "nasceu", "emanuel", "pastores", "magos"],
    "ceia": ["ceia", "calice", "pao ", "o pao", "vinho", "corpo partido", "memoria de"],
    "presença": ["presenca", "intimid", "lugar secreto", "teu coracao", "tua face", "habitar", "habita", "perto de ti", "tua casa"],
    "santidade": ["santidad", "santo, santo", "santo santo", "puro", "pureza", "consagr", "separad"],
    "entrega": ["rendo", "rendi", "render", "entreg", "eis-me", "eis me", "me dou", "tudo a ti", "minha vida"],
    "gratidão": ["gratid", "obrigad", "agradec", "gracas"],
    "majestade": ["rei ", "reis", "reina", "trono", "majest", "soberan", "dignid", "digno", "poderoso", "grandeza"],
    "céu": ["ceu", "eterni", "maranata", "noiva", "volta de", "vinda", "nova jerusalem", "glorificad"],
    "missões": ["nacoes", "povos", "evangel", "colheita", "missao", "missoes", "ide e", "anunciar", "proclamar"],
    "paz": ["paz", "calma", "quietude", "sereno"],
    "família": ["familia", "minha casa", "meus filhos", "geracao", "geracoes", "pais e filhos"],
}

PONTOS_MINIMOS = 2
MAX_TAGS = 4


def _sem_acento(texto):
    texto = unicodedata.normalize("NFD", texto or "")
    return "".join(c for c in texto if unicodedata.category(c) != "Mn").lower()


def _padrao(raizes):
    # \b no inicio: raiz casa so no comeco da palavra. Raiz com pontuacao/
    # espaco no fim (ex: "fe,") ja delimita sozinha.
    return re.compile("|".join(r"(?<![a-z])" + re.escape(r) for r in raizes))


_PADROES = {tag: _padrao(raizes) for tag, raizes in TEMAS.items()}


def sugerir_tags(nome="", letra="", cifra=""):
    """Lista de ate MAX_TAGS temas (mais fortes primeiro). Usa a `letra`
    (versao de projecao) e, sem ela, a letra tirada da `cifra`."""
    if not (letra or "").strip() and (cifra or "").strip():
        from app.escala.models import projecao_da_cifra
        letra = projecao_da_cifra(cifra)

    # Espaco no fim de cada linha: raizes como "amo " / "rei " casam no fim da linha tambem.
    linhas = {_sem_acento(l).strip() + " " for l in (letra or "").split("\n")
              if l.strip() and not l.strip().startswith("[")}
    titulo = _sem_acento(nome) + " "

    pontos = {}
    for tag, padrao in _PADROES.items():
        total = sum(1 for linha in linhas if padrao.search(linha))
        if padrao.search(titulo):
            total += 2
        if total >= PONTOS_MINIMOS:
            pontos[tag] = total

    ordenados = sorted(pontos.items(), key=lambda item: (-item[1], list(TEMAS).index(item[0])))
    return [tag for tag, _ in ordenados[:MAX_TAGS]]
