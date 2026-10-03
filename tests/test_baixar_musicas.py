"""Baixar musicas do banco em Word (.docx) -- uma, varias (.zip) ou as de um
repertorio -- e reimportar o arquivo baixado sem perder nada."""
import io
import zipfile

from app.escala.models import Musica, PastaMusicas
from app.ministerio.importar_cifras import extrair_musica
from tests.conftest import sessao_isolada
from tests.test_pastas_e_aprovacao import _criar_pasta
from tests.test_repertorio import CIFRA, _montar, _nova_musica, _preencher

CIFRA_LONGA = (
    "[Intro] G  D/F#  Em  C\n\n"
    "[Verso 1]\n"
    "G              D/F#\n"
    "Tu és digno de toda honra\n"
    "Em             C\n"
    "Tu és digno de todo louvor\n"
)


def _texto_do_docx(dados):
    with zipfile.ZipFile(io.BytesIO(dados)) as pacote:
        return pacote.read("word/document.xml").decode("utf-8")


def test_baixar_uma_musica_em_word_e_reimportar_da_a_mesma_cifra(logged_in_client, app, db):
    with app.app_context():
        _, ministerio, _ = _montar(logged_in_client)
        musica = _nova_musica(logged_in_client, ministerio.id, nome="Digno de Toda Honra", tom="G")
        logged_in_client.post(f"/ministerio/repertorio/{musica.id}/louvor", data={"cifra_louvor": CIFRA_LONGA})

        resposta = logged_in_client.get(f"/ministerio/repertorio/{musica.id}/baixar")
        assert resposta.status_code == 200
        assert resposta.mimetype.endswith("wordprocessingml.document")
        assert "Digno de Toda Honra.docx" in resposta.headers["Content-Disposition"]
        xml = _texto_do_docx(resposta.data)
        assert "Courier New" in xml and "Tu és digno de toda honra" in xml

        # Volta pela importacao igualzinha (nome, artista, tom e cifra alinhada).
        lida = extrair_musica(resposta.data, "Digno de Toda Honra.docx")
        assert lida["nome"] == "Digno de Toda Honra"
        assert lida["artista"] == "Adhemar"
        assert lida["tom"] == "G"
        assert lida["cifra"] == CIFRA_LONGA.strip("\n")


def test_baixar_musica_no_tom_de_uma_versao_salva(logged_in_client, app, db):
    with app.app_context():
        _, ministerio, _ = _montar(logged_in_client)
        musica = _nova_musica(logged_in_client, ministerio.id)
        _preencher(logged_in_client, musica)
        logged_in_client.post(f"/ministerio/repertorio/{musica.id}/louvor",
                              data={"cifra_louvor": "A        E\nGrande e o Senhor\n", "tom": "A"})

        lida = extrair_musica(logged_in_client.get(f"/ministerio/repertorio/{musica.id}/baixar?tom=A").data, "x.docx")
        assert lida["tom"] == "A" and lida["cifra"].startswith("A        E")
        original = extrair_musica(logged_in_client.get(f"/ministerio/repertorio/{musica.id}/baixar").data, "x.docx")
        assert original["tom"] == "G" and original["cifra"] == CIFRA.strip("\n")


def test_baixar_banco_inteiro_ou_so_as_marcadas_num_zip(logged_in_client, app, db):
    with app.app_context():
        comunidade, ministerio, _ = _montar(logged_in_client)
        a = _nova_musica(logged_in_client, ministerio.id, nome="Oceanos")
        b = _nova_musica(logged_in_client, ministerio.id, nome="Rude Cruz")
        c = _nova_musica(logged_in_client, ministerio.id, nome="Grande e o Senhor")
        Musica.objects(id__in=[a.id, b.id, c.id]).update(set__oficial=True, set__comunidade_id=comunidade.id)

        resposta = logged_in_client.get(f"/ministerio/musicas/{comunidade.id}/baixar")
        assert resposta.status_code == 200 and resposta.mimetype == "application/zip"
        with zipfile.ZipFile(io.BytesIO(resposta.data)) as pacote:
            assert sorted(pacote.namelist()) == ["Grande e o Senhor.docx", "Oceanos.docx", "Rude Cruz.docx"]

        so_duas = logged_in_client.get(f"/ministerio/musicas/{comunidade.id}/baixar?ids={a.id},{b.id}")
        with zipfile.ZipFile(io.BytesIO(so_duas.data)) as pacote:
            assert sorted(pacote.namelist()) == ["Oceanos.docx", "Rude Cruz.docx"]

        html = logged_in_client.get(f"/ministerio/musicas/{comunidade.id}").data.decode("utf-8")
        assert "data-baixar" in html and f"/ministerio/musicas/{comunidade.id}/baixar" in html


def test_baixar_repertorio_numera_na_ordem(logged_in_client, app, db):
    with app.app_context():
        comunidade, ministerio, _ = _montar(logged_in_client)
        a = _nova_musica(logged_in_client, ministerio.id, nome="Rude Cruz")
        b = _nova_musica(logged_in_client, ministerio.id, nome="Oceanos")
        _criar_pasta(logged_in_client, comunidade.id, "Manhã", [a, b], ministerio_id=ministerio.id)
        pasta = PastaMusicas.objects(nome="Manhã").first()

        resposta = logged_in_client.get(f"/ministerio/pastas/{pasta.id}/baixar")
        assert resposta.status_code == 200
        with zipfile.ZipFile(io.BytesIO(resposta.data)) as pacote:
            assert pacote.namelist() == ["01 - Rude Cruz.docx", "02 - Oceanos.docx"]


def test_quem_nao_ve_o_banco_nao_baixa(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade, ministerio, _ = _montar(logged_in_client)
        musica = _nova_musica(logged_in_client, ministerio.id)
    with sessao_isolada(app):
        assert outro_logged_in_client.get(f"/ministerio/repertorio/{musica.id}/baixar").status_code == 404
        assert outro_logged_in_client.get(f"/ministerio/musicas/{comunidade.id}/baixar").status_code == 404
        assert outro_logged_in_client.get(f"/ministerio/{ministerio.id}/repertorio/baixar").status_code == 404


def test_nome_de_arquivo_seguro():
    from app.ministerio.exportar_cifras import nome_de_arquivo

    assert nome_de_arquivo('Oceanos / Onde: "meus pés"?', "docx") == "Oceanos Onde meus pés.docx"
    assert nome_de_arquivo("", "zip") == "musica.zip"
