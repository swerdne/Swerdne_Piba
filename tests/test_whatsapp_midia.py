"""Caixa de entrada do WhatsApp com midia: foto, figurinha, video, documento,
localizacao e contato chegam pelo webhook, o arquivo e guardado (a URL da
Meta expira) e aparece na conversa."""
import pytest

from app.escala.models import Funcao
from app.whatsapp_recebidas import MensagemWhatsapp, MidiaWhatsapp
from tests.conftest import sessao_isolada
from tests.test_whatsapp_recebidas import _escala, _igreja, _postar, enviados  # noqa: F401

FOTO = b"\xff\xd8\xff\xe0foto-falsa"


@pytest.fixture
def meta(monkeypatch):
    """Meta falsa: devolve um arquivo por media_id e anota o que foi pedido."""
    arquivos = {"FOTO1": (FOTO, "image/jpeg"), "FIG1": (b"RIFFwebp", "image/webp"),
                "VID1": (b"\x00\x00\x00\x18ftypmp4" + b"v" * 200, "video/mp4"),
                "DOC1": (b"%PDF-1.4 escala", "application/pdf")}
    pedidos = []

    def baixar(media_id):
        pedidos.append(media_id)
        return arquivos[media_id]

    monkeypatch.setattr("app.whatsapp.baixar_midia", baixar)
    return pedidos


def _msg(tipo, conteudo, de="5511987654321", wamid="w1"):
    return {"entry": [{"changes": [{"value": {
        "contacts": [{"wa_id": de, "profile": {"name": "Ana"}}],
        "messages": [{"from": de, "id": wamid, "type": tipo, tipo: conteudo}],
    }}]}]}


def test_foto_com_legenda_guarda_o_arquivo_e_a_legenda_vale_como_texto(logged_in_client, enviados, meta, app, db):
    with app.app_context():
        _, ministerio, membro = _igreja(logged_in_client)
        escala = _escala(ministerio, membro)
        _postar(logged_in_client, _msg("image", {"id": "FOTO1", "mime_type": "image/jpeg", "caption": "não posso"}))
        msg = MensagemWhatsapp.objects(direcao="recebida").first()
        assert (msg.media_tipo, msg.texto) == ("image", "📷 Foto · não posso")
        assert meta == ["FOTO1"] and bytes(MidiaWhatsapp.objects(mensagem_id=msg.id).first().conteudo) == FOTO
        assert Funcao.objects(escala_id=escala.id).first().status == "troca_solicitada"  # a legenda valeu


def test_figurinha_sem_legenda_fica_pra_lideranca_sem_resposta(logged_in_client, enviados, meta, app, db):
    with app.app_context():
        _igreja(logged_in_client)
        _postar(logged_in_client, _msg("sticker", {"id": "FIG1", "mime_type": "image/webp", "animated": False}))
        msg = MensagemWhatsapp.objects(direcao="recebida").first()
        assert msg.tipo_midia == "sticker" and msg.lida is False
        assert enviados == []  # midia sem legenda nao recebe o menu automatico
        assert MidiaWhatsapp.objects(mensagem_id=msg.id).count() == 1


def test_conversa_mostra_foto_video_documento_e_figurinha(logged_in_client, enviados, meta, app, db):
    with app.app_context():
        comunidade, _, _ = _igreja(logged_in_client)
        _postar(logged_in_client, _msg("image", {"id": "FOTO1", "mime_type": "image/jpeg"}, wamid="a"))
        _postar(logged_in_client, _msg("video", {"id": "VID1", "mime_type": "video/mp4", "caption": "ensaio"}, wamid="b"))
        _postar(logged_in_client, _msg("document", {"id": "DOC1", "mime_type": "application/pdf",
                                                    "filename": "escala-novembro.pdf"}, wamid="c"))
        _postar(logged_in_client, _msg("sticker", {"id": "FIG1", "mime_type": "image/webp"}, wamid="d"))
        ids = {m.media_tipo: m.id for m in MensagemWhatsapp.objects(direcao="recebida")}

        html = logged_in_client.get(f"/comunidade/{comunidade.id}/whatsapp/5511987654321").data.decode()
        base = f"/comunidade/{comunidade.id}/whatsapp/midia/"
        assert f'<img src="{base}{ids["image"]}" alt="Foto enviada"' in html
        assert f'src="{base}{ids["video"]}"' in html and "<video controls playsinline" in html and "ensaio" in html
        assert "escala-novembro.pdf" in html and "fa-file-pdf" in html
        assert f'<img src="{base}{ids["sticker"]}" alt="Figurinha"' in html
        assert "Hoje" in html  # separador de dia

        lista = logged_in_client.get(f"/comunidade/{comunidade.id}/whatsapp").data.decode()
        assert "😀 Figurinha" in lista and "data-wa-busca" in lista


