"""Testes do modulo comunidade."""
from app.comunidade.models import Comunidade
from app.escala.models import Membro
from tests.conftest import sessao_isolada
from tests.test_escala import (
    _criar_comunidade,
    _criar_ministerio,
    _criar_escala,
    _criar_membro,
    _escalar,
    _funcao_por_nome,
)


def test_comunidade_sem_login_redireciona(client):
    response = client.get("/comunidade/", follow_redirects=False)
    assert response.status_code == 302


def test_lista_vazia_mostra_estado_vazio(logged_in_client):
    response = logged_in_client.get("/comunidade/")
    assert response.status_code == 200
    assert "Voce ainda nao tem nenhuma comunidade" in response.data.decode("utf-8")


def test_criar_comunidade_aparece_na_lista(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client, "Igreja Vida Nova")
        assert comunidade is not None

        response = logged_in_client.get("/comunidade/")
        assert "Igreja Vida Nova" in response.data.decode("utf-8")


def test_criar_comunidade_sem_nome_mostra_erro(logged_in_client, app, db):
    with app.app_context():
        total_antes = Comunidade.query.count()
        logged_in_client.post("/comunidade/nova", data={"nome": "", "descricao": ""}, follow_redirects=True)
        assert Comunidade.query.count() == total_antes


def test_editar_comunidade_atualiza_nome(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client, "Nome Antigo")
        response = logged_in_client.post(
            f"/comunidade/{comunidade.id}/editar",
            data={"nome": "Nome Novo", "descricao": "Descricao nova"},
            follow_redirects=True,
        )
        assert response.status_code == 200
        atualizada = db.session.get(Comunidade, comunidade.id)
        assert atualizada.nome == "Nome Novo"
        assert atualizada.descricao == "Descricao nova"


# --- Isolamento entre contas -------------------------------------------------

