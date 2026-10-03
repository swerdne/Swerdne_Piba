"""Check-in por localizacao (app/escala/checkin.py): "Presente" do proprio
escalado so com a pessoa dentro do raio do local, no dia da escala."""
from datetime import datetime, timedelta, timezone
from unittest import mock

from app.escala.checkin import (
    LocalCheckin, avaliar_checkin, distancia_m, hora_local, local_do_checkin,
)
from app.escala.models import Funcao
from tests.conftest import sessao_isolada
from tests.test_escala import (
    _criar_comunidade, _criar_escala, _criar_membro, _criar_ministerio, _escalar, _funcao_por_nome,
)

# Um ponto em Sao Paulo e outros a ~50 m e ~1,1 km dele.
IGREJA = (-23.550520, -46.633308)
PERTO = (-23.550070, -46.633308)
LONGE = (-23.540520, -46.633308)


def _hoje():
    return (datetime.now(timezone.utc) - timedelta(hours=3)).date()


def _montar(cliente, dias=0, local=True, email="ana@example.com"):
    comunidade = _criar_comunidade(cliente)
    ministerio = _criar_ministerio(cliente, comunidade.id)
    escala = _criar_escala(cliente, ministerio.id, "Culto", data=(_hoje() + timedelta(days=dias)).isoformat(), horario="19:00")
    membro = _criar_membro(cliente, comunidade.id, "Ana", email=email)
    funcao = _funcao_por_nome(escala, "Baixo")
    _escalar(cliente, funcao.id, membro.id)
    if local:
        cliente.post(f"/comunidade/{comunidade.id}/local-checkin", data={
            "endereco": "Rua da Igreja, 10", "latitude": IGREJA[0], "longitude": IGREJA[1], "raio_checkin_m": 100,
        })
    return comunidade, ministerio, escala, funcao


def _checkin(cliente, escala, ponto, precisao=20):
    return cliente.post(f"/escala/{escala.id}/checkin",
                        data={"latitude": ponto[0], "longitude": ponto[1], "precisao": precisao})


# --- Regras puras ----------------------------------------------------------------

def test_distancia_entre_pontos():
    assert 45 < distancia_m(*IGREJA, *PERTO) < 55
    assert 1000 < distancia_m(*IGREJA, *LONGE) < 1200


def test_avaliar_checkin():
    local = LocalCheckin("Rua", IGREJA[0], IGREJA[1], 100, "comunidade")
    assert avaliar_checkin(local, *PERTO, 20)[0] is True
    ok, distancia, mensagem = avaliar_checkin(local, *LONGE, 20)
    assert not ok and distancia > 1000 and "1,1 km" in mensagem and "não foi confirmada" in mensagem
    ok, _, mensagem = avaliar_checkin(local, *PERTO, 500)
    assert not ok and "imprecisa" in mensagem
    ok, _, mensagem = avaliar_checkin(None, *PERTO, 20)
    assert not ok and "não foi cadastrado" in mensagem


def test_hora_local_em_brasilia():
    assert hora_local(datetime(2026, 10, 3, 21, 42)) == "18:42"


# --- Fluxo pelo app ----------------------------------------------------------------

def test_checkin_dentro_do_raio_marca_presente(logged_in_client, app, db):
    with app.app_context():
        _, _, escala, funcao = _montar(logged_in_client)
        resposta = _checkin(logged_in_client, escala, PERTO)
        assert resposta.get_json()["ok"] is True
        funcao = Funcao.objects(id=funcao.id).first()
        assert funcao.status == "presente"
        assert funcao.checkin_em is not None and 40 < funcao.checkin_distancia_m < 60
        assert funcao.checkin_precisao_m == 20

        # O lider ve o horario e a distancia na escala.
        html = logged_in_client.get(f"/escala/{escala.id}").data.decode("utf-8")
        assert "Check-in de hoje" in html and "1 de 1" in html
        assert f"Check-in {hora_local(funcao.checkin_em)}" in html


def test_checkin_fora_do_raio_nao_confirma(logged_in_client, app, db):
    with app.app_context():
        _, _, escala, funcao = _montar(logged_in_client)
        dados = _checkin(logged_in_client, escala, LONGE).get_json()
        assert dados["ok"] is False and dados["distancia_m"] > 1000
        assert "não foi confirmada" in dados["mensagem"]
        funcao = Funcao.objects(id=funcao.id).first()
        assert funcao.status != "presente" and funcao.checkin_em is None


def test_checkin_so_no_dia_da_escala(logged_in_client, app, db):
    with app.app_context():
        _, _, escala, funcao = _montar(logged_in_client, dias=2)
        dados = _checkin(logged_in_client, escala, PERTO).get_json()
        assert dados["ok"] is False and "abre no dia" in dados["mensagem"]
        assert Funcao.objects(id=funcao.id).first().checkin_em is None


def test_sem_local_cadastrado_avisa(logged_in_client, app, db):
    with app.app_context():
        _, ministerio, escala, _ = _montar(logged_in_client, local=False)
        dados = _checkin(logged_in_client, escala, PERTO).get_json()
        assert dados["ok"] is False and "não foi cadastrado" in dados["mensagem"]
        html = logged_in_client.get(f"/escala/{escala.id}").data.decode("utf-8")
        assert f"/ministerio/{ministerio.id}/local-checkin" in html  # aviso pro lider cadastrar


