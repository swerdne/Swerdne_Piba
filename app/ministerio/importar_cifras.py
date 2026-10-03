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
quebra de linha manual tambem. Quase toda cifra feita no Word/Google Docs
alinha os acordes com ESPACOS numa fonte PROPORCIONAL (Arial...), onde o
espaco e bem mais estreito que uma letra -- copiado tal e qual pra tela
(fonte monoespacada), os acordes escorregam pra direita. realinhar_acordes
recalcula a posicao de cada acorde pela largura real das letras na fonte
do documento (larguras_fontes.py) e o poe sobre a mesma letra. Documento em
fonte monoespacada (Courier, Consolas...) fica como esta. O
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

from app.escala.models import detectar_tom, eh_linha_de_acordes
from app.ministerio.larguras_fontes import CARACTERES, LARGURA_PADRAO, LARGURAS

# PDF de navegador costuma ter tabela de fontes com linhas "quebradas" que o
# pypdf contorna sozinho, mas avisa no log a cada uma -- ruido puro aqui.
logging.getLogger("pypdf").setLevel(logging.ERROR)

MAX_PAGINAS = 30  # cifra de site tem 1-4 paginas; acima disso nao e uma cifra
# Teto do XML descompactado do .docx -- protege contra zip "bomba" (arquivo
# pequeno que descompacta em gigas). Cifra de verdade fica em dezenas de KB.
MAX_XML_DOCX = 20 * 1024 * 1024

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
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


# --- Fonte de cada paragrafo do Word (pra realinhar os acordes) -----------------

_FONTES_MONO = ("courier", "consolas", "lucida console", "mono", "menlo", "monaco", "lucida sans typewriter")
_TAMANHO_PADRAO_PT = 11.0
_TAB_PT = 36.0  # tab padrao do Word: a cada 1,27 cm


def _chave_da_fonte(nome):
    """Nome da fonte do Word -> chave de larguras_fontes (None = monoespacada,
    nao precisa realinhar). Fonte proporcional desconhecida usa Arial, que e
    bem proxima da maioria das sem serifa."""
    nome = (nome or "").lower()
    if any(m in nome for m in _FONTES_MONO):
        return None
    for chave in ("calibri", "times", "tahoma"):
        if chave in nome:
            return chave
    return "arial"


def _estilo_padrao(pacote):
    """(fonte, tamanho em pt) padrao do documento: docDefaults do styles.xml,
    resolvendo fonte de tema (minorHAnsi -> theme1.xml)."""
    fonte, tamanho = None, _TAMANHO_PADRAO_PT
    try:
        estilos = ET.fromstring(pacote.read("word/styles.xml"))
    except (KeyError, ET.ParseError):
        return "Arial", tamanho
    padrao = estilos.find(f"{_W}docDefaults/{_W}rPrDefault/{_W}rPr")
    if padrao is not None:
        rfonts = padrao.find(_W + "rFonts")
        if rfonts is not None:
            fonte = rfonts.get(_W + "ascii") or rfonts.get(_W + "hAnsi")
            if not fonte and (rfonts.get(_W + "asciiTheme") or "").startswith("minor"):
                fonte = _fonte_do_tema(pacote)
        sz = padrao.find(_W + "sz")
        if sz is not None and (sz.get(_W + "val") or "").isdigit():
            tamanho = int(sz.get(_W + "val")) / 2
    return fonte or "Arial", tamanho


def _fonte_do_tema(pacote):
    try:
        tema = ET.fromstring(pacote.read("word/theme/theme1.xml"))
    except (KeyError, ET.ParseError):
        return None
    latina = tema.find(f".//{_A}minorFont/{_A}latin")
    return latina.get("typeface") if latina is not None else None


def _estilo_do_paragrafo(paragrafo, padrao):
    """(chave da fonte ou None, tamanho pt, negrito) do 1o trecho com texto."""
    fonte, tamanho = padrao
    negrito = False
    for run in paragrafo.iter(_W + "r"):
        if not "".join(t.text or "" for t in run.iter(_W + "t")).strip():
            continue
        propriedades = run.find(_W + "rPr")
        if propriedades is not None:
            rfonts = propriedades.find(_W + "rFonts")
            if rfonts is not None and (rfonts.get(_W + "ascii") or rfonts.get(_W + "hAnsi")):
                fonte = rfonts.get(_W + "ascii") or rfonts.get(_W + "hAnsi")
            sz = propriedades.find(_W + "sz")
            if sz is not None and (sz.get(_W + "val") or "").isdigit():
                tamanho = int(sz.get(_W + "val")) / 2
            b = propriedades.find(_W + "b")
            negrito = b is not None and (b.get(_W + "val") or "true").lower() not in ("0", "false")
        break
    return _chave_da_fonte(fonte), tamanho, negrito


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
            padrao = _estilo_padrao(pacote)
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
    linhas = []  # [(texto, estilo)] -- quebra manual vira linhas com o mesmo estilo

    def percorrer(no):
        if no.tag == _FALLBACK:
            return
        if no.tag == _W + "p":
            estilo = _estilo_do_paragrafo(no, padrao)
            for texto in _linhas_do_paragrafo(no).split("\n"):
                linhas.append((texto, estilo))
        for filho in no:
            percorrer(filho)

    percorrer(corpo)
    return "\n".join(realinhar_acordes(linhas))