def test_rota_da_midia_inline_pedacos_e_download(logged_in_client, enviados, meta, app, db):
    with app.app_context():
        comunidade, _, _ = _igreja(logged_in_client)
        _postar(logged_in_client, _msg("video", {"id": "VID1", "mime_type": "video/mp4"}, wamid="v"))
        _postar(logged_in_client, _msg("document", {"id": "DOC1", "mime_type": "application/pdf",
                                                    "filename": "Escala Novembro.pdf"}, wamid="d"))
        video = MensagemWhatsapp.objects(media_tipo="video").first()
        doc = MensagemWhatsapp.objects(media_tipo="document").first()
        url = f"/comunidade/{comunidade.id}/whatsapp/midia/{video.id}"

        inteiro = logged_in_client.get(url)
        assert inteiro.status_code == 200 and inteiro.mimetype == "video/mp4"
        assert inteiro.headers["Content-Disposition"].startswith("inline")
        pedaco = logged_in_client.get(url, headers={"Range": "bytes=0-9"})
        assert pedaco.status_code == 206 and len(pedaco.data) == 10

        baixar = logged_in_client.get(f"/comunidade/{comunidade.id}/whatsapp/midia/{doc.id}?baixar=1")
        assert baixar.headers["Content-Disposition"].startswith("attachment")
        assert "Escala Novembro.pdf" in baixar.headers["Content-Disposition"] and baixar.data.startswith(b"%PDF")


def test_localizacao_e_contato_viram_texto_legivel(logged_in_client, enviados, app, db):
    with app.app_context():
        _igreja(logged_in_client)
        _postar(logged_in_client, _msg("location", {"latitude": -20.67, "longitude": -40.5, "name": "PIBA",
                                                   "address": "Rua A, 10"}, wamid="l"))
        _postar(logged_in_client, {"entry": [{"changes": [{"value": {
            "contacts": [{"wa_id": "5511987654321", "profile": {"name": "Ana"}}],
            "messages": [{"from": "5511987654321", "id": "c", "type": "contacts",
                          "contacts": [{"name": {"formatted_name": "Pr. João"}, "phones": [{"phone": "+55 28 99999-0000"}]}]}],
        }}]}]})
        textos = [m.texto for m in MensagemWhatsapp.objects(direcao="recebida").order_by("id")]
        assert textos[0].startswith("📍 Localização: PIBA — Rua A, 10") and "maps.google.com/?q=-20.67,-40.5" in textos[0]
        assert textos[1] == "👤 Contato: Pr. João — +55 28 99999-0000"


def test_midia_que_a_meta_nao_entrega_avisa_e_outra_conta_nao_ve(logged_in_client, outro_logged_in_client, enviados,
                                                                 app, db, monkeypatch):
    from app.whatsapp import WhatsappNaoEnviadoError

    def falha(media_id):
        raise WhatsappNaoEnviadoError("Midia maior que o limite.")

    monkeypatch.setattr("app.whatsapp.baixar_midia", falha)
    with app.app_context():
        comunidade, _, _ = _igreja(logged_in_client)
        _postar(logged_in_client, _msg("video", {"id": "GRANDE", "mime_type": "video/mp4"}, wamid="g"))
        msg = MensagemWhatsapp.objects(direcao="recebida").first()
        url = f"/comunidade/{comunidade.id}/whatsapp/midia/{msg.id}"
        resposta = logged_in_client.get(url)
        assert resposta.status_code == 404 and "Veja direto no WhatsApp" in resposta.data.decode()
        cid, mid = comunidade.id, msg.id
    with sessao_isolada(app):
        assert outro_logged_in_client.get(f"/comunidade/{cid}/whatsapp/midia/{mid}").status_code == 404


def test_formatacao_do_whatsapp_vira_html_seguro():
    from app.whatsapp_recebidas import texto_whatsapp_em_html as formatar

    assert str(formatar("✅ *Presença confirmada!*")) == "✅ <strong>Presença confirmada!</strong>"
    assert str(formatar("_(entre)_ e ~velho~")) == "<em>(entre)</em> e <s>velho</s>"
    assert str(formatar("2*3*4")) == "2*3*4"
    assert str(formatar("<script>x</script>")) == "&lt;script&gt;x&lt;/script&gt;"
    link = str(formatar("mapa https://maps.google.com/?q=-20_67 fim"))
    assert 'href="https://maps.google.com/?q=-20_67"' in link and "<em>" not in link
