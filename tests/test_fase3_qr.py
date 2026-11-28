"""Fase 3, item 6: check-in por QR code (quando o GPS falha dentro da igreja)."""
import re
from datetime import datetime, timedelta, timezone
from unittest import mock

from app.escala import qr
from app.escala.models import Escala, Funcao
from tests.conftest import sessao_isolada
from tests.test_escala import (
    _criar_comunidade, _criar_escala, _criar_membro, _criar_ministerio, _escalar, _funcao_por_nome,
)


def _agora():
    return datetime.now(timezone.utc) - timedelta(hours=3)


def _montar(cliente, email="bruno@example.com", horas=0):
    """Escala de hoje (horario = agora + horas) com Bruno escalado no Baixo."""
    comunidade = _criar_comunidade(cliente)
    ministerio = _criar_ministerio(cliente, comunidade.id)
    quando = _agora() + timedelta(hours=horas)
    escala = _criar_escala(cliente, ministerio.id, "Culto", data=quando.date().isoformat(), horario=quando.strftime("%H:%M"))
    bruno = _criar_membro(cliente, comunidade.id, "Bruno", email=email)
    funcao = _funcao_por_nome(escala, "Baixo")
    _escalar(cliente, funcao.id, bruno.id)
    return escala, funcao


def _url_atual(cliente, escala):
    return cliente.get(f"/escala/{escala.id}/qr-checkin/atual").get_json()["url"]


def test_lider_ve_o_qr_e_o_codigo_muda_com_o_tempo(logged_in_client, app, db):
    with app.app_context():
        escala, _ = _montar(logged_in_client)
        assert f"/escala/{escala.id}/qr-checkin" in logged_in_client.get(f"/escala/{escala.id}").get_data(as_text=True)
        html = logged_in_client.get(f"/escala/{escala.id}/qr-checkin").get_data(as_text=True)
        assert "qrcode.min.js" in html and f"/escala/{escala.id}/qr/" in html
        primeiro = _url_atual(logged_in_client, escala)
        with mock.patch("app.escala.qr.time.time", return_value=__import__("time").time() + 31):
            segundo = _url_atual(logged_in_client, escala)
        assert primeiro != segundo


def test_codigo_vale_pouco_tempo():
    from app import create_app

    app = create_app("testing")
    with app.app_context():
        janela = qr._janela_atual()
        assert qr.codigo_valido(7, f"{janela}-{qr.codigo(7, janela)}")
        assert qr.codigo_valido(7, f"{janela - 2}-{qr.codigo(7, janela - 2)}")
        assert not qr.codigo_valido(7, f"{janela - 3}-{qr.codigo(7, janela - 3)}")  # foto antiga
        assert not qr.codigo_valido(8, f"{janela}-{qr.codigo(7, janela)}")  # QR de outra escala
        assert not qr.codigo_valido(7, f"{janela}-0000000000000000")
        assert not qr.codigo_valido(7, "lixo")


def test_escalado_le_o_qr_e_fica_presente(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        escala, funcao = _montar(logged_in_client)
        url = _url_atual(logged_in_client, escala)
    caminho = re.sub(r"^https?://[^/]+", "", url)
    with sessao_isolada(app):
        tela = outro_logged_in_client.get(caminho).get_data(as_text=True)
        assert "Confirmar presença" in tela and "Baixo" in tela
        outro_logged_in_client.post(caminho)
        funcao = Funcao.objects(id=funcao.id).first()
        assert funcao.status == "presente" and funcao.checkin_metodo == "qr" and funcao.checkin_em is not None
    with sessao_isolada(app):
        html = logged_in_client.get(f"/escala/{escala.id}").get_data(as_text=True)
        assert "fa-qrcode" in html and " · QR" in html


def test_qr_expirado_nao_marca(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        escala, funcao = _montar(logged_in_client)
        janela = qr._janela_atual() - 5
        caminho = f"/escala/{escala.id}/qr/{janela}-{qr.codigo(escala.id, janela)}"
    with sessao_isolada(app):
        assert "já expirou" in outro_logged_in_client.get(caminho).get_data(as_text=True)
        outro_logged_in_client.post(caminho)
        assert Funcao.objects(id=funcao.id).first().status != "presente"


def test_quem_nao_esta_escalado_nao_faz_checkin(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        escala, funcao = _montar(logged_in_client, email="carla@example.com")
        caminho = re.sub(r"^https?://[^/]+", "", _url_atual(logged_in_client, escala))
    with sessao_isolada(app):
        assert "não está escalado" in outro_logged_in_client.get(caminho).get_data(as_text=True)
        outro_logged_in_client.post(caminho)
        assert Funcao.objects(id=funcao.id).first().status != "presente"


def test_fora_do_horario_nao_vale(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        escala, funcao = _montar(logged_in_client)
        # Escala daqui a 5 horas: o QR so abre 3 horas antes.
        quando = _agora() + timedelta(hours=5)
        if quando.date() != _agora().date():
            return  # perto da meia-noite: a escala cairia amanha, outro motivo
        Escala.objects(id=escala.id).update(set__horario=quando.time().replace(second=0, microsecond=0))
        html = logged_in_client.get(f"/escala/{escala.id}/qr-checkin").get_data(as_text=True)
        assert "O check-in por QR abre às" in html and "qrcode.min.js" not in html


def test_so_o_lider_abre_a_tela_do_qr(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        escala, _ = _montar(logged_in_client)
    with sessao_isolada(app):
        assert outro_logged_in_client.get(f"/escala/{escala.id}/qr-checkin").status_code == 404
        assert outro_logged_in_client.get(f"/escala/{escala.id}/qr-checkin/atual").status_code == 404
