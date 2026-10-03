"""Importacao em lote de cifras a partir de PDFs gerados por sites (ver
app/ministerio/importar_cifras.py e ministerio.routes.importar_musicas).

Os PDFs em tests/fixtures imitam "Imprimir > Salvar como PDF" de um site de
cifra: cabecalho do navegador (data + "Nome - Artista - Site"), rodape (link
+ "1/1"), nome/artista/"tom: X" no topo e a cifra em fonte monoespacada.
"""
import io
import re
import json
from pathlib import Path

import pytest

from app.escala.models import Musica
from app.ministerio.importar_cifras import ArquivoInvalidoError, extrair_musica
from tests.conftest import sessao_isolada
from tests.test_escala import _criar_comunidade, _criar_ministerio

FIXTURES = Path(__file__).parent / "fixtures"


def _pdf(nome):
    return (FIXTURES / nome).read_bytes()


# --- Extracao (funcao pura) ---------------------------------------------------

def test_extrai_nome_artista_tom_e_cifra_do_pdf_do_site():
    musica = extrair_musica(_pdf("cifra_cifraclub.pdf"), "cifra_cifraclub.pdf")
    assert musica["nome"] == "Digno de Toda Honra"
    assert musica["artista"] == "Ministério Exemplo"
    assert musica["tom"] == "G"
    assert musica["avisos"] == []
    cifra = musica["cifra"]
    # Comeca direto na cifra -- cabecalho/rodape do navegador e topo ficam de fora.
    assert cifra.startswith("[Intro] G  D/F#  Em  C")
    assert "cifraclub" not in cifra.lower() and "1/1" not in cifra and "tom:" not in cifra.lower()
    # Alinhamento dos acordes em cima da letra preservado.
    assert "G                 D/F#\n  Tu és digno de toda honra" in cifra


def test_extrai_sem_cabecalho_do_navegador_usando_o_topo_da_pagina():
    musica = extrair_musica(_pdf("cifra_sem_cabecalho.pdf"), "x.pdf")
    assert musica["nome"] == "Grande É o Senhor"
    assert musica["artista"] == "Coral Modelo"
    assert musica["tom"] == "Em"


def test_varias_paginas_viram_uma_cifra_so_sem_cabecalhos_no_meio():
    musica = extrair_musica(_pdf("cifra_varias_paginas.pdf"), "x.pdf")
    assert musica["nome"] == "Santo Santo Santo"
    assert musica["cifra"].count("[Primeira Parte]") == 3
    assert "Cifra Club" not in musica["cifra"]
    assert "2/3" not in musica["cifra"]


def test_arquivo_que_nao_e_pdf_da_erro_claro():
    with pytest.raises(ArquivoInvalidoError):
        extrair_musica(b"isto nao e um pdf", "falso.pdf")


# --- Rotas ------------------------------------------------------------------

def _ministerio(cliente):
    comunidade = _criar_comunidade(cliente)
    return _criar_ministerio(cliente, comunidade.id)


def _extrair(cliente, ministerio_id, conteudo, nome="cifra.pdf"):
    return cliente.post(
        f"/ministerio/{ministerio_id}/repertorio/importar/extrair",
        data={"arquivo": (io.BytesIO(conteudo), nome)},
        content_type="multipart/form-data",
    )


def test_extrair_devolve_sugestao_sem_gravar_nada(logged_in_client, app, db):
    with app.app_context():
        ministerio = _ministerio(logged_in_client)
        resposta = _extrair(logged_in_client, ministerio.id, _pdf("cifra_cifraclub.pdf"))
        assert resposta.status_code == 200
        musica = resposta.get_json()["musica"]
        assert musica["nome"] == "Digno de Toda Honra"
        assert musica["ja_existe"] is False
        assert Musica.objects(ministerio_id=ministerio.id).count() == 0


def test_extrair_avisa_musica_repetida(logged_in_client, app, db):
    with app.app_context():
        ministerio = _ministerio(logged_in_client)
        Musica(ministerio_id=ministerio.id, nome="digno de toda honra").save()
        resposta = _extrair(logged_in_client, ministerio.id, _pdf("cifra_cifraclub.pdf"))
        assert resposta.get_json()["musica"]["ja_existe"] is True


def test_extrair_pdf_invalido_responde_erro_sem_500(logged_in_client, app, db):
    with app.app_context():
        ministerio = _ministerio(logged_in_client)
        resposta = _extrair(logged_in_client, ministerio.id, b"lixo", "quebrado.pdf")
        assert resposta.status_code == 422
        assert "erro" in resposta.get_json()


