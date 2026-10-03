"""Extracao de cifras de PDFs gerados por sites (Cifra Club, Cifras.com.br,
Letras...) via "Imprimir > Salvar como PDF" -- usada pela importacao em
lote do banco de musicas (ministerio.routes.importar_musicas).

So funcoes puras (bytes do PDF -> dict); nada aqui grava no banco. O
resultado e so uma SUGESTAO: a tela de importacao mostra tudo pra pessoa
conferir e corrigir antes de salvar, porque cada site/navegador monta o PDF
um pouco diferente.

O que se espera de um PDF desses (e o que cada parte vira):
- Cabecalho/rodape do navegador em toda pagina: data/hora + titulo da
  pagina ("Nome - Artista - Cifra Club"), link do site, "1/3". O titulo e
  a fonte mais confiavel de nome/artista; o resto e descartado.
- Topo da 1a pagina: nome, artista, "tom: G".
- O resto: a cifra, com os acordes alinhados em cima da letra (fonte
  monoespacada) -- por isso o texto e extraido em modo "layout", que
  preserva os espacos.

PDF escaneado (imagem, sem texto) nao da pra extrair: volta com aviso.
"""
import io
import logging
import re

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.escala.models import eh_linha_de_acordes

# PDF de navegador costuma ter tabela de fontes com linhas "quebradas" que o
# pypdf contorna sozinho, mas avisa no log a cada uma -- ruido puro aqui.
logging.getLogger("pypdf").setLevel(logging.ERROR)

MAX_PAGINAS = 30  # cifra de site tem 1-4 paginas; acima disso nao e uma cifra

_DATA_HORA = re.compile(r"^\s*\d{1,2}/\d{1,2}/\d{2,4},?\s+\d{1,2}:\d{2}(?::\d{2})?(?:\s*[AP]M)?\s*", re.I)
_URL = re.compile(r"https?://|www\.", re.I)
_CONTADOR_PAGINA = re.compile(r"^\s*(?:p[aá]gina|page)?\s*\d+\s*(?:/|de|of)\s*\d+\s*$", re.I)
_TOM = re.compile(r"^\s*tom\s*[:\-]?\s*([A-G][#b]?m?)(?![a-z])", re.I)
_ROTULO = re.compile(r"^\s*\[[^\]]+\]")
_SEPARADOR_TITULO = re.compile(r"\s+[-–—|]\s+")
_PARTE_DE_SITE = re.compile(r"cifra|letra|club|\.com|\.br|songbook|ultimate", re.I)
# Rodapes de conteudo que alguns sites poem depois da cifra.
_LIXO_FINAL = re.compile(
    r"^\s*(?:composi[cç][aã]o|colabora[cç][aã]o|revis[aã]o|enviad[ao] por|ver mais|exibir|"
    r"cifra club|cifras\.com|letras\.mus|aprenda a tocar|vers[aã]o simplificada)",
    re.I,
)


class PdfInvalidoError(Exception):
    """PDF ilegivel, protegido por senha ou grande demais."""


def _texto_do_pdf(dados):
    try:
        leitor = PdfReader(io.BytesIO(dados))
        if leitor.is_encrypted and not leitor.decrypt(""):
            raise PdfInvalidoError("PDF protegido por senha.")
        paginas = leitor.pages
        if len(paginas) > MAX_PAGINAS:
            raise PdfInvalidoError(f"PDF com mais de {MAX_PAGINAS} paginas -- nao parece uma cifra.")
        return "\n".join(pagina.extract_text(extraction_mode="layout") or "" for pagina in paginas)
    except PdfInvalidoError:
        raise
    except (PdfReadError, ValueError, KeyError, TypeError, OSError) as erro:
        raise PdfInvalidoError("Nao foi possivel ler este PDF.") from erro


def _normalizar(texto):
    # Espaco nao separavel e hifen "suave" aparecem muito em PDF de navegador.
    texto = texto.replace("\r\n", "\n").replace("\xa0", " ").replace("\xad", "-")
    texto = texto.replace(" ", " ").replace("​", "").replace("\t", "    ")
    return [linha.rstrip() for linha in texto.split("\n")]


def _nome_artista_do_titulo(titulo):
    """"Nome - Artista - Cifra Club" -> ("Nome", "Artista")."""
    partes = [p.strip() for p in _SEPARADOR_TITULO.split(titulo) if p.strip()]
    while len(partes) > 1 and _PARTE_DE_SITE.search(partes[-1]):
        partes.pop()
    if not partes:
        return None, None
    return partes[0], (partes[1] if len(partes) > 1 else None)


