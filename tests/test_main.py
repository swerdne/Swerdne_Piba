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
    html = response.data.decode("utf-8")
    assert any(f"{s}, ana" in html for s in ("Bom dia", "Boa tarde", "Boa noite"))


def test_dashboard_mostra_proxima_escala_em_que_o_usuario_esta_escalado(logged_in_client, app, db):
    from datetime import date, timedelta
    from app.auth.models import User
    from app.comunidade.models import Comunidade
    from app.ministerio.models import Ministerio
    from app.escala.models import Escala, Funcao, Membro

    with app.app_context():
        ana = User.objects(email="ana@example.com").first()
        comunidade = Comunidade(nome="Comunidade Teste", usuario_id=ana.id)
        comunidade.save()
        ministerio = Ministerio(nome="Louvor", comunidade_id=comunidade.id)
        ministerio.save()
        membro = Membro(comunidade_id=comunidade.id, nome="Ana", email="ana@example.com")
        membro.save()

        passada = Escala(ministerio_id=ministerio.id, nome="Culto Passado", departamento="Louvor",
                         data=date.today() - timedelta(days=7))
        passada.save()
        cancelada = Escala(ministerio_id=ministerio.id, nome="Culto Cancelado", departamento="Louvor",
                           data=date.today() + timedelta(days=1), cancelada=True)
        cancelada.save()
        proxima = Escala(ministerio_id=ministerio.id, nome="Culto de Domingo", departamento="Louvor",
                         data=date.today() + timedelta(days=3))
        proxima.save()
        depois = Escala(ministerio_id=ministerio.id, nome="Culto Depois", departamento="Louvor",
                        data=date.today() + timedelta(days=10))
        depois.save()
        for escala in (passada, cancelada, proxima, depois):
            Funcao(escala_id=escala.id, nome="Baixo", membro_id=membro.id).save()

        html = logged_in_client.get("/dashboard").data.decode("utf-8")

    assert "Culto de Domingo" in html
    assert "Sua funcao" in html and "Baixo" in html
    assert "Culto Passado" not in html
    # Cancelada nao vira "Proxima escala" -- aparece so como aviso em "Ensaios e avisos".
    card_proxima, avisos = html.split("Ensaios e avisos", 1)
    assert "Culto Cancelado" not in card_proxima
    assert "Culto Cancelado" in avisos and ">Cancelada<" in avisos
    assert "Culto Depois" not in html


def test_dashboard_sem_escala_mostra_estado_vazio(logged_in_client):
    html = logged_in_client.get("/dashboard").data.decode("utf-8")
    assert "Nenhuma escala marcada" in html


def test_dashboard_lista_comunidades_do_usuario(logged_in_client, app, db):
    from app.auth.models import User
    from app.comunidade.models import Comunidade, UsuarioComunidade
    from app.ministerio.models import Ministerio

    with app.app_context():
        ana = User.objects(email="ana@example.com").first()
        minha = Comunidade(nome="Igreja da Ana", usuario_id=ana.id)
        minha.save()
        UsuarioComunidade(usuario_id=ana.id, comunidade_id=minha.id, papel="admin").save()
        Ministerio(nome="Louvor", comunidade_id=minha.id).save()
        Ministerio(nome="Midia", comunidade_id=minha.id).save()

        participo = Comunidade(nome="Igreja Vizinha", usuario_id=ana.id)
        participo.save()
        UsuarioComunidade(usuario_id=ana.id, comunidade_id=participo.id, papel="membro").save()

        alheia = Comunidade(nome="Igreja Alheia", usuario_id=ana.id)
        alheia.save()

        html = logged_in_client.get("/dashboard").data.decode("utf-8")

    assert "Igreja da Ana" in html and "2 ministerios" in html
    assert "Igreja Vizinha" in html and "Membro" in html
    assert "Igreja Alheia" not in html


def test_marca_tybenson_by_swerdne_aparece_so_no_dashboard(logged_in_client):
    """Nome do app e "TyBenson" em todo lugar (titulo da aba, cabecalhos) --
    o credito "By Swerdne" e so informativo, aparece so na tela inicial."""
    html_dashboard = logged_in_client.get("/dashboard").data.decode("utf-8")
    assert "TyBenson" in html_dashboard
    assert "By Swerdne" in html_dashboard
    assert "PIBA Swerdne" not in html_dashboard


def test_dashboard_agrupa_notificacoes_por_escala(logged_in_client, app, db):
    """Notificacoes com a mesma escala_id devem aparecer juntas, sob um
    cabecalho com o nome da escala (ver main.routes._agrupar_notificacoes) --
    nao mais uma lista plana."""
    from app.notificacoes import Notificacao
    from app.auth.models import User
    from app.comunidade.models import Comunidade
    from app.ministerio.models import Ministerio
    from app.escala.models import Escala

    with app.app_context():
        ana = User.objects(email="ana@example.com").first()
        comunidade = Comunidade(nome="Comunidade Teste", usuario_id=ana.id)
        comunidade.save()
        ministerio = Ministerio(nome="Ministerio Teste", comunidade_id=comunidade.id)
        ministerio.save()
        escala_a = Escala(ministerio_id=ministerio.id, nome="Culto A", departamento="Louvor")
        escala_a.save()
        escala_b = Escala(ministerio_id=ministerio.id, nome="Culto B", departamento="Louvor")
        escala_b.save()

        Notificacao(usuario_id=ana.id, titulo="Primeira", mensagem="m1", escala_id=escala_a.id, tipo="escalado").save()
        Notificacao(usuario_id=ana.id, titulo="Segunda", mensagem="m2", escala_id=escala_a.id, tipo="confirmado").save()
        Notificacao(usuario_id=ana.id, titulo="Terceira", mensagem="m3", escala_id=escala_b.id, tipo="escalado").save()

        resposta = logged_in_client.get("/dashboard")
        html = resposta.data.decode("utf-8")

        assert resposta.status_code == 200
        assert html.count("Culto A") == 1
        assert html.count("Culto B") == 1
        assert "Primeira" in html and "Segunda" in html and "Terceira" in html


