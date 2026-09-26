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


def test_service_worker_servido_na_raiz_sem_login(client):
    # precisa ser publico e na raiz (nao /static/js/) pro escopo do service
    # worker cobrir o site inteiro -- exigido pro PWA ser instalavel.
    response = client.get("/service-worker.js")
    assert response.status_code == 200
    assert "javascript" in response.content_type


def test_dashboard_com_login(logged_in_client):
    response = logged_in_client.get("/dashboard")
    assert response.status_code == 200
    assert "Ola, ana".encode() in response.data


def test_marca_tybenson_by_swerdne_aparece_so_no_dashboard(logged_in_client):
    """Nome do app e "TyBenson" em todo lugar (titulo da aba, cabecalhos) --
    o credito "By Swerdne" e so informativo, aparece so na tela inicial."""
    html_dashboard = logged_in_client.get("/dashboard").data.decode("utf-8")
    assert "TyBenson" in html_dashboard
    assert "By Swerdne" in html_dashboard
    assert "PIBA Swerdne" not in html_dashboard


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


def test_trocar_senha_com_senha_atual_correta(logged_in_client, app, db):
    response = logged_in_client.post(
        "/perfil/senha",
        data={"senha_atual": "senha123", "nova_senha": "novaSenha456", "confirmar_senha": "novaSenha456"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Senha atualizada".encode() in response.data

    with app.app_context():
        from app.auth.models import User
        user = User.query.filter_by(email="ana@example.com").first()
        assert user.check_password("novaSenha456")
        assert not user.check_password("senha123")


def test_trocar_senha_com_senha_atual_errada_nao_altera(logged_in_client, app, db):
    response = logged_in_client.post(
        "/perfil/senha",
        data={"senha_atual": "senha-errada", "nova_senha": "novaSenha456", "confirmar_senha": "novaSenha456"},
        follow_redirects=True,
    )
    assert "Senha atual incorreta".encode() in response.data

    with app.app_context():
        from app.auth.models import User
        user = User.query.filter_by(email="ana@example.com").first()
        assert user.check_password("senha123")


def test_trocar_senha_com_confirmacao_diferente_nao_altera(logged_in_client, app, db):
    logged_in_client.post(
        "/perfil/senha",
        data={"senha_atual": "senha123", "nova_senha": "novaSenha456", "confirmar_senha": "outra-coisa"},
        follow_redirects=True,
    )

    with app.app_context():
        from app.auth.models import User
        user = User.query.filter_by(email="ana@example.com").first()
        assert user.check_password("senha123")


def test_definir_senha_em_conta_so_google_nao_exige_senha_atual(app, db):
    """Conta criada so via Google (sem password_hash) nao tem senha atual pra
    conferir -- o POST em /perfil/senha define a primeira senha direto."""
    with app.app_context():
        from app.auth.models import User
        user = User(google_id="google-123", email="so-google@example.com", name="So Google", email_confirmado=True)
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    cliente = app.test_client()
    with cliente.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True

    response = cliente.post(
        "/perfil/senha",
        data={"nova_senha": "primeiraSenha1", "confirmar_senha": "primeiraSenha1"},
        follow_redirects=True,
    )
    assert "Senha definida".encode() in response.data

    with app.app_context():
        from app.auth.models import User
        user = User.query.filter_by(email="so-google@example.com").first()
        assert user.check_password("primeiraSenha1")


def test_salvar_nome(logged_in_client, app, db):
    response = logged_in_client.post("/perfil/nome", data={"nome": "Ana Souza"}, follow_redirects=True)
    assert response.status_code == 200
    assert "Nome atualizado".encode() in response.data

    with app.app_context():
        from app.auth.models import User
        user = User.query.filter_by(email="ana@example.com").first()
        assert user.name == "Ana Souza"


def test_salvar_nome_vazio_nao_altera(logged_in_client, app, db):
    logged_in_client.post("/perfil/nome", data={"nome": ""}, follow_redirects=True)

    with app.app_context():
        from app.auth.models import User
        user = User.query.filter_by(email="ana@example.com").first()
        assert user.name != ""


def test_baixar_dados_devolve_json_com_dados_da_conta(logged_in_client):
    response = logged_in_client.get("/perfil/dados")
    assert response.status_code == 200
    assert "attachment" in response.headers["Content-Disposition"]

    dados = response.get_json()
    assert dados["email"] == "ana@example.com"
    assert "password_hash" not in dados


def test_desconectar_google_com_senha_funciona(logged_in_client, app, db):
    # Sem `with app.app_context()` aninhado de proposito: a fixture `app` ja
    # mantem um app_context ativo o teste inteiro, e a request abaixo reusa
    # esse MESMO contexto (mesma sessao/identity map do SQLAlchemy). Um
    # `with app.app_context()` aninhado aqui criaria uma sessao a parte --
    # o commit feito nela nao apareceria pro objeto "ana" que a request ja
    # tem cacheado, e a rota veria google_id desatualizado (None).
    from app.auth.models import User
    user = User.query.filter_by(email="ana@example.com").first()
    user.google_id = "google-ana-123"
    db.session.commit()

    response = logged_in_client.post("/perfil/google/desconectar", follow_redirects=True)
    assert "desconectada".encode() in response.data

    with app.app_context():
        from app.auth.models import User
        user = User.query.filter_by(email="ana@example.com").first()
        assert user.google_id is None


def test_desconectar_google_sem_senha_e_bloqueado(app, db):
    """Sem senha, desconectar o Google tiraria todo acesso a conta -- a rota
    tem que recusar mesmo que o POST seja montado a mao (a tela ja esconde
    esse botao nesse caso)."""
    with app.app_context():
        from app.auth.models import User
        user = User(google_id="google-so-1", email="so-google3@example.com", name="So Google", email_confirmado=True)
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    cliente = app.test_client()
    with cliente.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True

    response = cliente.post("/perfil/google/desconectar", follow_redirects=True)
    assert "Defina uma senha".encode() in response.data

    with app.app_context():
        from app.auth.models import User
        user = User.query.filter_by(email="so-google3@example.com").first()
        assert user.google_id == "google-so-1"


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


def test_chat_explica_hierarquia_de_papeis(logged_in_client):
    response = logged_in_client.post(
        "/chat", json={"mensagem": "qual a diferenca entre super admin e lider de ministerio?", "historico": []}
    )
    resposta = response.get_json()["resposta"]
    assert "Super Admin" in resposta
    assert "Lider de Ministerio" in resposta


def test_chat_explica_disponibilidade_e_calendario(logged_in_client):
    r1 = logged_in_client.post("/chat", json={"mensagem": "como funciona a disponibilidade?", "historico": []})
    assert "disponibilidade" in r1.get_json()["resposta"].lower()

    r2 = logged_in_client.post("/chat", json={"mensagem": "tem um calendario?", "historico": []})
    assert "Calendario" in r2.get_json()["resposta"]


def test_chat_responde_saudacao_e_agradecimento(logged_in_client):
    r1 = logged_in_client.post("/chat", json={"mensagem": "oi", "historico": []})
    assert "Oi!" in r1.get_json()["resposta"]

    r2 = logged_in_client.post("/chat", json={"mensagem": "muito obrigado!", "historico": []})
    assert "Disponha" in r2.get_json()["resposta"]