# --- Realinhamento dos acordes (fonte proporcional -> colunas) --------------------

_INDICE_CARACTERE = {c: i for i, c in enumerate(CARACTERES)}
_MONO_MILESIMOS = 600  # Courier: todo caractere tem a mesma largura


def _largura(caractere, estilo):
    chave, tamanho, negrito = estilo
    if chave is None:
        return _MONO_MILESIMOS * tamanho / 1000
    tabela = LARGURAS[chave + ("-negrito" if negrito else "")]
    indice = _INDICE_CARACTERE.get(caractere)
    return (tabela[indice] if indice is not None else LARGURA_PADRAO) * tamanho / 1000


def _posicoes(texto, estilo):
    """x (em pt) do inicio de cada caractere, + o fim da linha."""
    posicoes, x = [], 0.0
    for caractere in texto:
        posicoes.append(x)
        if caractere == "\t":
            x = (int(x // _TAB_PT) + 1) * _TAB_PT
        else:
            x += _largura(caractere, estilo)
    posicoes.append(x)
    return posicoes


def _eh_letra(texto):
    return bool(texto.strip()) and not eh_linha_de_acordes(texto) and not texto.strip().startswith("[")


def _montar_linha(colunas_e_acordes):
    saida = ""
    for coluna, acorde in colunas_e_acordes:
        coluna = max(coluna, len(saida) + (1 if saida else 0))
        saida = saida.ljust(coluna) + acorde
    return saida


def _realinhar_linha(acordes_txt, estilo_acordes, letra_txt, estilo_letra, largura_media):
    xs = _posicoes(acordes_txt, estilo_acordes)
    tokens = [(m.start(), m.group()) for m in re.finditer(r"\S+", acordes_txt)]
    if letra_txt is None:
        return _montar_linha((round(xs[i] / largura_media), t) for i, t in tokens)
    xs_letra = _posicoes(letra_txt, estilo_letra)
    fim_letra = xs_letra[-1]
    media_letra = fim_letra / len(letra_txt) if letra_txt else largura_media
    colocados = []
    for i, token in tokens:
        x = xs[i]
        if x <= fim_letra:
            # A letra mais perto do ponto onde o acorde estava.
            coluna = min(range(len(xs_letra)), key=lambda k: abs(xs_letra[k] - x))
        else:
            coluna = len(letra_txt) + round((x - fim_letra) / media_letra)
        colocados.append((coluna, token))
    return _montar_linha(colocados)


def realinhar_acordes(linhas):
    """[(texto, estilo)] -> [texto] com cada linha de acordes escrita em fonte
    proporcional reposicionada por coluna sobre a linha de letra seguinte.
    estilo = (chave da fonte ou None se monoespacada, tamanho pt, negrito).
    Linhas que nao sao de acordes saem como estao."""
    letras = [(t, e) for t, e in linhas if e[0] is not None and _eh_letra(t)]
    total = sum(_posicoes(t, e)[-1] for t, e in letras)
    caracteres = sum(len(t) for t, _ in letras)
    largura_media_padrao = (total / caracteres) if caracteres else 0.6 * _TAMANHO_PADRAO_PT

    saida = []
    for indice, (texto, estilo) in enumerate(linhas):
        if estilo[0] is None or not eh_linha_de_acordes(texto):
            saida.append(texto)
            continue
        seguinte = linhas[indice + 1] if indice + 1 < len(linhas) else None
        if seguinte is not None and _eh_letra(seguinte[0]):
            saida.append(_realinhar_linha(texto, estilo, seguinte[0], seguinte[1], largura_media_padrao))
        else:
            saida.append(_realinhar_linha(texto, estilo, None, None, largura_media_padrao))
    return saida


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
            "nome": _nome_do_arquivo(nome_arquivo), "artista": "", "tom": "", "cifra": "", "tags": [],
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
        # Sem "tom: X" no arquivo: identifica pelos acordes. Quando o arquivo
        # informa, ele manda -- com capotraste o tom real difere do desenho
        # dos acordes, e o site sabe disso; os acordes sozinhos, nao.
        tom = detectar_tom(cifra) or ""
        if tom:
            avisos.append(f"Tom {tom} identificado automaticamente pelos acordes -- confira.")
        else:
            avisos.append("Tom nao encontrado no arquivo nem identificado pelos acordes.")

    from app.escala.temas import sugerir_tags

    return {
        "nome": nome[:150],
        "artista": (artista or "")[:120],
        "tom": tom[:10],
        "cifra": cifra,
        "tags": sugerir_tags(nome, cifra=cifra),
        "avisos": avisos,
    }


def _nome_do_arquivo(nome_arquivo):
    base = re.sub(r"\.(?:pdf|docx?)$", "", (nome_arquivo or "").rsplit("/", 1)[-1].rsplit("\\", 1)[-1], flags=re.I)
    base = re.sub(r"[_]+", " ", base).strip()
    return base[:150] or "Musica sem nome"