def test_salvar_tema(logged_in_client, app, db):
    response = logged_in_client.post("/perfil/tema", data={"tema": "escuro"}, follow_redirects=True)
    assert response.status_code == 200

    with app.app_context():
        from app.auth.models import User
        user = User.objects(email="ana@example.com").first()
        assert user.theme == "escuro"


def test_salvar_tema_invalido_nao_altera(logged_in_client, app, db):
    logged_in_client.post("/perfil/tema", data={"tema": "cor-inexistente"}, follow_redirects=True)

    with app.app_context():
        from app.auth.models import User
        user = User.objects(email="ana@example.com").first()
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
        user = User.objects(email="ana@example.com").first()
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
        user = User.objects(email="ana@example.com").first()
        assert user.check_password("senha123")


def test_trocar_senha_com_confirmacao_diferente_nao_altera(logged_in_client, app, db):
    logged_in_client.post(
        "/perfil/senha",
        data={"senha_atual": "senha123", "nova_senha": "novaSenha456", "confirmar_senha": "outra-coisa"},
        follow_redirects=True,
    )

    with app.app_context():
        from app.auth.models import User
        user = User.objects(email="ana@example.com").first()
        assert user.check_password("senha123")


def test_definir_senha_em_conta_so_google_nao_exige_senha_atual(app, db):
    """Conta criada so via Google (sem password_hash) nao tem senha atual pra
    conferir -- o POST em /perfil/senha define a primeira senha direto."""
    with app.app_context():
        from app.auth.models import User
        user = User(google_id="google-123", email="so-google@example.com", name="So Google", email_confirmado=True)
        user.save()
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
        user = User.objects(email="so-google@example.com").first()
        assert user.check_password("primeiraSenha1")


def test_salvar_nome(logged_in_client, app, db):
    response = logged_in_client.post("/perfil/nome", data={"nome": "Ana Souza"}, follow_redirects=True)
    assert response.status_code == 200
    assert "Nome atualizado".encode() in response.data

    with app.app_context():
        from app.auth.models import User
        user = User.objects(email="ana@example.com").first()
        assert user.name == "Ana Souza"


def test_salvar_nome_vazio_nao_altera(logged_in_client, app, db):
    logged_in_client.post("/perfil/nome", data={"nome": ""}, follow_redirects=True)

    with app.app_context():
        from app.auth.models import User
        user = User.objects(email="ana@example.com").first()
        assert user.name != ""


def test_baixar_dados_devolve_json_com_dados_da_conta(logged_in_client):
    response = logged_in_client.get("/perfil/dados")
    assert response.status_code == 200
    assert "attachment" in response.headers["Content-Disposition"]

    dados = response.get_json()
    assert dados["email"] == "ana@example.com"
    assert "password_hash" not in dados


def test_desconectar_google_com_senha_funciona(logged_in_client, app, db):
    # sessao_isolada (nao so p/ simular 2 contas, ver conftest.py) tambem e
    # necessaria aqui: sem identity map (diferente do SQLAlchemy), o
    # objeto que a rota ve como current_user (cacheado por Flask-Login no
    # app_context, ver docstring de sessao_isolada) e uma instancia Python
    # DIFERENTE da que este teste busca e salva -- sem forcar um app_context
    # novo antes do POST, a rota enxergaria o valor antigo em memoria.
    from tests.conftest import sessao_isolada

    with sessao_isolada(app):
        from app.auth.models import User
        user = User.objects(email="ana@example.com").first()
        user.google_id = "google-ana-123"
        user.save()

    with sessao_isolada(app):
        response = logged_in_client.post("/perfil/google/desconectar", follow_redirects=True)
        assert "desconectada".encode() in response.data

    with app.app_context():
        from app.auth.models import User
        user = User.objects(email="ana@example.com").first()
        assert user.google_id is None


def test_desconectar_google_sem_senha_e_bloqueado(app, db):
    """Sem senha, desconectar o Google tiraria todo acesso a conta -- a rota
    tem que recusar mesmo que o POST seja montado a mao (a tela ja esconde
    esse botao nesse caso)."""
    with app.app_context():
        from app.auth.models import User
        user = User(google_id="google-so-1", email="so-google3@example.com", name="So Google", email_confirmado=True)
        user.save()
        user_id = user.id

    cliente = app.test_client()
    with cliente.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True

    response = cliente.post("/perfil/google/desconectar", follow_redirects=True)
    assert "Defina uma senha".encode() in response.data

    with app.app_context():
        from app.auth.models import User
        user = User.objects(email="so-google3@example.com").first()
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
        user = User.objects(email="ana@example.com").first()
        assert user.foto_perfil.startswith("/imagem/")


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