def test_salvar_cria_musicas_com_cifra_e_projecao(logged_in_client, app, db):
    with app.app_context():
        ministerio = _ministerio(logged_in_client)
        musicas = [
            {"nome": "Digno", "artista": "Exemplo", "tom": "G",
             "cifra": "[Refrão]\nG        D\nSanto, santo\n"},
            {"nome": "Outra", "artista": "", "tom": "", "cifra": ""},
        ]
        resposta = logged_in_client.post(
            f"/ministerio/{ministerio.id}/repertorio/importar/salvar",
            data={"musicas": json.dumps(musicas)},
        )
        assert resposta.get_json()["criadas"] == 2

        digno = Musica.objects(ministerio_id=ministerio.id, nome="Digno").first()
        assert digno.tom == "G" and digno.artista == "Exemplo"
        assert "Santo, santo" in digno.cifra_louvor
        # Projecao gerada da cifra: sem acordes, rotulo padronizado, maiusculas.
        assert digno.letra_projecao == "[REFRÃO]\nSANTO, SANTO"
        assert Musica.objects(ministerio_id=ministerio.id, nome="Outra").first().cifra_louvor is None


def test_importacao_so_pra_quem_gerencia_o_ministerio(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        ministerio_id = _ministerio(logged_in_client).id

    with sessao_isolada(app):
        assert outro_logged_in_client.get(f"/ministerio/{ministerio_id}/repertorio/importar").status_code == 404
        assert _extrair(outro_logged_in_client, ministerio_id, _pdf("cifra_cifraclub.pdf")).status_code == 404
        resposta = outro_logged_in_client.post(
            f"/ministerio/{ministerio_id}/repertorio/importar/salvar",
            data={"musicas": json.dumps([{"nome": "Invasora"}])},
        )
        assert resposta.status_code == 404
        assert Musica.objects(nome="Invasora").count() == 0


def test_tela_de_importacao_abre_e_repertorio_tem_o_link(logged_in_client, app, db):
    with app.app_context():
        ministerio = _ministerio(logged_in_client)
        tela = logged_in_client.get(f"/ministerio/{ministerio.id}/repertorio/importar")
        assert tela.status_code == 200
        assert "Importar cifras de PDF ou Word" in tela.data.decode("utf-8")
        repertorio = logged_in_client.get(f"/ministerio/{ministerio.id}/repertorio")
        assert f"/ministerio/{ministerio.id}/repertorio/importar" in repertorio.data.decode("utf-8")


# --- Word (.docx) -------------------------------------------------------------

_NS_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _run(texto):
    from xml.sax.saxutils import escape
    partes = []
    for i, pedaco in enumerate(texto.split("\t")):
        if i:
            partes.append("<w:tab/>")
        partes.append(f'<w:t xml:space="preserve">{escape(pedaco)}</w:t>')
    return '<w:r><w:rPr><w:rFonts w:ascii="Courier New" w:hAnsi="Courier New"/></w:rPr>' + "".join(partes) + "</w:r>"


def _docx(paragrafos, extra_corpo="", com_cabecalho=True):
    """Monta um .docx com a mesma estrutura que o Word grava. Cada item de
    `paragrafos` vira um <w:p>; "\n" dentro dele vira quebra manual
    (Shift+Enter), "\t" vira tab."""
    corpo = ""
    for paragrafo in paragrafos:
        linhas = paragrafo.split("\n")
        runs = '<w:r><w:br/></w:r>'.join(_run(l) for l in linhas)
        corpo += f"<w:p>{runs}</w:p>"
    documento = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{_NS_W}" '
        'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006">'
        f"<w:body>{corpo}{extra_corpo}<w:sectPr/></w:body></w:document>"
    )
    arquivo = io.BytesIO()
    import zipfile
    with zipfile.ZipFile(arquivo, "w", zipfile.ZIP_DEFLATED) as pacote:
        pacote.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        pacote.writestr("word/document.xml", documento)
        if com_cabecalho:
            # Cabecalho do Word mora em outra parte -- nao pode entrar na cifra.
            pacote.writestr("word/header1.xml", f'<w:hdr xmlns:w="{_NS_W}"><w:p>{_run("Igreja Exemplo - Louvor")}</w:p></w:hdr>')
    return arquivo.getvalue()