def test_escalado_nao_marca_presente_na_mao(logged_in_client, app, db):
    with app.app_context():
        _, _, _, funcao = _montar(logged_in_client)
        logged_in_client.post(f"/escala/funcao/{funcao.id}/status", data={"status": "presente"})
        assert Funcao.objects(id=funcao.id).first().status != "presente"
        # Os outros status continuam livres.
        logged_in_client.post(f"/escala/funcao/{funcao.id}/status", data={"status": "confirmado"})
        assert Funcao.objects(id=funcao.id).first().status == "confirmado"


def test_lider_marca_outra_pessoa_presente_sem_checkin(logged_in_client, app, db):
    with app.app_context():
        _, _, escala, funcao = _montar(logged_in_client, email="carla@example.com")
        logged_in_client.post(f"/escala/funcao/{funcao.id}/status", data={"status": "presente"})
        funcao = Funcao.objects(id=funcao.id).first()
        assert funcao.status == "presente" and funcao.checkin_em is None
        html = logged_in_client.get(f"/escala/{escala.id}").data.decode("utf-8")
        assert "Marcado pelo líder" in html


def test_quem_nao_esta_escalado_nao_faz_checkin(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        _, _, escala, _ = _montar(logged_in_client)
    with sessao_isolada(app):
        assert _checkin(outro_logged_in_client, escala, PERTO).status_code == 404


def test_trocar_a_pessoa_apaga_o_checkin(logged_in_client, app, db):
    with app.app_context():
        comunidade, _, escala, funcao = _montar(logged_in_client)
        _checkin(logged_in_client, escala, PERTO)
        outro = _criar_membro(logged_in_client, comunidade.id, "Bruno", email="bruno@example.com")
        logged_in_client.post(f"/escala/funcao/{funcao.id}/remover", data={})
        _escalar(logged_in_client, funcao.id, outro.id)
        funcao = Funcao.objects(id=funcao.id).first()
        assert funcao.checkin_em is None and funcao.status != "presente"


def test_minha_escala_mostra_o_botao_no_dia(logged_in_client, app, db):
    with app.app_context():
        _, _, escala, _ = _montar(logged_in_client)
        html = logged_in_client.get(f"/minha-escala?escala={escala.id}").data.decode("utf-8")
        assert "data-checkin-botao data-url" in html and f"/escala/{escala.id}/checkin" in html
        # "Presente" saiu da lista do proprio escalado (so via check-in).
        assert 'value="presente"' not in html

        _checkin(logged_in_client, escala, PERTO)
        html = logged_in_client.get(f"/minha-escala?escala={escala.id}").data.decode("utf-8")
        assert "Presença confirmada às" in html and "data-checkin-botao data-url" not in html


def test_local_do_ministerio_vale_sobre_o_da_comunidade(logged_in_client, app, db):
    with app.app_context():
        _, ministerio, escala, _ = _montar(logged_in_client)
        assert local_do_checkin(ministerio).origem == "comunidade"
        logged_in_client.post(f"/ministerio/{ministerio.id}/local-checkin", data={
            "endereco": "Salão", "latitude": LONGE[0], "longitude": LONGE[1], "raio_checkin_m": 50,
        })
        ministerio.reload()
        local = local_do_checkin(ministerio)
        assert local.origem == "ministerio" and local.raio_m == 50
        assert _checkin(logged_in_client, escala, PERTO).get_json()["ok"] is False  # longe do salao
        logged_in_client.post(f"/ministerio/{ministerio.id}/local-checkin", data={"acao": "usar_comunidade"})
        ministerio.reload()
        assert local_do_checkin(ministerio).origem == "comunidade"


def test_so_admin_cadastra_local_da_comunidade(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade, ministerio, _, _ = _montar(logged_in_client)
    with sessao_isolada(app):
        assert outro_logged_in_client.get(f"/comunidade/{comunidade.id}/local-checkin").status_code == 404
        assert outro_logged_in_client.get(f"/ministerio/{ministerio.id}/local-checkin").status_code == 404


def test_raio_fora_dos_limites_e_recusado(logged_in_client, app, db):
    with app.app_context():
        comunidade, _, _, _ = _montar(logged_in_client, local=False)
        html = logged_in_client.post(f"/comunidade/{comunidade.id}/local-checkin", data={
            "latitude": IGREJA[0], "longitude": IGREJA[1], "raio_checkin_m": 5,
        }).data.decode("utf-8")
        assert "Use entre 30 e 2000 metros" in html
        comunidade.reload()
        assert comunidade.latitude is None


def test_busca_de_endereco(logged_in_client):
    falsa = mock.Mock()
    falsa.json.return_value = [{"display_name": "Rua A, 10, São Paulo", "lat": "-23.5", "lon": "-46.6"}]
    falsa.raise_for_status.return_value = None
    with mock.patch("app.escala.local_checkin.requests.get", return_value=falsa) as chamada:
        dados = logged_in_client.get("/local/buscar?q=Rua A 10 Sao Paulo").get_json()
    assert dados["ok"] and dados["resultados"][0]["latitude"] == -23.5
    assert "TyBenson" in chamada.call_args.kwargs["headers"]["User-Agent"]


def test_localizacao_liberada_pelo_cabecalho(client):
    assert "geolocation=(self)" in client.get("/auth/login").headers["Permissions-Policy"]
