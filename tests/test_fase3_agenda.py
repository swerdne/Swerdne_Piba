"""Fase 3, item 4: escalas na agenda (Google Agenda / iPhone) por link de
assinatura .ics, pessoal ou do ministerio."""
from datetime import date, datetime, timedelta, timezone

from app.agenda import _dobrar, calendario, evento_ics
from app.auth.models import User
from app.comunidade.models import Evento
from app.ministerio.models import UsuarioMinisterio
from tests.conftest import sessao_isolada
from tests.test_escala import (
    _criar_comunidade, _criar_escala, _criar_membro, _criar_ministerio, _escalar, _funcao_por_nome,
)


def _hoje():
    return (datetime.now(timezone.utc) - timedelta(hours=3)).date()


def _token(cliente, email="ana@example.com"):
    cliente.get("/perfil/agenda")
    return User.objects(email=email).first().token_agenda


def _montar(cliente):
    comunidade = _criar_comunidade(cliente)
    ministerio = _criar_ministerio(cliente, comunidade.id)
    dia = _hoje() + timedelta(days=4)
    escala = _criar_escala(cliente, ministerio.id, "Culto da Família", data=dia.isoformat(), horario="19:00")
    ana = _criar_membro(cliente, comunidade.id, "Ana", email="ana@example.com")
    _escalar(cliente, _funcao_por_nome(escala, "Baixo").id, ana.id)
    Evento(comunidade_id=comunidade.id, nome="Retiro", data=dia + timedelta(days=10)).save()
    return comunidade, ministerio, escala, dia


def test_ics_basico_e_linhas_dobradas():
    texto = calendario("Teste", [evento_ics("x@tybenson", date(2026, 12, 6), None, None, "Culto; especial, sábado",
                                            "linha 1\nlinha 2 " + "é" * 60)])
    assert texto.startswith("BEGIN:VCALENDAR\r\n") and texto.endswith("END:VCALENDAR\r\n")
    assert "SUMMARY:Culto\\; especial\\, sábado" in texto
    assert "DTSTART;VALUE=DATE:20261206" in texto and "DTEND;VALUE=DATE:20261207" in texto
    assert all(len(l.encode("utf-8")) <= 75 for l in texto.split("\r\n"))
    assert _dobrar("curta") == "curta"


def test_pagina_mostra_links_e_gera_token(logged_in_client, app, db):
    with app.app_context():
        _, ministerio, _, _ = _montar(logged_in_client)
        token = _token(logged_in_client)
        html = logged_in_client.get("/perfil/agenda").get_data(as_text=True)
        assert token and len(token) >= 40
        assert f"/agenda/{token}.ics" in html and f"/agenda/{token}/ministerio/{ministerio.id}.ics" in html
        assert "webcal://" in html and "Do URL" in html
        assert "/perfil/agenda" in logged_in_client.get("/dashboard").get_data(as_text=True)


def test_agenda_pessoal_sem_login(logged_in_client, client, app, db):
    with app.app_context():
        _, ministerio, escala, dia = _montar(logged_in_client)
        token = _token(logged_in_client)
        resposta = app.test_client().get(f"/agenda/{token}.ics")  # sem cookie, como o Google
        texto = resposta.get_data(as_text=True)
        assert resposta.status_code == 200 and resposta.mimetype == "text/calendar"
        assert "X-WR-CALNAME:Minhas escalas (TyBenson)" in texto
        assert f"UID:escala-{escala.id}-pessoa-" in texto and "SUMMARY:Culto da Família · Baixo" in texto
        assert f"DTSTART;TZID=America/Sao_Paulo:{dia:%Y%m%d}T190000" in texto
        assert "SUMMARY:Retiro" in texto  # evento da comunidade


def test_agenda_do_ministerio_mostra_quem_esta_em_cada_funcao(logged_in_client, app, db):
    with app.app_context():
        _, ministerio, escala, _ = _montar(logged_in_client)
        token = _token(logged_in_client)
        texto = app.test_client().get(f"/agenda/{token}/ministerio/{ministerio.id}.ics").get_data(as_text=True)
        desdobrado = texto.replace("\r\n ", "")
        assert f"UID:escala-{escala.id}@tybenson" in texto and "Baixo: Ana" in desdobrado and "vaga" in desdobrado


def test_ministerio_alheio_e_token_errado_nao_abrem(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        _, ministerio, _, _ = _montar(logged_in_client)
    with sessao_isolada(app):
        token_bruno = _token(outro_logged_in_client, "bruno@example.com")
    anonimo = app.test_client()
    assert anonimo.get(f"/agenda/{token_bruno}/ministerio/{ministerio.id}.ics").status_code == 404
    assert anonimo.get("/agenda/token-que-nao-existe-de-jeito-nenhum.ics").status_code == 404
    with sessao_isolada(app):
        bruno = User.objects(email="bruno@example.com").first()
        UsuarioMinisterio(usuario_id=bruno.id, ministerio_id=ministerio.id, papel="membro").save()
    assert anonimo.get(f"/agenda/{token_bruno}/ministerio/{ministerio.id}.ics").status_code == 200


def test_gerar_novo_link_desliga_o_antigo(logged_in_client, app, db):
    with app.app_context():
        antigo = _token(logged_in_client)
        logged_in_client.post("/perfil/agenda")
        novo = User.objects(email="ana@example.com").first().token_agenda
        assert novo != antigo
        anonimo = app.test_client()
        assert anonimo.get(f"/agenda/{antigo}.ics").status_code == 404
        assert anonimo.get(f"/agenda/{novo}.ics").status_code == 200


def test_escala_cancelada_vai_como_cancelada(logged_in_client, app, db):
    with app.app_context():
        _, _, escala, _ = _montar(logged_in_client)
        logged_in_client.post(f"/escala/{escala.id}/cancelar")
        texto = app.test_client().get(f"/agenda/{_token(logged_in_client)}.ics").get_data(as_text=True)
        assert "STATUS:CANCELLED" in texto
