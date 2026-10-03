"""Importacao em lote de cifras a partir de PDFs gerados por sites (ver
app/ministerio/importar_pdf.py e ministerio.routes.importar_musicas).

Os PDFs em tests/fixtures imitam "Imprimir > Salvar como PDF" de um site de
cifra: cabecalho do navegador (data + "Nome - Artista - Site"), rodape (link
+ "1/1"), nome/artista/"tom: X" no topo e a cifra em fonte monoespacada.
"""
import io
import json
from pathlib import Path

import pytest

from app.escala.models import Musica
from app.ministerio.importar_pdf import PdfInvalidoError, extrair_musica
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
    with pytest.raises(PdfInvalidoError):
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
        assert "Importar cifras de PDFs" in tela.data.decode("utf-8")
        repertorio = logged_in_client.get(f"/ministerio/{ministerio.id}/repertorio")
        assert f"/ministerio/{ministerio.id}/repertorio/importar" in repertorio.data.decode("utf-8")