_DOCX_CIFRA = [
    "Ele Reina",
    "Ministério Exemplo",
    "Tom: D",
    "",
    "[Intro] D  A  Bm  G",
    "",
    "[Verso]",
    "D              A\n  Ele reina sobre tudo",
    "Bm\tG\n  Pra sempre reinará",
]


def test_extrai_musica_de_documento_do_word():
    musica = extrair_musica(_docx(_DOCX_CIFRA), "ele_reina.docx")
    assert musica["nome"] == "Ele Reina"
    assert musica["artista"] == "Ministério Exemplo"
    assert musica["tom"] == "D"
    assert musica["avisos"] == []
    cifra = musica["cifra"]
    assert cifra.startswith("[Intro] D  A  Bm  G")
    # Quebra manual (Shift+Enter) vira linha nova; espacos preservados.
    assert "D              A\n  Ele reina sobre tudo" in cifra
    assert "Bm    G\n  Pra sempre reinará" in cifra  # tab -> 4 espacos
    assert "Igreja Exemplo" not in cifra  # cabecalho do Word ignorado


def test_caixa_de_texto_do_word_nao_sai_duplicada():
    """Word grava caixa de texto 2x (versao nova + mc:Fallback pra Word antigo)."""
    caixa = (
        "<w:p><w:r><mc:AlternateContent><mc:Choice><w:drawing><w:txbxContent>"
        f"<w:p>{_run('Capotraste na 2a casa')}</w:p>"
        "</w:txbxContent></w:drawing></mc:Choice><mc:Fallback><w:pict><w:txbxContent>"
        f"<w:p>{_run('Capotraste na 2a casa')}</w:p>"
        "</w:txbxContent></w:pict></mc:Fallback></mc:AlternateContent></w:r></w:p>"
    )
    musica = extrair_musica(_docx(_DOCX_CIFRA, extra_corpo=caixa), "x.docx")
    assert musica["cifra"].count("Capotraste na 2a casa") == 1


def test_doc_antigo_pede_pra_salvar_como_docx():
    with pytest.raises(ArquivoInvalidoError, match="docx"):
        extrair_musica(b"\xd0\xcf\x11\xe0 qualquer coisa", "antigo.doc")


def test_docx_corrompido_ou_manipulado_da_erro_claro():
    with pytest.raises(ArquivoInvalidoError):
        extrair_musica(b"nao e zip", "quebrado.docx")
    # Zip sem word/document.xml (ex: outro arquivo renomeado pra .docx).
    falso = io.BytesIO()
    import zipfile
    with zipfile.ZipFile(falso, "w") as pacote:
        pacote.writestr("qualquer.txt", "oi")
    with pytest.raises(ArquivoInvalidoError):
        extrair_musica(falso.getvalue(), "falso.docx")


def test_rota_extrair_aceita_docx(logged_in_client, app, db):
    with app.app_context():
        ministerio = _ministerio(logged_in_client)
        resposta = _extrair(logged_in_client, ministerio.id, _docx(_DOCX_CIFRA), "ele_reina.docx")
        assert resposta.status_code == 200
        assert resposta.get_json()["musica"]["nome"] == "Ele Reina"
        antigo = _extrair(logged_in_client, ministerio.id, b"\xd0\xcf\x11\xe0", "antigo.doc")
        assert antigo.status_code == 422
        assert "docx" in antigo.get_json()["erro"]


def test_lote_grande_salvo_em_partes_avisa_uma_vez_com_o_total(logged_in_client, app, db):
    """Pasta inteira chega em partes (ver importar_musicas.html): as partes
    do meio gravam sem aviso; so a ultima avisa, com o total de todas."""
    with app.app_context():
        ministerio = _ministerio(logged_in_client)
        url = f"/ministerio/{ministerio.id}/repertorio/importar/salvar"
        parte1 = [{"nome": f"Musica {i}"} for i in range(3)]
        parte2 = [{"nome": "Musica final"}]
        logged_in_client.post(url, data={"musicas": json.dumps(parte1), "parcial": "1"})
        logged_in_client.post(url, data={"musicas": json.dumps(parte2), "total": "4"})

        assert Musica.objects(ministerio_id=ministerio.id).count() == 4
        with logged_in_client.session_transaction() as sessao:
            avisos = [mensagem for _categoria, mensagem in sessao.get("_flashes", [])]
        assert avisos == ["4 musica(s) importada(s) para o repertorio."]


# --- Tom identificado pelos acordes (escala.models.detectar_tom) ---------------

