"""Testes do modulo auth."""
from app.auth.models import User


def test_register_page(client):
    response = client.get("/auth/register")
    assert response.status_code == 200


def test_password_hashing(app, db):
    user = User(username="teste", email="teste@example.com")
    user.set_password("senha123")
    assert user.check_password("senha123")
    assert not user.check_password("errada")


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
    """Simula duas abas do MESMO navegador: registra a conta A, guarda o id,
    depois registra a conta B usando o MESMO client (cookie jar compartilhado,
    como duas abas reais) -- /sessao-atual deve refletir a troca, e e
    justamente essa divergencia que o JS de vigiaTrocaDeSessao detecta."""
    client.post(
        "/auth/register",
        data={"username": "ana", "email": "ana@example.com", "password": "senha123", "confirm": "senha123"},
        follow_redirects=True,
    )
    with app.app_context():
        id_ana = User.query.filter_by(email="ana@example.com").first().id

    client.post(
        "/auth/register",
        data={"username": "bruno", "email": "bruno@example.com", "password": "senha123", "confirm": "senha123"},
        follow_redirects=True,
    )
    with app.app_context():
        id_bruno = User.query.filter_by(email="bruno@example.com").first().id

    assert id_ana != id_bruno
    response = client.get("/auth/sessao-atual")
    assert response.get_json() == {"usuario_id": id_bruno}
