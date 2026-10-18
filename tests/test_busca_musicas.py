"""Busca no Banco de Musicas: no banco (letra, varias palavras, erro de
digitacao), na web (so metadados do Deezer + links externos), colar cifra e
registro de fonte/link de origem."""
import json

import pytest

from app.escala.banco_musicas import buscar_no_banco
from app.escala.models import Musica
from app.ministerio import busca_web
from app.ministerio.importar_cifras import ArquivoInvalidoError, extrair_musica_de_texto
from tests.conftest import sessao_isolada
from tests.test_escala import _criar_comunidade, _criar_ministerio

CIFRA = """Bondade de Deus
Isaias Saad
Tom: G

[Intro] G  D  Em  C

G              D
Te amo, Deus, tua bondade e infinita
Em             C
Minha vida e teu louvor eterno
"""


def _ministerio(cliente):
    return _criar_ministerio(cliente, _criar_comunidade(cliente).id)


def _musica(ministerio, nome, **campos):
    return Musica(comunidade_id=ministerio.comunidade_id, ministerio_id=ministerio.id, oficial=False,
                  nome=nome, **campos).save()


# --- Busca no banco -------------------------------------------------------------------

class _M:
    """Musica de mentira pra testar a busca sem banco."""
    _id = 0

    def __init__(self, nome, artista="", tom="", tags=(), letra_projecao="", cifra_louvor=""):
        _M._id += 1
        self.id, self.nome, self.artista, self.tom = _M._id, nome, artista, tom
        self.tags, self.letra_projecao, self.cifra_louvor = list(tags), letra_projecao, cifra_louvor


@pytest.fixture
def acervo():
    return {
        "fiel": _M("Deus de Promessas", "Davi Sacer", letra_projecao="[REFRAO]\nDeus fiel, tu es fiel\nCumpres tuas promessas"),
        "cruz": _M("Rude Cruz", tags=["cruz", "graça"], letra_projecao="Rude cruz se erigiu"),
        "ressurreicao": _M("Ele Vive", tags=["ressurreição"], cifra_louvor="G   D\nO tumulo vazio\nC  G\nEle ressuscitou"),
        "graca": _M("Maravilhosa Graça", letra_projecao="Graça que me alcançou"),
    }


def test_busca_acha_trecho_da_letra_e_diz_onde(acervo):
    resultado = buscar_no_banco(acervo.values(), "Deus fiel")
    assert resultado[0] == {"id": acervo["fiel"].id, "onde": "nome"} or resultado[0]["id"] == acervo["fiel"].id
    assert [r["id"] for r in buscar_no_banco(acervo.values(), "tumulo vazio")] == [acervo["ressurreicao"].id]
    assert buscar_no_banco(acervo.values(), "tumulo vazio")[0]["onde"] == "letra"


def test_busca_exige_todas_as_palavras_e_ignora_acento(acervo):
    assert [r["id"] for r in buscar_no_banco(acervo.values(), "rude cruz")] == [acervo["cruz"].id]
    assert buscar_no_banco(acervo.values(), "rude graça tumulo") == []
    ids = {r["id"] for r in buscar_no_banco(acervo.values(), "GRACA")}
    assert ids == {acervo["cruz"].id, acervo["graca"].id}


def test_busca_tolera_erro_de_digitacao(acervo):
    assert [r["id"] for r in buscar_no_banco(acervo.values(), "ressureicao")] == [acervo["ressurreicao"].id]
    assert acervo["graca"].id in {r["id"] for r in buscar_no_banco(acervo.values(), "maravilhoza")}
    # Palavra curta precisa vir certa (senao "dor" acharia "dos", "do"...).
    assert buscar_no_banco(acervo.values(), "cru") == [{"id": acervo["cruz"].id, "onde": "nome"}]