@pytest.mark.parametrize("cifra, esperado", [
    ("G  D/F#  Em  C\nG D Em C\nC D G", "G"),
    ("Em  C  G  D\nEm C G D\nC D Em", "Em"),       # relativo de G: decide pelo inicio/fim
    ("Am  F  C  G\nAm Dm E7 Am", "Am"),            # V maior do menor harmonico
    ("C  Am  F  G\nDm G C\nF G C", "C"),
    ("Bb  Eb  F  Gm\nEb F Bb", "Bb"),              # grafia da propria cifra (nao A#)
    ("F#m  D  A  E\nD E F#m", "F#m"),
    ("E7M  B  C#m7  A9\nA9 B4 B E", "E"),          # extensoes contam pela qualidade
    ("[G]Tu es [D]santo [Em]Senhor [C]Deus\n[G]fim", "G"),  # acordes no meio da letra
    ("G D", None),                                 # pouco acorde: nao chuta
    ("so letra, nenhum acorde aqui", None),
])
def test_detectar_tom_pelos_acordes(cifra, esperado):
    from app.escala.models import detectar_tom
    assert detectar_tom(cifra) == esperado


def test_importacao_sem_tom_no_arquivo_identifica_pelos_acordes():
    sem_tom = [linha for linha in _DOCX_CIFRA if not linha.startswith("Tom:")]
    musica = extrair_musica(_docx(sem_tom), "ele_reina.docx")
    assert musica["tom"] == "D"
    assert any("identificado automaticamente" in aviso for aviso in musica["avisos"])


def test_tom_informado_no_arquivo_prevalece_sobre_os_acordes():
    """Com capotraste o desenho dos acordes nao e o tom real -- o arquivo manda."""
    com_capo = ["Ele Reina", "Ministério Exemplo", "Tom: E", "", "D  A  Bm  G\nG A D"]
    assert extrair_musica(_docx(com_capo), "x.docx")["tom"] == "E"


def test_salvar_cifra_em_musica_sem_tom_preenche_o_tom(logged_in_client, app, db):
    with app.app_context():
        ministerio = _ministerio(logged_in_client)
        sem_tom = Musica(ministerio_id=ministerio.id, nome="Sem tom")
        sem_tom.save()
        com_tom = Musica(ministerio_id=ministerio.id, nome="Com tom", tom="A")
        com_tom.save()
        cifra = "G  D  Em  C\nC D G"
        for musica in (sem_tom, com_tom):
            logged_in_client.post(f"/ministerio/repertorio/{musica.id}/louvor", data={"cifra_louvor": cifra, "tom": ""})

        assert Musica.objects(id=sem_tom.id).first().tom == "G"
        assert Musica.objects(id=com_tom.id).first().tom == "A"  # nunca troca tom ja informado


# --- Dropdown de tom (escala.forms.TomField) ------------------------------------

def test_campo_de_tom_e_um_dropdown_com_os_24_tons(logged_in_client, app, db):
    with app.app_context():
        ministerio = _ministerio(logged_in_client)
        html = logged_in_client.get(f"/ministerio/{ministerio.id}/repertorio").data.decode("utf-8")
        assert re.search(r'<select [^>]*name="tom"', html)
        assert '<option value="F#m">F#m — Fá# menor</option>' in html
        assert '<option value="Bb">Bb — Sib</option>' in html
        assert '<optgroup label="">' not in html  # opcao vazia solta no topo


def test_tom_antigo_com_outra_grafia_continua_selecionado(logged_in_client, app, db):
    """Musica salva como "A#" (antes do dropdown): sem isso o select viria em
    branco e o proximo salvar apagaria o tom."""
    with app.app_context():
        ministerio = _ministerio(logged_in_client)
        musica = Musica(ministerio_id=ministerio.id, nome="Antiga", tom="A#")
        musica.save()
        html = logged_in_client.get(f"/ministerio/repertorio/{musica.id}").data.decode("utf-8")
        assert '<option selected value="A#">A#</option>' in html


def test_tom_invalido_e_recusado(logged_in_client, app, db):
    with app.app_context():
        ministerio = _ministerio(logged_in_client)
        logged_in_client.post(f"/ministerio/{ministerio.id}/repertorio/nova",
                              data={"nome": "Teste", "tom": "Sol maior"})
        assert Musica.objects(ministerio_id=ministerio.id, nome="Teste").count() == 0
        logged_in_client.post(f"/ministerio/{ministerio.id}/repertorio/nova",
                              data={"nome": "Teste", "tom": "F#m"})
        assert Musica.objects(ministerio_id=ministerio.id, nome="Teste").first().tom == "F#m"


