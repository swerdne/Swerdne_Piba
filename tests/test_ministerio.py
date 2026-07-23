"""Testes do modulo ministerio."""
from app.ministerio.models import Ministerio
from tests.conftest import sessao_isolada
from tests.test_escala import _criar_comunidade, _criar_ministerio, _criar_escala


def test_ministerio_sem_login_redireciona(client):
    # @login_required intercepta antes de chegar no get_or_404, entao nem
    # precisa existir um ministerio de verdade com esse id.
    response = client.get("/ministerio/1", follow_redirects=False)
    assert response.status_code == 302


def test_criar_ministerio_aparece_na_comunidade(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id, "Ministerio de Louvor")
        assert ministerio is not None

        response = logged_in_client.get(f"/comunidade/{comunidade.id}")
        assert "Ministerio de Louvor" in response.data.decode("utf-8")


def test_criar_ministerio_sem_nome_mostra_erro(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        total_antes = Ministerio.query.count()
        logged_in_client.post(
            f"/ministerio/comunidade/{comunidade.id}/nova",
            data={"nome": "", "descricao": ""},
            follow_redirects=True,
        )
        assert Ministerio.query.count() == total_antes


def test_editar_ministerio_atualiza_nome(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id, "Nome Antigo")
        response = logged_in_client.post(
            f"/ministerio/{ministerio.id}/editar",
            data={"nome": "Nome Novo", "descricao": "Descricao nova"},
            follow_redirects=True,
        )
        assert response.status_code == 200
        atualizado = db.session.get(Ministerio, ministerio.id)
        assert atualizado.nome == "Nome Novo"
        assert atualizado.descricao == "Descricao nova"


def test_escala_criada_dentro_do_ministerio_aparece_na_area_dele(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        escala = _criar_escala(logged_in_client, ministerio.id, "Culto de Domingo")

        response = logged_in_client.get(f"/ministerio/{ministerio.id}")
        assert response.status_code == 200
        assert "Culto de Domingo" in response.data.decode("utf-8")
        assert escala.ministerio_id == ministerio.id


# --- Calendario ---------------------------------------------------------------

def test_calendario_mostra_cor_no_dia_da_escala(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        escala = _criar_escala(
            logged_in_client, ministerio.id, "Culto de Domingo", data="2026-08-09", horario="19:00"
        )

        response = logged_in_client.get(f"/ministerio/{ministerio.id}?ano=2026&mes=8")
        html = response.data.decode("utf-8")
        assert response.status_code == 200
        assert "agosto de 2026" in html
        # a escala aparece na legenda do calendario com sua data
        assert "Culto de Domingo" in html
        assert "09/08" in html


def test_calendario_navegacao_mes_anterior_proximo_com_rollover(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)

        # Janeiro: mes anterior deve cair em dezembro do ano anterior
        response = logged_in_client.get(f"/ministerio/{ministerio.id}?ano=2026&mes=1")
        html = response.data.decode("utf-8")
        assert f"/ministerio/{ministerio.id}?ano=2025&amp;mes=12" in html
        assert f"/ministerio/{ministerio.id}?ano=2026&amp;mes=2" in html

        # Dezembro: proximo mes deve cair em janeiro do ano seguinte
        response = logged_in_client.get(f"/ministerio/{ministerio.id}?ano=2026&mes=12")
        html = response.data.decode("utf-8")
        assert f"/ministerio/{ministerio.id}?ano=2026&amp;mes=11" in html
        assert f"/ministerio/{ministerio.id}?ano=2027&amp;mes=1" in html


def test_escala_fora_do_mes_nao_aparece_na_legenda(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        _criar_escala(logged_in_client, ministerio.id, "Culto Distante", data="2026-12-25", horario="")

        response = logged_in_client.get(f"/ministerio/{ministerio.id}?ano=2026&mes=8")
        html = response.data.decode("utf-8")
        assert "Nenhuma escala com data neste mes" in html


# --- Pagina de calendario completa ---------------------------------------------

def test_calendario_completo_mostra_escala_no_dia(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        _criar_escala(
            logged_in_client, ministerio.id, "Culto de Domingo", data="2026-08-09", horario="19:00"
        )

        response = logged_in_client.get(f"/ministerio/{ministerio.id}/calendario?ano=2026&mes=8")
        html = response.data.decode("utf-8")
        assert response.status_code == 200
        assert "agosto de 2026" in html
        assert "Culto de Domingo" in html
        # grade completa: linhas = semanas, colunas = dias da semana
        assert "Dom" in html and "Seg" in html and "Sab" in html


def test_calendario_completo_navegacao_usa_a_propria_rota(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)

        response = logged_in_client.get(f"/ministerio/{ministerio.id}/calendario?ano=2026&mes=1")
        html = response.data.decode("utf-8")
        assert response.status_code == 200
        # a navegacao de mes/ano deve ficar dentro da propria pagina de calendario,
        # nao voltar pro widget pequeno da tela do ministerio
        assert f"/ministerio/{ministerio.id}/calendario?ano=2025&amp;mes=12" in html
        assert f"/ministerio/{ministerio.id}/calendario?ano=2026&amp;mes=2" in html


def test_calendario_completo_sem_escalas_mostra_aviso(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)

        response = logged_in_client.get(f"/ministerio/{ministerio.id}/calendario?ano=2026&mes=8")
        html = response.data.decode("utf-8")
        assert "Nenhuma escala com data neste mes" in html


def test_widget_pequeno_linka_para_calendario_completo(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)

        response = logged_in_client.get(f"/ministerio/{ministerio.id}")
        html = response.data.decode("utf-8")
        assert f"/ministerio/{ministerio.id}/calendario" in html


def test_usuario_nao_consegue_ver_calendario_de_outra_conta(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade = _criar_comunidade(logged_in_client, "Comunidade Ana")
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        ministerio_id = ministerio.id

    with sessao_isolada(app):
        response = outro_logged_in_client.get(f"/ministerio/{ministerio_id}/calendario")
        assert response.status_code == 404


# --- Isolamento entre contas -------------------------------------------------

def test_usuario_nao_consegue_ver_ministerio_de_outra_conta(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade = _criar_comunidade(logged_in_client, "Comunidade Ana")
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        ministerio_id = ministerio.id

    with sessao_isolada(app):
        assert outro_logged_in_client.get(f"/ministerio/{ministerio_id}").status_code == 404
        assert outro_logged_in_client.get(f"/ministerio/{ministerio_id}/editar").status_code == 404


def test_usuario_nao_consegue_editar_ministerio_de_outra_conta(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade = _criar_comunidade(logged_in_client, "Comunidade Ana")
        ministerio = _criar_ministerio(logged_in_client, comunidade.id, "Ministerio Original")
        ministerio_id = ministerio.id

    with sessao_isolada(app):
        response = outro_logged_in_client.post(
            f"/ministerio/{ministerio_id}/editar",
            data={"nome": "Invasao", "descricao": ""},
            follow_redirects=True,
        )
        assert response.status_code == 404

    with sessao_isolada(app):
        assert db.session.get(Ministerio, ministerio_id).nome == "Ministerio Original"


def test_usuario_nao_consegue_criar_ministerio_em_comunidade_de_outra_conta(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade = _criar_comunidade(logged_in_client, "Comunidade Ana")
        comunidade_id = comunidade.id

    with sessao_isolada(app):
        response = outro_logged_in_client.post(
            f"/ministerio/comunidade/{comunidade_id}/nova",
            data={"nome": "Invasao", "descricao": ""},
            follow_redirects=True,
        )
        assert response.status_code == 404
