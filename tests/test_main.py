"""Testes do modulo main."""

import io


def test_index_sem_login_redireciona_para_login(client):
    response = client.get("/", follow_redirects=True)
    assert response.status_code == 200
    assert "Entrar".encode() in response.data


def test_healthz_nao_exige_login_e_consulta_o_banco(client):
    # publico de proposito -- e o endpoint usado por ping externo de
    # keep-alive (cron-job.org etc.), que nao tem como autenticar.
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.data == b"ok"


def test_dashboard_com_login(logged_in_client):
    response = logged_in_client.get("/dashboard")
    assert response.status_code == 200
    assert "Ola, ana".encode() in response.data


def test_salvar_tema(logged_in_client, app, db):
    response = logged_in_client.post("/perfil/tema", data={"tema": "escuro"}, follow_redirects=True)
    assert response.status_code == 200

    with app.app_context():
        from app.auth.models import User
        user = User.query.filter_by(email="ana@example.com").first()
        assert user.theme == "escuro"


def test_salvar_tema_invalido_nao_altera(logged_in_client, app, db):
    logged_in_client.post("/perfil/tema", data={"tema": "cor-inexistente"}, follow_redirects=True)

    with app.app_context():
        from app.auth.models import User
        user = User.query.filter_by(email="ana@example.com").first()
        assert user.theme == "indigo"


def test_upload_foto_rejeita_extensao_invalida(logged_in_client):
    dados = {
        "foto": (io.BytesIO(b"conteudo-falso"), "arquivo.txt"),
    }
    response = logged_in_client.post(
        "/perfil/foto", data=dados, content_type="multipart/form-data", follow_redirects=True
    )
    assert response.status_code == 200
    assert "JPG ou PNG".encode() in response.data


def test_upload_foto_valida_salva_avatar(logged_in_client, app, db):
    imagem_png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0"
        b"\x00\x00\x03\x01\x01\x00\x18\xdd\x8d\xb0\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    dados = {"foto": (io.BytesIO(imagem_png), "foto.png")}
    response = logged_in_client.post(
        "/perfil/foto", data=dados, content_type="multipart/form-data", follow_redirects=True
    )
    assert response.status_code == 200

    with app.app_context():
        from app.auth.models import User
        user = User.query.filter_by(email="ana@example.com").first()
        assert user.foto_perfil.startswith("/static/uploads/avatars/user_")


def test_chat_mock_responde(logged_in_client):
    response = logged_in_client.post(
        "/chat", json={"mensagem": "como faco login?", "historico": []}
    )
    assert response.status_code == 200
    dados = response.get_json()
    assert "Google" in dados["resposta"] or "senha" in dados["resposta"]


def test_chat_sem_mensagem_retorna_erro(logged_in_client):
    response = logged_in_client.post("/chat", json={"mensagem": "", "historico": []})
    assert response.status_code == 400


def test_chat_explica_tutorial(logged_in_client):
    response = logged_in_client.post(
        "/chat", json={"mensagem": "como funciona o tutorial?", "historico": []}
    )
    assert response.status_code == 200
    assert "tutorial" in response.get_json()["resposta"].lower()


def test_chat_explica_comunidade_e_ministerio(logged_in_client):
    r1 = logged_in_client.post("/chat", json={"mensagem": "o que e uma comunidade?", "historico": []})
    assert "Comunidade" in r1.get_json()["resposta"]

    r2 = logged_in_client.post("/chat", json={"mensagem": "pra que serve um ministerio?", "historico": []})
    assert "Ministerio" in r2.get_json()["resposta"]
