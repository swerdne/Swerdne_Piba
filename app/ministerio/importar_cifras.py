"""Extracao de cifras de arquivos -- PDF gerado por sites (Cifra Club,
Cifras.com.br, Letras...) via "Imprimir > Salvar como PDF", ou documento do
Word (.docx) -- usada pela importacao em lote do banco de musicas
(ministerio.routes.importar_musicas).

So funcoes puras (bytes do arquivo -> dict); nada aqui grava no banco. O
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

Word (.docx): so o corpo do documento (cabecalho/rodape do Word ficam em
outra parte do arquivo e sao ignorados); cada paragrafo vira uma linha,
quebra de linha manual tambem. O alinhamento dos acordes depende de quem
digitou ter usado espacos (fonte monoespacada) -- tab vira 4 espacos. O
.doc antigo (binario, Word 97-2003) nao e lido: volta pedindo pra salvar
como .docx. Depois de extraido o texto, PDF e Word seguem a MESMA
heuristica (extrair_musica).
"""
import io
import logging
import re
import zipfile
import xml.etree.ElementTree as ET

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.escala.models import eh_linha_de_acordes

# PDF de navegador costuma ter tabela de fontes com linhas "quebradas" que o
# pypdf contorna sozinho, mas avisa no log a cada uma -- ruido puro aqui.
logging.getLogger("pypdf").setLevel(logging.ERROR)

MAX_PAGINAS = 30  # cifra de site tem 1-4 paginas; acima disso nao e uma cifra
# Teto do XML descompactado do .docx -- protege contra zip "bomba" (arquivo
# pequeno que descompacta em gigas). Cifra de verdade fica em dezenas de KB.
MAX_XML_DOCX = 20 * 1024 * 1024

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_FALLBACK = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback"

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


EXTENSOES_ACEITAS = (".pdf", ".docx")


class ArquivoInvalidoError(Exception):
    """Arquivo ilegivel, protegido por senha, grande demais ou de formato
    nao suportado -- a mensagem vai direto pra tela."""


def _texto_do_pdf(dados):
    try:
        leitor = PdfReader(io.BytesIO(dados))
        if leitor.is_encrypted and not leitor.decrypt(""):
            raise ArquivoInvalidoError("PDF protegido por senha.")
        paginas = leitor.pages
        if len(paginas) > MAX_PAGINAS:
            raise ArquivoInvalidoError(f"PDF com mais de {MAX_PAGINAS} paginas -- nao parece uma cifra.")
        return "\n".join(pagina.extract_text(extraction_mode="layout") or "" for pagina in paginas)
    except ArquivoInvalidoError:
        raise
    except (PdfReadError, ValueError, KeyError, TypeError, OSError) as erro:
        raise ArquivoInvalidoError("Nao foi possivel ler este PDF.") from erro


def _linhas_do_paragrafo(paragrafo):
    """Texto de 1 paragrafo do Word, respeitando tab e quebra manual
    (Shift+Enter, que vira varias linhas dentro do mesmo paragrafo)."""
    partes = []

    def visitar(no):
        if no.tag == _FALLBACK:
            return  # versao alternativa (duplicada) de caixa de texto/desenho
        if no.tag == _W + "t":
            partes.append(no.text or "")
        elif no.tag == _W + "tab":
            partes.append("\t")
        elif no.tag in (_W + "br", _W + "cr"):
            partes.append("\n")
        for filho in no:
            if filho.tag != _W + "p":  # paragrafo dentro de caixa de texto: visitado a parte
                visitar(filho)

    visitar(paragrafo)
    return "".join(partes)


def _texto_do_docx(dados):
    try:
        with zipfile.ZipFile(io.BytesIO(dados)) as pacote:
            try:
                info = pacote.getinfo("word/document.xml")
            except KeyError:
                raise ArquivoInvalidoError("Este arquivo nao parece um documento do Word (.docx).")
            if info.file_size > MAX_XML_DOCX:
                raise ArquivoInvalidoError("Documento do Word grande demais -- nao parece uma cifra.")
            xml = pacote.read(info)
    except ArquivoInvalidoError:
        raise
    except (zipfile.BadZipFile, OSError, RuntimeError) as erro:
        # RuntimeError: .docx protegido por senha (criptografado).
        raise ArquivoInvalidoError("Nao foi possivel ler este documento do Word.") from erro

    # Word nunca declara DTD/entidades -- se tiver, e arquivo manipulado.
    if b"<!DOCTYPE" in xml or b"<!ENTITY" in xml:
        raise ArquivoInvalidoError("Nao foi possivel ler este documento do Word.")
    try:
        raiz = ET.fromstring(xml)
    except ET.ParseError as erro:
        raise ArquivoInvalidoError("Nao foi possivel ler este documento do Word.") from erro

    corpo = raiz.find(_W + "body")
    if corpo is None:
        return ""
    linhas = []

    def percorrer(no):
        if no.tag == _FALLBACK:
            return
        if no.tag == _W + "p":
            linhas.append(_linhas_do_paragrafo(no))
        for filho in no:
            percorrer(filho)

    percorrer(corpo)
    return "\n".join(linhas)


def _texto_do_arquivo(dados, nome_arquivo):
    nome = (nome_arquivo or "").lower()
    if nome.endswith(".docx"):
        return _texto_do_docx(dados)
    if nome.endswith(".doc"):
        raise ArquivoInvalidoError(
            "Formato .doc antigo nao e suportado -- abra no Word e use Salvar como > Documento do Word (.docx)."
        )
    if nome.endswith(".pdf"):
        return _texto_do_pdf(dados)
    raise ArquivoInvalidoError("Envie um arquivo PDF ou Word (.docx).")


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
    dos bytes de um PDF ou .docx (decide pela extensao de `nome_arquivo`).
    Levanta ArquivoInvalidoError se nem der pra ler."""
    avisos = []
    linhas = _normalizar(_texto_do_arquivo(dados, nome_arquivo))
    if not any(l.strip() for l in linhas):
        vazio = (
            "Este documento esta vazio." if (nome_arquivo or "").lower().endswith(".docx")
            else "Este PDF nao tem texto (parece escaneado ou imagem) -- nao da pra extrair a cifra."
        )
        return {
            "nome": _nome_do_arquivo(nome_arquivo), "artista": "", "tom": "", "cifra": "",
            "avisos": [vazio],
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
    base = re.sub(r"\.(?:pdf|docx?)$", "", (nome_arquivo or "").rsplit("/", 1)[-1].rsplit("\\", 1)[-1], flags=re.I)
    base = re.sub(r"[_]+", " ", base).strip()
    return base[:150] or "Musica sem nome"
