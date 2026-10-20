"""Audios nos Materiais da escala: enviar (arquivo ou gravado na tela), tocar
na propria tela (com Range, que o iPhone exige) e baixar."""
import io

from app.escala.models import Anexo
from tests.conftest import sessao_isolada
from tests.test_minha_escala import _montar

MP3 = b"ID3" + bytes(range(256)) * 40  # ~10 KB


def _enviar_audio(cliente, escala_id, nome="guia.mp3", conteudo=MP3, apelido="", **extra):
    return cliente.post(
        f"/escala/{escala_id}/anexos",
        data={"anexo-arquivo": (io.BytesIO(conteudo), nome), "anexo-funcao_id": "0", "anexo-nome": apelido},
        content_type="multipart/form-data",
        **extra,
    )


def test_audio_enviado_aparece_com_player_e_baixar(logged_in_client, app, db):
    with app.app_context():
        _, _, escala = _montar(logged_in_client)
        _enviar_audio(logged_in_client, escala.id, apelido="Guia - Grande e o Senhor")
        anexo = Anexo.objects(escala_id=escala.id).first()
        assert anexo.nome_arquivo == "Guia - Grande e o Senhor.mp3" and anexo.tipo == "audio/mpeg" and anexo.eh_audio

        html = logged_in_client.get(f"/escala/{escala.id}").data.decode()
        assert "Audios (1)" in html and "<audio controls" in html
        assert f'/escala/anexo/{anexo.id}?baixar=1' in html and "data-gravador" in html

        minha = logged_in_client.get("/minha-escala").data.decode()
        assert "Guia - Grande e o Senhor" in minha and "<audio controls" in minha


def test_player_responde_com_pedacos_e_baixar_e_download(logged_in_client, app, db):
    with app.app_context():
        _, _, escala = _montar(logged_in_client)
        _enviar_audio(logged_in_client, escala.id)
        anexo = Anexo.objects(escala_id=escala.id).first()
        url = f"/escala/anexo/{anexo.id}"

        inteiro = logged_in_client.get(url)
        assert inteiro.status_code == 200 and inteiro.data == MP3 and inteiro.headers["Accept-Ranges"] == "bytes"
        assert "attachment" not in inteiro.headers.get("Content-Disposition", "")

        pedaco = logged_in_client.get(url, headers={"Range": "bytes=0-1"})  # o 1o pedido do Safari
        assert pedaco.status_code == 206 and pedaco.data == MP3[:2]
        assert pedaco.headers["Content-Range"] == f"bytes 0-1/{len(MP3)}"
        fim = logged_in_client.get(url, headers={"Range": "bytes=-10"})
        assert fim.status_code == 206 and fim.data == MP3[-10:]
        assert logged_in_client.get(url, headers={"Range": f"bytes={len(MP3) + 5}-"}).status_code == 416

        baixar = logged_in_client.get(url + "?baixar=1")
        assert "attachment" in baixar.headers["Content-Disposition"] and baixar.data == MP3


def test_audio_gravado_na_tela_vem_por_fetch(logged_in_client, app, db):
    """A gravacao (webm do Chrome / m4a do iPhone) usa a mesma rota, via fetch."""
    with app.app_context():
        _, _, escala = _montar(logged_in_client)
        resposta = _enviar_audio(logged_in_client, escala.id, nome="Audio gravado 18-10 21h30.webm",
                                 conteudo=b"\x1aE\xdf\xa3webm", headers={"X-Requested-With": "fetch"})
        assert resposta.get_json() == {"ok": True}
        m4a = _enviar_audio(logged_in_client, escala.id, nome="Audio gravado.m4a", conteudo=b"....ftypM4A ",
                            headers={"X-Requested-With": "fetch"})
        assert m4a.get_json() == {"ok": True}
        assert sorted(a.tipo for a in Anexo.objects(escala_id=escala.id)) == ["audio/mp4", "audio/webm"]


def test_audio_de_ate_15mb_e_quem_nao_e_da_equipe_nao_ouve(logged_in_client, outro_logged_in_client, app, db):
    with app.app_context():
        _, _, escala = _montar(logged_in_client)
        grande = b"ID3" + b"0" * (12 * 1024 * 1024)
        _enviar_audio(logged_in_client, escala.id, nome="ensaio.mp3", conteudo=grande)
        anexo = Anexo.objects(escala_id=escala.id).exclude("conteudo").first()
        assert anexo is not None and anexo.tamanho == len(grande)

        with sessao_isolada(app):
            assert outro_logged_in_client.get(f"/escala/anexo/{anexo.id}").status_code == 404