def test_rota_de_busca_no_banco_e_isolada_por_conta(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        ministerio = _ministerio(logged_in_client)
        musica = _musica(ministerio, "Ele Vive", letra_projecao="O tumulo vazio")
        url = f"/ministerio/{ministerio.id}/repertorio/buscar?q=tumulo"
        dados = logged_in_client.get(url).get_json()
        assert dados["resultados"] == [{"id": musica.id, "onde": "letra"}]
    with sessao_isolada(app):
        assert outro_logged_in_client.get(url).status_code == 404


# --- Busca na web ---------------------------------------------------------------------

class _RespostaDeezer:
    def __init__(self, dados, status=200):
        self._dados, self.status_code = dados, status

    def json(self):
        return self._dados


@pytest.fixture
def deezer(monkeypatch):
    busca_web.limpar_cache()
    chamadas = []
    resposta = {"dados": {"data": [
        {"title": "Bondade de Deus", "link": "https://www.deezer.com/track/1", "artist": {"name": "Isaias Saad"},
         "album": {"title": "Bondade de Deus"}},
        {"title": "Bondade de Deus", "link": "https://www.deezer.com/track/2", "artist": {"name": "Isaias Saad"},
         "album": {"title": "Ao vivo"}},  # mesma musica em outro album: aparece 1 vez
        {"title": "Bondade <script>", "link": "javascript:alert(1)", "artist": {"name": "X"}},
    ]}}

    def falso_get(url, params=None, timeout=None):
        chamadas.append((url, params, timeout))
        if isinstance(resposta["dados"], Exception):
            raise resposta["dados"]
        return _RespostaDeezer(resposta["dados"])

    monkeypatch.setattr("app.ministerio.busca_web.requests.get", falso_get)
    yield {"chamadas": chamadas, "resposta": resposta}
    busca_web.limpar_cache()


def test_busca_web_traz_so_metadados_e_links_externos(logged_in_client, app, db, deezer):
    with app.app_context():
        ministerio = _ministerio(logged_in_client)
        url = f"/ministerio/{ministerio.id}/repertorio/busca-web?q=bondade de deus"
        resultados = logged_in_client.get(url).get_json()["resultados"]

        assert len(resultados) == 2
        primeiro = resultados[0]
        assert (primeiro["titulo"], primeiro["artista"], primeiro["link_origem"]) == (
            "Bondade de Deus", "Isaias Saad", "https://www.deezer.com/track/1")
        assert primeiro["links"]["cifraclub"] == "https://www.cifraclub.com.br/?q=Bondade+de+Deus+Isaias+Saad"
        assert "youtube.com/results" in primeiro["links"]["youtube"]
        assert "cifra" not in primeiro and "letra" not in primeiro  # nunca conteudo protegido
        assert resultados[1]["link_origem"] is None  # javascript: descartado
        assert deezer["chamadas"][0][0] == busca_web.URL_DEEZER and deezer["chamadas"][0][2] == busca_web.TIMEOUT_SEGUNDOS

        # Mesma busca de novo: vem do cache, sem chamar a fonte externa.
        logged_in_client.get(url)
        assert len(deezer["chamadas"]) == 1


def test_busca_web_fora_do_ar_volta_erro_sem_derrubar(logged_in_client, app, db, deezer):
    import requests

    with app.app_context():
        ministerio = _ministerio(logged_in_client)
        deezer["resposta"]["dados"] = requests.Timeout("lento")
        resposta = logged_in_client.get(f"/ministerio/{ministerio.id}/repertorio/busca-web?q=qualquer")
        assert resposta.status_code == 503 and "nao respondeu" in resposta.get_json()["erro"]

        deezer["resposta"]["dados"] = {"error": {"type": "Exception", "message": "Quota limit exceeded"}}
        assert logged_in_client.get(f"/ministerio/{ministerio.id}/repertorio/busca-web?q=outra").status_code == 503
        assert logged_in_client.get(f"/ministerio/{ministerio.id}/repertorio/busca-web?q=a").status_code == 400


def test_busca_web_so_para_quem_edita_o_banco(logged_in_client, outro_logged_in_client, app, db, deezer):
    with sessao_isolada(app):
        ministerio_id = _ministerio(logged_in_client).id
    with sessao_isolada(app):
        assert outro_logged_in_client.get(f"/ministerio/{ministerio_id}/repertorio/busca-web?q=bondade").status_code == 404
        resposta = outro_logged_in_client.post(f"/ministerio/{ministerio_id}/repertorio/busca-web/adicionar",
                                               data={"titulo": "X"})
        assert resposta.status_code == 404
    assert deezer["chamadas"] == []


def test_adicionar_da_web_cria_sem_cifra_com_fonte_e_nao_duplica(logged_in_client, app, db):
    with app.app_context():
        ministerio = _ministerio(logged_in_client)
        url = f"/ministerio/{ministerio.id}/repertorio/busca-web/adicionar"
        resposta = logged_in_client.post(url, data={
            "titulo": "Bondade de Deus", "artista": "Isaias Saad", "link_origem": "https://www.deezer.com/track/1",
        })
        musica = Musica.objects(nome="Bondade de Deus").first()
        assert resposta.status_code == 302 and resposta.headers["Location"].endswith(f"/repertorio/{musica.id}#louvor")
        assert (musica.artista, musica.fonte, musica.link_origem) == (
            "Isaias Saad", busca_web.FONTE_DEEZER, "https://www.deezer.com/track/1")
        assert musica.cifra_louvor is None and musica.oficial is False and musica.ministerio_id == ministerio.id

        # De novo (ou com outra grafia de maiuscula): abre a existente.
        resposta = logged_in_client.post(url, data={"titulo": "bondade de deus", "link_origem": "javascript:alert(1)"})
        assert resposta.headers["Location"].endswith(f"/repertorio/{musica.id}")
        assert Musica.objects(nome__iexact="bondade de deus").count() == 1

        pagina = logged_in_client.get(f"/ministerio/repertorio/{musica.id}").data.decode()
        assert "Fonte: Deezer" in pagina and "https://www.deezer.com/track/1" in pagina


def test_trazer_a_cifra_na_musica_adicionada_pela_web(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        ministerio = _ministerio(logged_in_client)
        logged_in_client.post(f"/ministerio/{ministerio.id}/repertorio/busca-web/adicionar", data={
            "titulo": "Bondade de Deus", "artista": "Isaias Saad", "link_origem": "https://www.deezer.com/track/1",
        })
        musica = Musica.objects(nome="Bondade de Deus").first()
        pagina = logged_in_client.get(f"/ministerio/repertorio/{musica.id}").data.decode()
        assert "Trazer a cifra" in pagina
        assert "https://www.cifraclub.com.br/?q=Bondade+de+Deus+Isaias+Saad" in pagina

        resposta = logged_in_client.post(f"/ministerio/repertorio/{musica.id}/louvor/colar", data={"texto": CIFRA})
        assert resposta.status_code == 302 and resposta.headers["Location"].endswith("#louvor")
        musica = Musica.objects(id=musica.id).first()
        assert "Te amo, Deus" in musica.cifra_louvor and "Isaias Saad" not in musica.cifra_louvor  # topo vira dados
        assert musica.tom == "G" and musica.letra_projecao  # tom do texto + projecao gerada
        assert musica.fonte == busca_web.FONTE_DEEZER + " + cifra colada"
        assert "Trazer a cifra" not in logged_in_client.get(f"/ministerio/repertorio/{musica.id}").data.decode()
        musica_id = musica.id
    with sessao_isolada(app):
        assert outro_logged_in_client.post(f"/ministerio/repertorio/{musica_id}/louvor/colar",
                                           data={"texto": CIFRA}).status_code == 404


def test_trazer_a_cifra_com_texto_vazio_avisa(logged_in_client, app, db):
    with app.app_context():
        ministerio = _ministerio(logged_in_client)
        musica = _musica(ministerio, "Sem Cifra")
        resposta = logged_in_client.post(f"/ministerio/repertorio/{musica.id}/louvor/colar", data={"texto": "  "},
                                         follow_redirects=True)
        assert "Cole o texto da cifra" in resposta.data.decode()
        assert Musica.objects(id=musica.id).first().cifra_louvor is None


def test_link_seguro_so_aceita_http():
    assert busca_web.link_seguro("https://x.com/a") == "https://x.com/a"
    assert busca_web.link_seguro("javascript:alert(1)") is None
    assert busca_web.link_seguro("data:text/html,oi") is None
    assert busca_web.link_seguro("https://" + "a" * 600) is None


# --- Colar cifra ----------------------------------------------------------------------

def test_extrair_musica_de_texto_colado():
    musica = extrair_musica_de_texto(CIFRA)
    assert (musica["nome"], musica["artista"], musica["tom"]) == ("Bondade de Deus", "Isaias Saad", "G")
    assert "Te amo, Deus" in musica["cifra"] and musica["fonte"] == "Texto colado"
    with pytest.raises(ArquivoInvalidoError):
        extrair_musica_de_texto("   ")
    with pytest.raises(ArquivoInvalidoError):
        extrair_musica_de_texto("G D\n" * 20000)


def test_colar_e_salvar_registra_a_fonte(logged_in_client, app, db):
    with app.app_context():
        ministerio = _ministerio(logged_in_client)
        base = f"/ministerio/{ministerio.id}/repertorio/importar"
        assert "Colar o texto de uma cifra" in logged_in_client.get(base).data.decode()
        assert "direitos autorais" in logged_in_client.get(base).data.decode()

        dados = logged_in_client.post(f"{base}/colar", data={
            "texto": CIFRA, "link_origem": "https://exemplo.org/minha-cifra",
        }).get_json()["musica"]
        assert dados["nome"] == "Bondade de Deus" and dados["link_origem"] == "https://exemplo.org/minha-cifra"
        assert Musica.objects.count() == 0  # so leu

        logged_in_client.post(f"{base}/salvar", data={"musicas": json.dumps([dados])})
        musica = Musica.objects(nome="Bondade de Deus").first()
        assert (musica.fonte, musica.link_origem, musica.tom) == ("Texto colado", "https://exemplo.org/minha-cifra", "G")
        assert musica.letra_projecao  # projecao gerada da cifra

        erro = logged_in_client.post(f"{base}/colar", data={"texto": ""})
        assert erro.status_code == 422


def test_tela_do_banco_tem_busca_na_web_so_pra_quem_edita(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        ministerio = _ministerio(logged_in_client)
        html = logged_in_client.get(f"/ministerio/{ministerio.id}/repertorio").data.decode()
        # Banco vazio: a busca (e a web) aparece mesmo assim pra quem edita.
        assert 'data-modo-busca="web"' in html and "data-buscar-web" in html
        comunidade_id = ministerio.comunidade_id
    with sessao_isolada(app):
        # Banco oficial visto por quem nao e admin: sem busca na web.
        resposta = outro_logged_in_client.get(f"/ministerio/musicas/{comunidade_id}")
        assert resposta.status_code == 404 or 'data-modo-busca="web"' not in resposta.data.decode()