def test_usuario_nao_consegue_ver_comunidade_de_outra_conta(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade = _criar_comunidade(logged_in_client, "Comunidade Ana")
        comunidade_id = comunidade.id

    with sessao_isolada(app):
        assert outro_logged_in_client.get(f"/comunidade/{comunidade_id}").status_code == 404
        assert outro_logged_in_client.get(f"/comunidade/{comunidade_id}/editar").status_code == 404
        assert outro_logged_in_client.get(f"/comunidade/{comunidade_id}/membros").status_code == 404


def test_usuario_nao_consegue_editar_comunidade_de_outra_conta(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade = _criar_comunidade(logged_in_client, "Comunidade Ana")
        comunidade_id = comunidade.id

    with sessao_isolada(app):
        response = outro_logged_in_client.post(
            f"/comunidade/{comunidade_id}/editar",
            data={"nome": "Invasao", "descricao": ""},
            follow_redirects=True,
        )
        assert response.status_code == 404

    with sessao_isolada(app):
        assert db.session.get(Comunidade, comunidade_id).nome == "Comunidade Ana"


# --- Diretorio de membros -----------------------------------------------------

def test_adicionar_membro_ao_diretorio(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        membro = _criar_membro(logged_in_client, comunidade.id, "Fulano", email="fulano@example.com")
        assert membro is not None

        response = logged_in_client.get(f"/comunidade/{comunidade.id}/membros")
        assert "Fulano" in response.data.decode("utf-8")


def test_excluir_membro_do_diretorio(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        membro = _criar_membro(logged_in_client, comunidade.id, "Fulano")

        response = logged_in_client.post(
            f"/comunidade/{comunidade.id}/membros/{membro.id}/excluir", data={}, follow_redirects=True
        )
        assert response.status_code == 200
        assert db.session.get(Membro, membro.id) is None


def test_excluir_membro_escalado_e_bloqueado(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        escala = _criar_escala(logged_in_client, ministerio.id, "Culto de Domingo")
        baixo = _funcao_por_nome(escala, "Baixo")
        membro = _criar_membro(logged_in_client, comunidade.id, "Fulano")
        _escalar(logged_in_client, baixo.id, membro.id)

        response = logged_in_client.post(
            f"/comunidade/{comunidade.id}/membros/{membro.id}/excluir", data={}, follow_redirects=True
        )
        assert response.status_code == 200
        assert "antes de excluir do diretorio" in response.data.decode("utf-8")
        assert db.session.get(Membro, membro.id) is not None


# --- Tela de escalados --------------------------------------------------------

def test_escalados_dono_ve_quem_esta_escalado(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        escala = _criar_escala(logged_in_client, ministerio.id, "Culto de Domingo", data="2026-08-01", horario="19:00")
        baixo = _funcao_por_nome(escala, "Baixo")
        membro = _criar_membro(logged_in_client, comunidade.id, "Fulano")
        _escalar(logged_in_client, baixo.id, membro.id)

        response = logged_in_client.get(f"/comunidade/{comunidade.id}/escalados")
        html = response.data.decode("utf-8")
        assert response.status_code == 200
        assert "Fulano" in html
        assert "Baixo" in html


def test_escalados_filtra_por_departamento(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        escala_louvor = _criar_escala(logged_in_client, ministerio.id, "Culto Louvor", departamento="Louvor")
        escala_kids = _criar_escala(logged_in_client, ministerio.id, "Culto Kids", departamento="Kids")

        membro = _criar_membro(logged_in_client, comunidade.id, "Fulano")
        _escalar(logged_in_client, _funcao_por_nome(escala_louvor, "Baixo").id, membro.id)
        _escalar(logged_in_client, _funcao_por_nome(escala_kids, "Sala Infantil").id, membro.id)

        response = logged_in_client.get(f"/comunidade/{comunidade.id}/escalados?departamento=Kids")
        html = response.data.decode("utf-8")
        assert "Culto Kids" in html
        assert "Culto Louvor" not in html


def test_terceiro_sem_vinculo_nao_ve_escalados(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade = _criar_comunidade(logged_in_client, "Comunidade Ana")
        comunidade_id = comunidade.id

    with sessao_isolada(app):
        response = outro_logged_in_client.get(f"/comunidade/{comunidade_id}/escalados")
        assert response.status_code == 404


def test_membro_vinculado_por_email_ve_escalados_de_leitura(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade = _criar_comunidade(logged_in_client, "Comunidade Ana")
        # bruno@example.com e o e-mail da conta "bruno" (ver conftest.py)
        _criar_membro(logged_in_client, comunidade.id, "Bruno", email="bruno@example.com")
        comunidade_id = comunidade.id

    with sessao_isolada(app):
        response = outro_logged_in_client.get(f"/comunidade/{comunidade_id}/escalados")
        assert response.status_code == 200

        # leitura apenas: nao pode gerenciar membros nem editar a comunidade
        assert outro_logged_in_client.get(f"/comunidade/{comunidade_id}/membros").status_code == 404
        assert outro_logged_in_client.get(f"/comunidade/{comunidade_id}/editar").status_code == 404


# --- Fluxo ponta a ponta: diretorio -> select da funcao -----------------------

def test_membros_do_diretorio_aparecem_no_select_da_funcao(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        escala = _criar_escala(logged_in_client, ministerio.id, "Culto de Domingo")
        membro1 = _criar_membro(logged_in_client, comunidade.id, "Fulano")
        membro2 = _criar_membro(logged_in_client, comunidade.id, "Ciclana")

        html = logged_in_client.get(f"/escala/{escala.id}").data.decode("utf-8")
        assert "Fulano" in html
        assert "Ciclana" in html

        baixo = _funcao_por_nome(escala, "Baixo")
        response = _escalar(logged_in_client, baixo.id, membro2.id)
        assert response.status_code == 200
        assert "Ciclana" in response.data.decode("utf-8")