# --- Reconhecimento de linhas de acordes (escala.models.eh_linha_de_acordes) ---
#
# Notacoes reais de sites/cadernos de cifra. Se uma linha de acordes nao for
# reconhecida, a cifra perde transposicao e o tom nao e identificado; se uma
# linha de LETRA for confundida com acordes, ela some da projecao. A mesma
# regra existe em static/js/transpor.js -- mudou aqui, mude la.

_LINHAS_DE_ACORDES = [
    'C9(no3)  G',
    'Cadd9  G',
    'C(add9)  G',
    'C6/9  G',
    'C6(9)  G',
    'A7(b9/#11)  D',
    'Bø  E7',
    'Bø7  E7',
    'CΔ  G',
    'CΔ7  G',
    'Cmaj7  G',
    'C7M  G',
    'C7+  F',
    'Dm7(b5)  G7',
    'Dm7b5  G7',
    'F#°  G',
    'F#º7  G',
    'Ebdim  D',
    'G7(13)  C',
    'G13  C',
    'Asus4  A',
    'Asus2  A',
    'A4  A',
    'A2  A',
    'E5  A5',
    'Bb7(#11)  A',
    'C/E  F',
    'D/F#  G',
    'G/B  C',
    'A/C#  D',
    'E7/G#  A',
    'Am7/G  F',
    'N.C.  G  D',
    'G  D  N.C.',
    '|: G  D  Em  C :|',
    '|| G | D | Em | C ||',
    '( G  D  Em  C )',
    'G  D  Em  C ...',
    'G  D  Em  C  …',
    'G -> D -> Em',
    'G → D → Em',
    'G  D  (2x)',
    'G  D  x2',
    'G  D  2x',
    'G * D * Em',
    'Intro: G  D  Em  C',
    '[Intro] G  D  Em  C',
    'Refrão: C  G  D',
    'G7M(9)  D/F#  Em7(11)  C7M(9)',
    'Bb  F/A  Gm7  Eb7M',
    'E  B/D#  C#m7  A9',
    'D4(7)  D  A/C#',
    'G9(11)  Gsus',
    'Am7(11)  Am7(9)',
]

_LINHAS_DE_LETRA = [
    'A Deus seja a glória',
    'E eu te louvarei',
    'Agora é tempo',
    'Dá-me a mão',
    'Ah ah ah',
    'E a',
    'Ele é',
    'Bem',
    'Cada dia',
    'Fé',
    'De Deus',
    'Em Ti eu confio',
    'Deus é fiel',
    'Grande é o Senhor',
    'Bendito seja',
    'Cristo vive',
    'Glória a Deus',
    'Aleluia',
    'Amém',
    'Ao Rei dos reis',
    'Dai graças',
    'Eu e minha casa',
    'Fé, esperança e amor',
    'Graça sobre graça',
    'Em Cristo',
    'Ao Cordeiro',
    'Bom é louvar',
    'Cante ao Senhor',
    'Diga ao mundo',
]


@pytest.mark.parametrize("linha", _LINHAS_DE_ACORDES)
def test_reconhece_notacoes_de_acordes(linha):
    from app.escala.models import eh_linha_de_acordes
    assert eh_linha_de_acordes(linha)


@pytest.mark.parametrize("linha", _LINHAS_DE_LETRA)
def test_letra_nao_e_confundida_com_acordes(linha):
    from app.escala.models import eh_linha_de_acordes
    assert not eh_linha_de_acordes(linha)


def test_transpor_preserva_notacoes_especiais():
    from app.escala.models import transpor_cifra
    assert transpor_cifra("C6/9  G", 2) == "D6/9  A"          # 6/9 nao e baixo
    assert transpor_cifra("A7(b9/#11)  D", 2) == "B7(b9/#11)  E"
    assert transpor_cifra("D/F#  G", 2) == "E/G#  A"          # baixo continua transpondo
    assert transpor_cifra("N.C.  G  D", 2) == "N.C.  A  E"


def test_detecta_tom_com_notacoes_especiais():
    from app.escala.models import detectar_tom
    assert detectar_tom("|: Am  Dm7  Bø  E7(b9) :|\nN.C.\nF7M  Dm  E7  Am") == "Am"
    assert detectar_tom("C9(no3)  G/B  Am7  F6/9\nFΔ  G  C") == "C"
