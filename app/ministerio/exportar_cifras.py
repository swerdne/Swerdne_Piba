"""Baixar musicas do banco: cada musica vira um documento do Word (.docx),
varias vao juntas num .zip.

O .docx e montado direto no XML (zipfile, sem biblioteca extra -- mesmo
caminho da leitura em importar_cifras.py). Cifra em Courier New: fonte
monoespacada mantem o acorde em cima da silaba certa em qualquer Word/Google
Docs, e o arquivo volta pro app pela importacao sem precisar realinhar.
Acordes em laranja/negrito, igual a tela (cifra_em_html).

Formato do topo (nome, artista, "Tom: X", linha em branco, cifra) e o que a
importacao entende: reimportar o arquivo baixado devolve a mesma musica.
"""
import io
import re
import unicodedata
import zipfile
from xml.sax.saxutils import escape

from app.escala.models import _TOKEN_ACORDE, eh_linha_de_acordes

_FONTE = "Courier New"
_COR_ACORDE = "EA580C"

_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    '<Override PartName="/word/styles.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
    '</Types>'
)
_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
    'Target="word/document.xml"/>'
    '</Relationships>'
)
_DOC_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
    'Target="styles.xml"/>'
    '</Relationships>'
)
# Fonte padrao do documento = Courier New 10,5pt; paragrafo sem espaco extra
# (cada linha da cifra e um paragrafo, espaco entre eles desalinharia nada,
# mas deixaria a folha comprida demais).
_STYLES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    '<w:docDefaults><w:rPrDefault><w:rPr>'
    f'<w:rFonts w:ascii="{_FONTE}" w:hAnsi="{_FONTE}" w:cs="{_FONTE}" w:eastAsia="{_FONTE}"/>'
    '<w:sz w:val="21"/><w:szCs w:val="21"/><w:lang w:val="pt-BR"/>'
    '</w:rPr></w:rPrDefault>'
    '<w:pPrDefault><w:pPr><w:spacing w:before="0" w:after="0" w:line="240" w:lineRule="auto"/></w:pPr></w:pPrDefault>'
    '</w:docDefaults>'
    '</w:styles>'
)


def _run(texto, negrito=False, cor=None, tamanho=None):
    propriedades = f'<w:rFonts w:ascii="{_FONTE}" w:hAnsi="{_FONTE}" w:cs="{_FONTE}"/>'
    if negrito:
        propriedades += "<w:b/>"
    if cor:
        propriedades += f'<w:color w:val="{cor}"/>'
    if tamanho:
        propriedades += f'<w:sz w:val="{tamanho}"/><w:szCs w:val="{tamanho}"/>'
    return f'<w:r><w:rPr>{propriedades}</w:rPr><w:t xml:space="preserve">{escape(texto)}</w:t></w:r>'


def _paragrafo(runs=""):
    return f"<w:p>{runs}</w:p>"


def _linha_da_cifra(linha):
    if not eh_linha_de_acordes(linha):
        return _paragrafo(_run(linha) if linha else "")
    pedacos = []
    for pedaco in re.split(r"(\s+)", linha):
        if not pedaco:
            continue
        eh_acorde = not pedaco.isspace() and _TOKEN_ACORDE.match(pedaco)
        pedacos.append(_run(pedaco, negrito=bool(eh_acorde), cor=_COR_ACORDE if eh_acorde else None))
    return _paragrafo("".join(pedacos))


def texto_da_musica(musica, cifra=None, tom=None):
    """(cifra ou letra de projecao, tom) que vai no arquivo."""
    tom = tom if tom is not None else (musica.tom or "")
    corpo = cifra if cifra is not None else (musica.cifra_louvor or musica.letra_projecao or "")
    return corpo.replace("\r\n", "\n").strip("\n"), tom


def docx_da_musica(musica, cifra=None, tom=None):
    """Bytes do .docx de uma musica (cifra do tom pedido, se informada)."""
    corpo, tom = texto_da_musica(musica, cifra, tom)
    paragrafos = [_paragrafo(_run(musica.nome, negrito=True, tamanho=32))]
    if musica.artista:
        paragrafos.append(_paragrafo(_run(musica.artista, cor="6B7280")))
    if tom:
        paragrafos.append(_paragrafo(_run("Tom: ", negrito=True) + _run(tom, negrito=True, cor=_COR_ACORDE)))
    paragrafos.append(_paragrafo())
    if corpo:
        paragrafos.extend(_linha_da_cifra(linha.rstrip()) for linha in corpo.split("\n"))
    documento = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>" + "".join(paragrafos) +
        # A4, margens de 1,5 cm: cabe linha de cifra comprida sem quebrar.
        '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
        '<w:pgMar w:top="850" w:right="850" w:bottom="850" w:left="850" w:header="0" w:footer="0" w:gutter="0"/>'
        "</w:sectPr></w:body></w:document>"
    )
    saida = io.BytesIO()
    with zipfile.ZipFile(saida, "w", zipfile.ZIP_DEFLATED) as pacote:
        pacote.writestr("[Content_Types].xml", _CONTENT_TYPES)
        pacote.writestr("_rels/.rels", _RELS)
        pacote.writestr("word/_rels/document.xml.rels", _DOC_RELS)
        pacote.writestr("word/styles.xml", _STYLES)
        pacote.writestr("word/document.xml", documento)
    return saida.getvalue()


def nome_de_arquivo(texto, extensao):
    """Nome seguro pra qualquer sistema (sem / \\ : * ? etc.), acentos mantidos."""
    texto = unicodedata.normalize("NFC", texto or "")
    texto = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", texto)
    texto = " ".join(texto.split()).strip(" .")[:80] or "musica"
    return f"{texto}.{extensao}"


def zip_de_musicas(entradas, numerar=False):
    """[(musica, cifra_ou_None, tom_ou_None)] -> bytes do .zip, um .docx por
    musica. numerar: "01 - Nome.docx" (ordem de um repertorio). Nomes
    repetidos ganham (2), (3)..."""
    saida = io.BytesIO()
    usados = set()
    with zipfile.ZipFile(saida, "w", zipfile.ZIP_DEFLATED) as pacote:
        for n, (musica, cifra, tom) in enumerate(entradas, start=1):
            base = nome_de_arquivo(musica.nome, "docx")[:-5]
            if numerar:
                base = f"{n:02d} - {base}"
            nome, n = f"{base}.docx", 2
            while nome.lower() in usados:
                nome, n = f"{base} ({n}).docx", n + 1
            usados.add(nome.lower())
            pacote.writestr(nome, docx_da_musica(musica, cifra, tom))
    return saida.getvalue()