def _sem_cabecalho_e_rodape(linhas):
    """Tira as linhas que o navegador poe em toda pagina; devolve
    (linhas_restantes, titulo_da_pagina_ou_None)."""
    titulo = None
    restantes = []
    for linha in linhas:
        data = _DATA_HORA.match(linha)
        if data:
            resto = linha[data.end():].strip()
            if resto and titulo is None and not _URL.search(resto):
                titulo = resto
            continue
        if _URL.search(linha) or _CONTADOR_PAGINA.match(linha):
            continue
        restantes.append(linha)
    # Titulo repetido sem a data (alguns navegadores) tambem e cabecalho.
    if titulo:
        restantes = [l for l in restantes if l.strip() != titulo]
    return restantes, titulo


def _tirar_recuo_comum(linhas):
    """Modo layout poe a margem da pagina como espacos a esquerda -- tira o
    recuo que TODAS as linhas tem, sem mexer no alinhamento entre elas."""
    recuos = [len(l) - len(l.lstrip(" ")) for l in linhas if l.strip()]
    corte = min(recuos) if recuos else 0
    return [l[corte:] for l in linhas]


def _compactar(linhas):
    """Tira linhas em branco das pontas e deixa no maximo 1 seguida."""
    saida = []
    for linha in linhas:
        if not linha.strip():
            if saida and saida[-1] != "":
                saida.append("")
        else:
            saida.append(linha)
    while saida and saida[-1] == "":
        saida.pop()
    return saida


def _comeco_da_cifra(linha):
    return eh_linha_de_acordes(linha) or bool(_ROTULO.match(linha))


def extrair_musica(dados, nome_arquivo=""):
    """Devolve {"nome", "artista", "tom", "cifra", "avisos": [...]} a partir
    dos bytes de um PDF. Levanta PdfInvalidoError se nem der pra ler."""
    avisos = []
    linhas = _normalizar(_texto_do_pdf(dados))
    if not any(l.strip() for l in linhas):
        return {
            "nome": _nome_do_arquivo(nome_arquivo), "artista": "", "tom": "", "cifra": "",
            "avisos": ["Este PDF nao tem texto (parece escaneado ou imagem) -- nao da pra extrair a cifra."],
        }

    linhas, titulo = _sem_cabecalho_e_rodape(linhas)
    linhas = _tirar_recuo_comum(linhas)
    nome, artista = _nome_artista_do_titulo(titulo) if titulo else (None, None)

    # Onde a cifra comeca: depois da linha "tom: X" ou, sem ela, na
    # primeira linha de acordes / rotulo [Intro].
    tom = ""
    inicio = None
    for i, linha in enumerate(linhas):
        achou_tom = _TOM.match(linha)
        if achou_tom:
            tom = achou_tom.group(1)
            tom = tom[0].upper() + tom[1:]
            inicio = i + 1
            break
        if _comeco_da_cifra(linha):
            inicio = i
            break
    if inicio is None:
        inicio = 0

    # Topo (antes da cifra): nome e artista, quando o titulo da pagina nao
    # deu. Outras linhas do topo (ex: "Capotraste na 2a casa") vao pra cifra.
    topo = [l.strip() for l in linhas[:inicio] if l.strip() and not _TOM.match(l)]
    if not nome and topo:
        nome = topo[0]
    if not artista and len(topo) > 1 and topo[1] != nome:
        artista = topo[1]
    conhecidos = {(nome or "").lower(), (artista or "").lower()}
    extras_do_topo = [l for l in topo if l.lower() not in conhecidos]

    corpo = [l for l in linhas[inicio:] if not _TOM.match(l)]
    while corpo and (not corpo[-1].strip() or _LIXO_FINAL.match(corpo[-1])):
        corpo.pop()
    cifra = "\n".join(_compactar(extras_do_topo + ([""] if extras_do_topo else []) + corpo))

    if not nome:
        nome = _nome_do_arquivo(nome_arquivo)
        avisos.append("Nome tirado do nome do arquivo -- confira.")
    if not any(eh_linha_de_acordes(l) for l in cifra.split("\n")):
        avisos.append("Nao encontrei acordes -- confira se este PDF e mesmo uma cifra.")
    if not tom:
        avisos.append("Tom nao encontrado no PDF.")

    return {
        "nome": nome[:150],
        "artista": (artista or "")[:120],
        "tom": tom[:10],
        "cifra": cifra,
        "avisos": avisos,
    }


def _nome_do_arquivo(nome_arquivo):
    base = re.sub(r"\.pdf$", "", (nome_arquivo or "").rsplit("/", 1)[-1].rsplit("\\", 1)[-1], flags=re.I)
    base = re.sub(r"[_]+", " ", base).strip()
    return base[:150] or "Musica sem nome"
