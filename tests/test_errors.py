"""Testes das paginas de erro estilizadas (404, 403, 500 e fallback generico)."""
from flask import abort


def test_pagina_404_estilizada_para_visitante_anonimo(client):
    response = client.get("/rota-que-nunca-vai-existir")

    assert response.status_code == 404
    assert "Erro 404".encode() in response.data
    assert "Pagina nao encontrada".encode() in response.data
    assert "Ir para o Login".encode() in response.data


def test_pagina_404_para_usuario_logado_mostra_botao_de_dashboard(logged_in_client):
    response = logged_in_client.get("/rota-que-nunca-vai-existir")

    assert response.status_code == 404
    assert "Voltar para o Dashboard".encode() in response.data


def test_pagina_403_estilizada(app, client):
    @app.route("/_teste-erro-403-proposital")
    def _rota_teste_403():
        abort(403)

    response = client.get("/_teste-erro-403-proposital")

    assert response.status_code == 403
    assert "Erro 403".encode() in response.data
    assert "Sem permissao".encode() in response.data


def test_pagina_erro_generica_para_codigo_sem_handler_especifico(app, client):
    @app.route("/_teste-erro-400-proposital")
    def _rota_teste_400():
        abort(400)

    response = client.get("/_teste-erro-400-proposital")

    assert response.status_code == 400
    assert "Erro 400".encode() in response.data


def test_pagina_500_nao_derruba_a_app_e_mostra_pagina_estilizada(app, client):
    @app.route("/_teste-erro-500-proposital")
    def _rota_teste_500():
        raise RuntimeError("erro proposital pra testar a pagina de 500")

    # Simula o comportamento de producao: sem isso, TESTING=True (config da
    # app de teste) faz o Flask/test client deixarem a excecao subir direto
    # pro teste em vez de converte-la numa resposta 500 de verdade.
    app.config["PROPAGATE_EXCEPTIONS"] = False
    app.testing = False
    client.testing = False

    response = client.get("/_teste-erro-500-proposital")

    assert response.status_code == 500
    assert "Erro 500".encode() in response.data
    assert "Algo deu errado no servidor".encode() in response.data


def test_pagina_500_cai_no_fallback_minimo_se_o_banco_tambem_estiver_fora_do_ar(app, client, monkeypatch):
    """erro.html estende base.html, que consulta o banco via current_user
    (context processor de tema) -- se o banco estiver de fato inacessivel,
    essa propria renderizacao falha. Sem um fallback que nao depende de
    banco nenhum, o usuario cairia na tela crua e sem estilo do Werkzeug."""
    import app.errors as errors_module

    def _render_quebrado(*args, **kwargs):
        raise RuntimeError("banco indisponivel, nem a pagina de erro renderiza")

    monkeypatch.setattr(errors_module, "render_template", _render_quebrado)

    @app.route("/_teste-erro-500-com-banco-fora-do-ar")
    def _rota_teste_500_fallback():
        raise RuntimeError("erro proposital")

    app.config["PROPAGATE_EXCEPTIONS"] = False
    app.testing = False
    client.testing = False

    response = client.get("/_teste-erro-500-com-banco-fora-do-ar")

    assert response.status_code == 500
    assert "Algo deu errado no servidor".encode() in response.data
    assert "Voltar para o inicio".encode() in response.data
