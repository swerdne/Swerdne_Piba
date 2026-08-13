"""Testes do modulo auth."""
from datetime import datetime, timedelta, timezone

from app.auth.models import User


def _dados_registro(**overrides):
    dados = {"username": "carla", "email": "carla@example.com", "password": "senha123", "confirm": "senha123"}
    dados.update(overrides)
    return dados


def test_register_page(client):
    response = client.get("/auth/register")
    assert response.status_code == 200


def test_password_hashing(app, db):
    user = User(username="teste", email="teste@example.com")
    user.set_password("senha123")
    assert user.check_password("senha123")
    assert not user.check_password("errada")


# --- Confirmacao de e-mail no cadastro tradicional --------------------------

def test_registro_nao_loga_direto_pede_confirmacao(client, app, db):
    response = client.post("/auth/register", data=_dados_registro(), follow_redirects=True)
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "Falta pouco" in html
    assert "carla@example.com" in html
    # nao logou: sessao-atual continua anonima
    assert client.get("/auth/sessao-atual").get_json() == {"usuario_id": None}

    with app.app_context():
        usuario = User.query.filter_by(email="carla@example.com").first()
        assert usuario is not None
        assert usuario.email_confirmado is False
        assert usuario.token_confirmacao is not None
        assert usuario.token_confirmacao_expira_em is not None


def test_confirmar_email_loga_e_redireciona_para_dashboard(client, app, db):
    client.post("/auth/register", data=_dados_registro(), follow_redirects=True)
    with app.app_context():
        usuario = User.query.filter_by(email="carla@example.com").first()
        token = usuario.token_confirmacao

    response = client.get(f"/auth/confirmar-email/{token}", follow_redirects=True)
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "confirmado com sucesso" in html.lower()
    assert client.get("/auth/sessao-atual").get_json()["usuario_id"] is not None

    with app.app_context():
        usuario = User.query.filter_by(email="carla@example.com").first()
        assert usuario.email_confirmado is True
        assert usuario.token_confirmacao is None


def test_confirmar_email_token_invalido_nao_loga(client):
    response = client.get("/auth/confirmar-email/token-que-nao-existe", follow_redirects=True)
    assert response.status_code == 200
    assert client.get("/auth/sessao-atual").get_json() == {"usuario_id": None}


def test_confirmar_email_token_expirado_oferece_reenvio(client, app, db):
    client.post("/auth/register", data=_dados_registro(), follow_redirects=True)
    with app.app_context():
        usuario = User.query.filter_by(email="carla@example.com").first()
        token = usuario.token_confirmacao
        usuario.token_confirmacao_expira_em = datetime.now(timezone.utc) - timedelta(hours=1)
        db.session.commit()

    response = client.get(f"/auth/confirmar-email/{token}", follow_redirects=True)
    html = response.data.decode("utf-8")

    assert "expirou" in html.lower()
    assert client.get("/auth/sessao-atual").get_json() == {"usuario_id": None}


def test_login_bloqueado_sem_confirmar_email(client, app, db):
    client.post("/auth/register", data=_dados_registro(), follow_redirects=True)

    response = client.post(
        "/auth/login", data={"email": "carla@example.com", "password": "senha123"}, follow_redirects=True
    )
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "ainda nao foi confirmada" in html.lower() or "falta pouco" in html.lower()
    assert client.get("/auth/sessao-atual").get_json() == {"usuario_id": None}


def test_login_funciona_normalmente_apos_confirmar(client, app, db):
    from tests.conftest import _registrar_e_confirmar

    _registrar_e_confirmar(client, app, "carla", "carla@example.com")
    client.get("/auth/logout")
    assert client.get("/auth/sessao-atual").get_json() == {"usuario_id": None}

    response = client.post(
        "/auth/login", data={"email": "carla@example.com", "password": "senha123"}, follow_redirects=True
    )
    assert response.status_code == 200
    assert client.get("/auth/sessao-atual").get_json()["usuario_id"] is not None


