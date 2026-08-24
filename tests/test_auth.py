"""Testes do modulo auth."""
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


# --- Cadastro tradicional (sem confirmacao de e-mail) -----------------------

def test_registro_loga_direto(client, app, db):
    response = client.post("/auth/register", data=_dados_registro(), follow_redirects=True)

    assert response.status_code == 200
    # loga direto, sem passar por link de confirmacao (ver auth/routes.py::register)
    assert client.get("/auth/sessao-atual").get_json()["usuario_id"] is not None

    with app.app_context():
        usuario = User.query.filter_by(email="carla@example.com").first()
        assert usuario is not None
        assert usuario.email_confirmado is True


def test_login_funciona_apos_registro_e_logout(client, app, db):
    client.post("/auth/register", data=_dados_registro(), follow_redirects=True)
    client.get("/auth/logout")
    assert client.get("/auth/sessao-atual").get_json() == {"usuario_id": None}

    response = client.post(
        "/auth/login", data={"email": "carla@example.com", "password": "senha123"}, follow_redirects=True
    )
    assert response.status_code == 200
    assert client.get("/auth/sessao-atual").get_json()["usuario_id"] is not None


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
    """Simula duas abas do MESMO navegador: registra a conta A (loga direto),
    guarda o id, depois registra a conta B usando o MESMO client (cookie jar
    compartilhado, como duas abas reais) -- /sessao-atual deve refletir a
    troca, e e justamente essa divergencia que o JS de vigiaTrocaDeSessao
    detecta."""
    from tests.conftest import _registrar

    _registrar(client, "ana", "ana@example.com")
    with app.app_context():
        id_ana = User.query.filter_by(email="ana@example.com").first().id

    _registrar(client, "bruno", "bruno@example.com")
    with app.app_context():
        id_bruno = User.query.filter_by(email="bruno@example.com").first().id

    assert id_ana != id_bruno
    response = client.get("/auth/sessao-atual")
    assert response.get_json() == {"usuario_id": id_bruno}
