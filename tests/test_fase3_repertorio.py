"""Fase 3, item 3: player junto da cifra, troca de tom e modo palco."""
import io
import os

from app.escala.models import Musica
from app.ministerio.midia import id_do_youtube, midia_do_link
from tests.test_repertorio import _montar, _nova_musica, _preencher

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_reconhece_links_do_youtube_e_de_audio():
    for url in ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=30", "https://youtu.be/dQw4w9WgXcQ",
                "https://m.youtube.com/shorts/dQw4w9WgXcQ", "https://music.youtube.com/watch?v=dQw4w9WgXcQ",
                "https://www.youtube.com/embed/dQw4w9WgXcQ"):
        assert id_do_youtube(url) == "dQw4w9WgXcQ", url
    assert midia_do_link("https://youtu.be/dQw4w9WgXcQ")["embed"].startswith(
        "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ?")
    assert midia_do_link("https://exemplo.com/ensaio/baixo.mp3") == {"tipo": "audio", "url": "https://exemplo.com/ensaio/baixo.mp3"}
    for nada in ("https://www.cifraclub.com.br/x/y/", "javascript:alert(1)", "http://exemplo.com/a.mp3",
                 "https://youtube.com/watch?v=curto", "", None):
        assert midia_do_link(nada) is None, nada


def test_pagina_da_musica_tem_player_e_modo_palco(logged_in_client, app, db):
    with app.app_context():
        _, ministerio, _ = _montar(logged_in_client)
        musica = _nova_musica(logged_in_client, ministerio.id)
        _preencher(logged_in_client, musica)
        Musica.objects(id=musica.id).update(set__link="https://youtu.be/dQw4w9WgXcQ")
        html = logged_in_client.get(f"/ministerio/repertorio/{musica.id}").get_data(as_text=True)
        assert "data-player-musica" in html and "Ouvir aqui" in html
        assert 'data-player-abrir="https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ' in html
        assert "<iframe" not in html  # o video so carrega no toque
        assert 'data-modo-palco="#cifra_louvor"' in html and "js/palco.js" in html  # lider: tela de edicao
        assert "data-transpor-passo" in html  # tom com um toque (+/- meio tom)


def test_link_que_nao_e_midia_nao_vira_player(logged_in_client, app, db):
    with app.app_context():
        _, ministerio, _ = _montar(logged_in_client)
        musica = _nova_musica(logged_in_client, ministerio.id)
        Musica.objects(id=musica.id).update(set__link="https://www.cifraclub.com.br/artista/musica/")
        html = logged_in_client.get(f"/ministerio/repertorio/{musica.id}").get_data(as_text=True)
        assert "data-player-musica" not in html and "Referência" in html


def test_player_no_repertorio_da_escala_e_folha_com_modo_palco(logged_in_client, app, db):
    with app.app_context():
        _, ministerio, escala = _montar(logged_in_client)
        logged_in_client.post(f"/escala/{escala.id}/repertorio/adicionar",
                              data={"nome_musica": "Avulsa", "tom": "C", "link": "https://youtu.be/dQw4w9WgXcQ"})
        logged_in_client.post(f"/escala/{escala.id}/repertorio/adicionar",
                              data={"nome_musica": "Áudio", "tom": "D", "link": "https://exemplo.com/guia.mp3"})
        html = logged_in_client.get(f"/escala/{escala.id}").get_data(as_text=True)
        assert "Ouvir aqui" in html and '<audio controls preload="none" src="https://exemplo.com/guia.mp3"' in html
        folha = logged_in_client.get(f"/escala/{escala.id}/repertorio/cifras").get_data(as_text=True)
        assert 'data-modo-palco=".folha"' in folha and "js/palco.js" in folha


def test_modo_palco_tem_fonte_rolagem_e_tela_ligada():
    js = io.open(os.path.join(RAIZ, "app", "static", "js", "palco.js"), encoding="utf-8").read()
    for trecho in ("navigator.wakeLock.request('screen')", "mudarFonte", "mudarVelocidade", "requestAnimationFrame",
                   "requestFullscreen", "localStorage"):
        assert trecho in js, trecho
    principal = io.open(os.path.join(RAIZ, "app", "static", "js", "main.js"), encoding="utf-8").read()
    assert "data-player-abrir" in principal  # player do YouTube em toda pagina