def test_reenviar_confirmacao_gera_token_novo(client, app, db):
    client.post("/auth/register", data=_dados_registro(), follow_redirects=True)
    with app.app_context():
        usuario = User.query.filter_by(email="carla@example.com").first()
        token_antigo = usuario.token_confirmacao

    response = client.post("/auth/reenviar-confirmacao", data={"email": "carla@example.com"}, follow_redirects=True)
    assert response.status_code == 200

    with app.app_context():
        usuario = User.query.filter_by(email="carla@example.com").first()
        assert usuario.token_confirmacao != token_antigo
        assert usuario.token_confirmacao is not None


def test_reenviar_confirmacao_ja_confirmado(client, app, db):
    from tests.conftest import _registrar_e_confirmar

    _registrar_e_confirmar(client, app, "carla", "carla@example.com")

    response = client.post("/auth/reenviar-confirmacao", data={"email": "carla@example.com"}, follow_redirects=True)
    html = response.data.decode("utf-8")
    assert "ja esta confirmado" in html.lower()


def test_reenviar_confirmacao_email_inexistente(client):
    response = client.post(
        "/auth/reenviar-confirmacao", data={"email": "ninguem@example.com"}, follow_redirects=True
    )
    html = response.data.decode("utf-8")
    assert "nao encontramos" in html.lower()


def test_cadastro_recusa_dominio_sem_mx(client, app, monkeypatch):
    """VALIDAR_DOMINIO_EMAIL fica desligado por padrao em teste (sem rede) --
    liga so aqui e simula um dominio que nao aceita e-mail."""
    app.config["VALIDAR_DOMINIO_EMAIL"] = True
    monkeypatch.setattr("app.auth.forms.dominio_aceita_email", lambda dominio: False)

    response = client.post(
        "/auth/register", data=_dados_registro(email="carla@dominio-que-nao-existe-de-verdade.invalido"),
        follow_redirects=True,
    )
    html = response.data.decode("utf-8")

    assert "nao conseguimos confirmar" in html.lower()
    with app.app_context():
        assert User.query.filter_by(email="carla@dominio-que-nao-existe-de-verdade.invalido").first() is None


# --- Deteccao de troca de sessao entre abas (ver static/js/main.js) ---------

def test_sessao_atual_sem_login_devolve_usuario_nulo(client):
    response = client.get("/auth/sessao-atual")
    assert response.status_code == 200
    assert response.get_json() == {"usuario_id": None}


def test_sessao_atual_logado_devolve_id_do_usuario(logged_in_client, app, db):
    with app.app_context():
        usuario = User.query.filter_by(email="ana@example.com").first()
        response = logged_in_client.get("/auth/sessao-atual")
        assert response.status_code == 200
        assert response.get_json() == {"usuario_id": usuario.id}


def test_sessao_atual_reflete_login_de_outra_conta_no_mesmo_cookie_jar(client, app, db):
    """Simula duas abas do MESMO navegador: confirma a conta A (loga), guarda
    o id, depois confirma a conta B usando o MESMO client (cookie jar
    compartilhado, como duas abas reais) -- /sessao-atual deve refletir a
    troca, e e justamente essa divergencia que o JS de vigiaTrocaDeSessao
    detecta. Registro sozinho nao loga mais ninguem (ver
    app/auth/routes.py::register) -- e o clique no link de confirmacao que
    loga, entao o teste precisa completar os dois fluxos, nao so os POSTs."""
    from tests.conftest import _registrar_e_confirmar

    _registrar_e_confirmar(client, app, "ana", "ana@example.com")
    with app.app_context():
        id_ana = User.query.filter_by(email="ana@example.com").first().id

    _registrar_e_confirmar(client, app, "bruno", "bruno@example.com")
    with app.app_context():
        id_bruno = User.query.filter_by(email="bruno@example.com").first().id

    assert id_ana != id_bruno
    response = client.get("/auth/sessao-atual")
    assert response.get_json() == {"usuario_id": id_bruno}
