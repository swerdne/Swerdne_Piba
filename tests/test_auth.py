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


# --- Redefinicao de senha por e-mail ("esqueci minha senha") ----------------

def test_esqueci_senha_gera_token_para_conta_com_senha(client, app, db):
    client.post("/auth/register", data=_dados_registro(), follow_redirects=True)

    response = client.post("/auth/esqueci-senha", data={"email": "carla@example.com"}, follow_redirects=True)
    assert response.status_code == 200
    assert "enviamos um link".encode() in response.data

    with app.app_context():
        usuario = User.query.filter_by(email="carla@example.com").first()
        assert usuario.token_redefinicao_senha is not None
        assert usuario.token_redefinicao_expira_em is not None


def test_esqueci_senha_com_email_inexistente_mostra_mesma_mensagem(client):
    """Nunca revela se o e-mail tem conta ou nao (anti-enumeration) -- a
    mensagem e identica ao caso de sucesso."""
    response = client.post(
        "/auth/esqueci-senha", data={"email": "ninguem@example.com"}, follow_redirects=True
    )
    assert "enviamos um link".encode() in response.data


def test_esqueci_senha_conta_so_google_nao_gera_token(app, db):
    with app.app_context():
        usuario = User(google_id="google-999", email="so-google2@example.com", name="So Google", email_confirmado=True)
        db.session.add(usuario)
        db.session.commit()

    cliente = app.test_client()
    cliente.post("/auth/esqueci-senha", data={"email": "so-google2@example.com"}, follow_redirects=True)

    with app.app_context():
        usuario = User.query.filter_by(email="so-google2@example.com").first()
        assert usuario.token_redefinicao_senha is None


def test_redefinir_senha_com_token_valido(client, app, db):
    client.post("/auth/register", data=_dados_registro(), follow_redirects=True)
    client.post("/auth/esqueci-senha", data={"email": "carla@example.com"}, follow_redirects=True)

    with app.app_context():
        token = User.query.filter_by(email="carla@example.com").first().token_redefinicao_senha

    response = client.post(
        f"/auth/redefinir-senha/{token}",
        data={"nova_senha": "outraSenha789", "confirmar_senha": "outraSenha789"},
        follow_redirects=True,
    )
    assert "Senha redefinida".encode() in response.data

    with app.app_context():
        usuario = User.query.filter_by(email="carla@example.com").first()
        assert usuario.check_password("outraSenha789")
        # Uso unico -- o token e limpo apos a troca
        assert usuario.token_redefinicao_senha is None


def test_redefinir_senha_com_token_invalido_redireciona(client):
    response = client.get("/auth/redefinir-senha/token-que-nao-existe", follow_redirects=True)
    assert "invalido ou ja expirou".encode() in response.data


def test_redefinir_senha_token_nao_reutilizavel(client, app, db):
    client.post("/auth/register", data=_dados_registro(), follow_redirects=True)
    client.post("/auth/esqueci-senha", data={"email": "carla@example.com"}, follow_redirects=True)

    with app.app_context():
        token = User.query.filter_by(email="carla@example.com").first().token_redefinicao_senha

    client.post(
        f"/auth/redefinir-senha/{token}",
        data={"nova_senha": "outraSenha789", "confirmar_senha": "outraSenha789"},
        follow_redirects=True,
    )
    # Segunda tentativa com o MESMO token (ja consumido) deve falhar
    response = client.post(
        f"/auth/redefinir-senha/{token}",
        data={"nova_senha": "terceiraSenha000", "confirmar_senha": "terceiraSenha000"},
        follow_redirects=True,
    )
    assert "invalido ou ja expirou".encode() in response.data
