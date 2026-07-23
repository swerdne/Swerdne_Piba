"""Testes do modulo escala."""
from app.comunidade.models import Comunidade
from app.ministerio.models import Ministerio
from app.escala.models import Escala, Funcao, Membro
from tests.conftest import sessao_isolada


def _criar_comunidade(cliente, nome="Comunidade Teste"):
    cliente.post(
        "/comunidade/nova",
        data={"nome": nome, "descricao": ""},
        follow_redirects=True,
    )
    return Comunidade.query.filter_by(nome=nome).order_by(Comunidade.id.desc()).first()


def _criar_ministerio(cliente, comunidade_id, nome="Ministerio Teste"):
    cliente.post(
        f"/ministerio/comunidade/{comunidade_id}/nova",
        data={"nome": nome, "descricao": ""},
        follow_redirects=True,
    )
    return (
        Ministerio.query.filter_by(nome=nome, comunidade_id=comunidade_id)
        .order_by(Ministerio.id.desc())
        .first()
    )


def _criar_escala(cliente, ministerio_id, nome, departamento="Louvor", data="", horario=""):
    cliente.post(
        f"/escala/ministerio/{ministerio_id}/nova",
        data={"nome": nome, "departamento": departamento, "data": data, "horario": horario},
        follow_redirects=True,
    )
    return (
        Escala.query.filter_by(nome=nome, departamento=departamento, ministerio_id=ministerio_id)
        .order_by(Escala.id.desc())
        .first()
    )


def _funcao_por_nome(escala, nome_funcao):
    return Funcao.query.filter_by(escala_id=escala.id, nome=nome_funcao).first()


def _criar_membro(cliente, comunidade_id, nome, telefone="", email=""):
    cliente.post(
        f"/comunidade/{comunidade_id}/membros",
        data={"nome": nome, "telefone": telefone, "email": email},
        follow_redirects=True,
    )
    return (
        Membro.query.filter_by(comunidade_id=comunidade_id, nome=nome)
        .order_by(Membro.id.desc())
        .first()
    )


def _escalar(cliente, funcao_id, membro_id, follow_redirects=True):
    return cliente.post(
        f"/escala/funcao/{funcao_id}/adicionar",
        data={"membro_id": membro_id},
        follow_redirects=follow_redirects,
    )


def _nova_escala_completa(cliente, nome_escala, departamento="Louvor"):
    """Cria comunidade + ministerio + escala numa tacada, para testes que so
    precisam do resultado final (a maioria)."""
    comunidade = _criar_comunidade(cliente)
    ministerio = _criar_ministerio(cliente, comunidade.id)
    return _criar_escala(cliente, ministerio.id, nome_escala, departamento=departamento)


def test_escala_sem_login_redireciona(client):
    response = client.get("/escala/", follow_redirects=False)
    assert response.status_code == 302


def test_escala_index_redireciona_para_comunidades(logged_in_client):
    response = logged_in_client.get("/escala/", follow_redirects=False)
    assert response.status_code == 302
    assert "/comunidade/" in response.headers["Location"]


def test_criar_escala_semeia_funcoes_do_departamento(logged_in_client, app, db):
    with app.app_context():
        escala = _nova_escala_completa(logged_in_client, "Culto de Domingo", departamento="Louvor")
        assert escala is not None

        response = logged_in_client.get(f"/escala/{escala.id}")
        html = response.data.decode("utf-8")
        assert response.status_code == 200
        for papel in ["Backing Vocal", "Baixo", "Bateria", "Guitarra", "Ministro de Louvor", "Teclado", "Violao"]:
            assert papel in html


def test_criar_escala_midia_semeia_funcoes_diferentes(logged_in_client, app, db):
    with app.app_context():
        escala = _nova_escala_completa(logged_in_client, "Culto de Domingo", departamento="Midia")
        html = logged_in_client.get(f"/escala/{escala.id}").data.decode("utf-8")
        assert "Fotografia" in html
        assert "Transmissao/Live" in html
        assert "Backing Vocal" not in html  # nao e do departamento Louvor


def test_criar_escala_kids_semeia_funcoes_diferentes(logged_in_client, app, db):
    with app.app_context():
        escala = _nova_escala_completa(logged_in_client, "Culto de Domingo", departamento="Kids")
        html = logged_in_client.get(f"/escala/{escala.id}").data.decode("utf-8")
        assert "Sala Bercario" in html
        assert "Recepcao Kids" in html


def test_criar_escala_sem_nome_mostra_erro(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        total_antes = Escala.query.count()
        logged_in_client.post(
            f"/escala/ministerio/{ministerio.id}/nova",
            data={"nome": "", "departamento": "Louvor", "data": "", "horario": ""},
            follow_redirects=True,
        )
        assert Escala.query.count() == total_antes


def test_mesmo_nome_pode_repetir_em_escalas_diferentes(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        e1 = _criar_escala(logged_in_client, ministerio.id, "Culto de Domingo", departamento="Louvor")
        logged_in_client.post(
            f"/escala/ministerio/{ministerio.id}/nova",
            data={"nome": "Culto de Domingo", "departamento": "Louvor", "data": "", "horario": ""},
            follow_redirects=True,
        )
        total = Escala.query.filter_by(nome="Culto de Domingo").count()
        assert total == 2
        assert e1 is not None


def test_adicionar_membro_a_uma_funcao(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        escala = _criar_escala(logged_in_client, ministerio.id, "Culto de Domingo")
        baixo = _funcao_por_nome(escala, "Baixo")
        membro = _criar_membro(logged_in_client, comunidade.id, "Endrews Elias", email="endrews@example.com")

        response = _escalar(logged_in_client, baixo.id, membro.id)
        assert response.status_code == 200
        assert "Endrews Elias" in response.data.decode("utf-8")

        baixo_atualizado = db.session.get(Funcao, baixo.id)
        assert baixo_atualizado.membro is not None
        assert baixo_atualizado.membro.nome == "Endrews Elias"
        assert baixo_atualizado.status == "nao_notificado"


def test_adicionar_membro_diretorio_vazio_mostra_aviso(logged_in_client, app, db):
    with app.app_context():
        escala = _nova_escala_completa(logged_in_client, "Culto de Domingo")
        baixo = _funcao_por_nome(escala, "Baixo")

        response = logged_in_client.post(
            f"/escala/funcao/{baixo.id}/adicionar", data={"membro_id": 999}, follow_redirects=True
        )
        assert response.status_code == 200
        baixo_atualizado = db.session.get(Funcao, baixo.id)
        assert baixo_atualizado.membro_id is None


def test_mover_membro_entre_funcoes(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        escala = _criar_escala(logged_in_client, ministerio.id, "Culto de Domingo")
        baixo = _funcao_por_nome(escala, "Baixo")
        bateria = _funcao_por_nome(escala, "Bateria")
        membro = _criar_membro(logged_in_client, comunidade.id, "Endrews Elias")

        _escalar(logged_in_client, baixo.id, membro.id)
        logged_in_client.post(
            f"/escala/funcao/{baixo.id}/mover",
            data={"destino_funcao_id": bateria.id},
            follow_redirects=True,
        )

        baixo_final = db.session.get(Funcao, baixo.id)
        bateria_final = db.session.get(Funcao, bateria.id)
        assert baixo_final.membro_id is None
        assert bateria_final.membro is not None
        assert bateria_final.membro.nome == "Endrews Elias"


def test_atualizar_status(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        escala = _criar_escala(logged_in_client, ministerio.id, "Culto de Domingo")
        baixo = _funcao_por_nome(escala, "Baixo")
        membro = _criar_membro(logged_in_client, comunidade.id, "Endrews Elias")
        _escalar(logged_in_client, baixo.id, membro.id)

        logged_in_client.post(
            f"/escala/funcao/{baixo.id}/status", data={"status": "confirmado"}, follow_redirects=True
        )
        baixo_final = db.session.get(Funcao, baixo.id)
        assert baixo_final.status == "confirmado"


def test_remover_membro(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        escala = _criar_escala(logged_in_client, ministerio.id, "Culto de Domingo")
        baixo = _funcao_por_nome(escala, "Baixo")
        membro = _criar_membro(logged_in_client, comunidade.id, "Endrews Elias")
        _escalar(logged_in_client, baixo.id, membro.id)

        logged_in_client.post(f"/escala/funcao/{baixo.id}/remover", data={}, follow_redirects=True)
        baixo_final = db.session.get(Funcao, baixo.id)
        assert baixo_final.membro_id is None


def test_notificar_sem_smtp_configurado_nao_derruba_o_servidor(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        escala = _criar_escala(logged_in_client, ministerio.id, "Culto de Domingo")
        baixo = _funcao_por_nome(escala, "Baixo")
        membro = _criar_membro(logged_in_client, comunidade.id, "Endrews Elias", email="endrews@example.com")
        _escalar(logged_in_client, baixo.id, membro.id)

        response = logged_in_client.post(
            f"/escala/{escala.id}/notificar", data={}, follow_redirects=True
        )
        assert response.status_code == 200
        assert "Internal Server Error" not in response.data.decode("utf-8")


def test_notificar_sem_twilio_configurado_nao_derruba_o_servidor(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        escala = _criar_escala(logged_in_client, ministerio.id, "Culto de Domingo")
        baixo = _funcao_por_nome(escala, "Baixo")
        membro = _criar_membro(logged_in_client, comunidade.id, "Endrews Elias", telefone="11999998888")
        _escalar(logged_in_client, baixo.id, membro.id)

        response = logged_in_client.post(
            f"/escala/{escala.id}/notificar", data={}, follow_redirects=True
        )
        html = response.data.decode("utf-8")
        assert response.status_code == 200
        assert "Internal Server Error" not in html
        assert "SMS falharam" in html


def test_notificar_membro_com_email_e_telefone_tenta_os_dois_canais(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        escala = _criar_escala(logged_in_client, ministerio.id, "Culto de Domingo")
        baixo = _funcao_por_nome(escala, "Baixo")
        membro = _criar_membro(
            logged_in_client, comunidade.id, "Endrews Elias", telefone="11999998888", email="endrews@example.com"
        )
        _escalar(logged_in_client, baixo.id, membro.id)

        response = logged_in_client.post(
            f"/escala/{escala.id}/notificar", data={}, follow_redirects=True
        )
        html = response.data.decode("utf-8")
        assert response.status_code == 200
        assert "e-mail(s) falharam" in html
        assert "SMS falharam" in html


def test_notificar_membro_sem_contato_e_contabilizado(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        escala = _criar_escala(logged_in_client, ministerio.id, "Culto de Domingo")
        baixo = _funcao_por_nome(escala, "Baixo")
        membro = _criar_membro(logged_in_client, comunidade.id, "Sem Contato")
        _escalar(logged_in_client, baixo.id, membro.id)

        response = logged_in_client.post(
            f"/escala/{escala.id}/notificar", data={}, follow_redirects=True
        )
        html = response.data.decode("utf-8")
        assert response.status_code == 200
        assert "sem e-mail/telefone cadastrado" in html


def test_notificar_membro_com_conta_gera_notificacao_no_app(logged_in_client, outro_logged_in_client, app, db):
    from app.notificacoes import Notificacao
    from app.auth.models import User

    with sessao_isolada(app):
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        escala = _criar_escala(logged_in_client, ministerio.id, "Culto de Domingo")
        baixo = _funcao_por_nome(escala, "Baixo")
        membro = _criar_membro(logged_in_client, comunidade.id, "Bruno", email="bruno@example.com")
        _escalar(logged_in_client, baixo.id, membro.id)

        response = logged_in_client.post(
            f"/escala/{escala.id}/notificar", data={}, follow_redirects=True
        )
        html = response.data.decode("utf-8")
        assert response.status_code == 200
        assert "notificacao(oes) no app" in html
        assert "e-mail(s) falharam" in html

        bruno = User.query.filter_by(email="bruno@example.com").first()
        notificacao = Notificacao.query.filter_by(usuario_id=bruno.id).first()
        assert notificacao is not None
        assert not notificacao.lida

    with sessao_isolada(app):
        html_bruno = outro_logged_in_client.get("/dashboard").data.decode("utf-8")
        assert "Voce foi escalado" in html_bruno


def test_marcar_notificacoes_como_lidas(logged_in_client, outro_logged_in_client, app, db):
    from app.notificacoes import Notificacao
    from app.auth.models import User

    with sessao_isolada(app):
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        escala = _criar_escala(logged_in_client, ministerio.id, "Culto de Domingo")
        baixo = _funcao_por_nome(escala, "Baixo")
        membro = _criar_membro(logged_in_client, comunidade.id, "Bruno", email="bruno@example.com")
        _escalar(logged_in_client, baixo.id, membro.id)
        logged_in_client.post(f"/escala/{escala.id}/notificar", data={}, follow_redirects=True)

    with sessao_isolada(app):
        outro_logged_in_client.post("/notificacoes/marcar-lidas", data={}, follow_redirects=True)

    with sessao_isolada(app):
        bruno = User.query.filter_by(email="bruno@example.com").first()
        notificacao = Notificacao.query.filter_by(usuario_id=bruno.id).first()
        assert notificacao.lida


def test_notificar_escala_vazia_mostra_aviso(logged_in_client, app, db):
    with app.app_context():
        escala = _nova_escala_completa(logged_in_client, "Culto de Domingo")
        response = logged_in_client.post(
            f"/escala/{escala.id}/notificar", data={}, follow_redirects=True
        )
        assert response.status_code == 200
        assert "Ninguem escalado" in response.data.decode("utf-8")


def test_adicionar_funcao_nova(logged_in_client, app, db):
    with app.app_context():
        escala = _nova_escala_completa(logged_in_client, "Culto de Domingo", departamento="Kids")
        response = logged_in_client.post(
            f"/escala/{escala.id}/funcao/adicionar", data={"nome": "Estacionamento"}, follow_redirects=True
        )
        assert response.status_code == 200
        assert "Estacionamento" in response.data.decode("utf-8")
        assert Funcao.query.filter_by(escala_id=escala.id, nome="Estacionamento").first() is not None


def test_adicionar_funcao_sem_nome_mostra_erro(logged_in_client, app, db):
    with app.app_context():
        escala = _nova_escala_completa(logged_in_client, "Culto de Domingo", departamento="Kids")
        total_antes = Funcao.query.filter_by(escala_id=escala.id).count()
        logged_in_client.post(f"/escala/{escala.id}/funcao/adicionar", data={"nome": ""}, follow_redirects=True)
        assert Funcao.query.filter_by(escala_id=escala.id).count() == total_antes


def test_editar_funcao_renomeia(logged_in_client, app, db):
    with app.app_context():
        escala = _nova_escala_completa(logged_in_client, "Culto de Domingo", departamento="Kids")
        funcao = _funcao_por_nome(escala, "Sala Infantil")
        response = logged_in_client.post(
            f"/escala/funcao/{funcao.id}/editar", data={"nome": "Sala Juniores"}, follow_redirects=True
        )
        assert response.status_code == 200
        assert db.session.get(Funcao, funcao.id).nome == "Sala Juniores"


def test_excluir_funcao_remove_do_banco(logged_in_client, app, db):
    with app.app_context():
        escala = _nova_escala_completa(logged_in_client, "Culto de Domingo", departamento="Kids")
        funcao = _funcao_por_nome(escala, "Sala Infantil")
        funcao_id = funcao.id
        response = logged_in_client.post(f"/escala/funcao/{funcao_id}/excluir", data={}, follow_redirects=True)
        assert response.status_code == 200
        db.session.remove()
        assert db.session.get(Funcao, funcao_id) is None


def test_excluir_funcao_com_membro_tambem_remove(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        escala = _criar_escala(logged_in_client, ministerio.id, "Culto de Domingo", departamento="Kids")
        funcao = _funcao_por_nome(escala, "Sala Infantil")
        membro = _criar_membro(logged_in_client, comunidade.id, "Alguem")
        _escalar(logged_in_client, funcao.id, membro.id)

        funcao_id = funcao.id
        response = logged_in_client.post(f"/escala/funcao/{funcao_id}/excluir", data={}, follow_redirects=True)
        assert response.status_code == 200
        assert "Internal Server Error" not in response.data.decode("utf-8")
        db.session.remove()
        assert db.session.get(Funcao, funcao_id) is None


# --- Subcabecalhos (categorias) ----------------------------------------------

def test_adicionar_subcabecalho(logged_in_client, app, db):
    with app.app_context():
        escala = _nova_escala_completa(logged_in_client, "Culto de Domingo", departamento="Louvor")

        response = logged_in_client.post(
            f"/escala/{escala.id}/subcabecalho/adicionar", data={"nome": "Orquestra"}, follow_redirects=True
        )
        assert response.status_code == 200
        assert "Orquestra" in response.data.decode("utf-8")

        subcabecalho = Funcao.query.filter_by(escala_id=escala.id, nome="Orquestra").first()
        assert subcabecalho is not None
        assert subcabecalho.eh_subcabecalho


def test_subcabecalho_nao_aparece_como_opcao_para_mover_ou_escalar(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        escala = _criar_escala(logged_in_client, ministerio.id, "Culto de Domingo", departamento="Louvor")
        logged_in_client.post(
            f"/escala/{escala.id}/subcabecalho/adicionar", data={"nome": "Orquestra"}, follow_redirects=True
        )
        subcabecalho = Funcao.query.filter_by(escala_id=escala.id, nome="Orquestra").first()

        baixo = _funcao_por_nome(escala, "Baixo")
        membro = _criar_membro(logged_in_client, comunidade.id, "Fulano")
        _escalar(logged_in_client, baixo.id, membro.id)

        html = logged_in_client.get(f"/escala/{escala.id}").data.decode("utf-8")
        assert f'value="{subcabecalho.id}"' not in html


def test_renomear_subcabecalho(logged_in_client, app, db):
    with app.app_context():
        escala = _nova_escala_completa(logged_in_client, "Culto de Domingo")
        logged_in_client.post(
            f"/escala/{escala.id}/subcabecalho/adicionar", data={"nome": "Orquestra"}, follow_redirects=True
        )
        subcabecalho = Funcao.query.filter_by(escala_id=escala.id, nome="Orquestra").first()

        logged_in_client.post(
            f"/escala/funcao/{subcabecalho.id}/editar", data={"nome": "Louvor"}, follow_redirects=True
        )
        assert db.session.get(Funcao, subcabecalho.id).nome == "Louvor"


def test_excluir_subcabecalho(logged_in_client, app, db):
    with app.app_context():
        escala = _nova_escala_completa(logged_in_client, "Culto de Domingo")
        logged_in_client.post(
            f"/escala/{escala.id}/subcabecalho/adicionar", data={"nome": "Orquestra"}, follow_redirects=True
        )
        subcabecalho = Funcao.query.filter_by(escala_id=escala.id, nome="Orquestra").first()
        subcabecalho_id = subcabecalho.id

        logged_in_client.post(f"/escala/funcao/{subcabecalho_id}/excluir", data={}, follow_redirects=True)
        db.session.remove()
        assert db.session.get(Funcao, subcabecalho_id) is None


# --- Exclusao de escalas ------------------------------------------------------

def test_excluir_escala(logged_in_client, app, db):
    with app.app_context():
        escala = _nova_escala_completa(logged_in_client, "Culto de Domingo")
        escala_id = escala.id

        response = logged_in_client.post(f"/escala/{escala_id}/excluir", data={}, follow_redirects=True)
        assert response.status_code == 200
        db.session.remove()
        assert db.session.get(Escala, escala_id) is None
        assert Funcao.query.filter_by(escala_id=escala_id).count() == 0


def test_excluir_escala_redireciona_para_ministerio(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        escala = _criar_escala(logged_in_client, ministerio.id, "Culto de Domingo")

        response = logged_in_client.post(f"/escala/{escala.id}/excluir", data={}, follow_redirects=False)
        assert response.status_code == 302
        assert f"/ministerio/{ministerio.id}" in response.headers["Location"]


def test_usuario_nao_consegue_excluir_escala_de_outra_conta(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        escala = _nova_escala_completa(logged_in_client, "Culto de Domingo")
        escala_id = escala.id

    with sessao_isolada(app):
        response = outro_logged_in_client.post(f"/escala/{escala_id}/excluir", data={}, follow_redirects=True)
        assert response.status_code == 404

    with sessao_isolada(app):
        assert db.session.get(Escala, escala_id) is not None


# --- Isolamento entre contas -------------------------------------------------

def test_contas_diferentes_tem_escalas_separadas(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        escala_ana = _nova_escala_completa(logged_in_client, "Culto de Domingo")
    with sessao_isolada(app):
        escala_bruno = _nova_escala_completa(outro_logged_in_client, "Culto de Domingo")

    assert escala_ana.id != escala_bruno.id
    assert escala_ana.ministerio_id != escala_bruno.ministerio_id


def test_usuario_nao_consegue_criar_escala_em_ministerio_de_outra_conta(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade_ana = _criar_comunidade(logged_in_client, "Comunidade Ana")
        ministerio_ana = _criar_ministerio(logged_in_client, comunidade_ana.id)
        ministerio_id = ministerio_ana.id

    with sessao_isolada(app):
        response = outro_logged_in_client.post(
            f"/escala/ministerio/{ministerio_id}/nova",
            data={"nome": "Invasao", "departamento": "Louvor", "data": "", "horario": ""},
            follow_redirects=True,
        )
        assert response.status_code == 404


def test_usuario_nao_consegue_mexer_em_funcao_de_outra_conta(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        escala = _nova_escala_completa(logged_in_client, "Culto de Domingo")
        funcao_id = _funcao_por_nome(escala, "Baixo").id

    with sessao_isolada(app):
        response = outro_logged_in_client.post(
            f"/escala/funcao/{funcao_id}/adicionar",
            data={"membro_id": 1},
            follow_redirects=True,
        )
        assert response.status_code == 404

    with sessao_isolada(app):
        assert db.session.get(Funcao, funcao_id).membro_id is None


def test_usuario_nao_consegue_excluir_funcao_de_outra_conta(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        escala = _nova_escala_completa(logged_in_client, "Culto de Domingo")
        funcao_id = _funcao_por_nome(escala, "Baixo").id

    with sessao_isolada(app):
        response = outro_logged_in_client.post(
            f"/escala/funcao/{funcao_id}/excluir", data={}, follow_redirects=True
        )
        assert response.status_code == 404

    with sessao_isolada(app):
        assert db.session.get(Funcao, funcao_id) is not None


def test_usuario_nao_consegue_notificar_escala_de_outra_conta(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        escala = _nova_escala_completa(logged_in_client, "Culto de Domingo")
        escala_id = escala.id

    with sessao_isolada(app):
        response = outro_logged_in_client.post(
            f"/escala/{escala_id}/notificar", data={}, follow_redirects=True
        )
        assert response.status_code == 404


def test_usuario_nao_consegue_ver_escala_de_outra_conta(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        escala = _nova_escala_completa(logged_in_client, "Culto de Domingo")
        escala_id = escala.id

    with sessao_isolada(app):
        response = outro_logged_in_client.get(f"/escala/{escala_id}")
        assert response.status_code == 404


# --- Edicao de escala (nome/data/horario) --------------------------------------

def test_editar_escala_atualiza_data_e_horario(logged_in_client, app, db):
    with app.app_context():
        escala = _nova_escala_completa(logged_in_client, "Culto de Domingo")

        response = logged_in_client.post(
            f"/escala/{escala.id}/editar",
            data={"nome": escala.nome, "data": "2026-09-06", "horario": "10:00"},
            follow_redirects=True,
        )
        assert response.status_code == 200

        atualizada = db.session.get(Escala, escala.id)
        assert atualizada.data.isoformat() == "2026-09-06"
        assert atualizada.horario.strftime("%H:%M") == "10:00"


def test_editar_escala_atualiza_o_nome(logged_in_client, app, db):
    with app.app_context():
        escala = _nova_escala_completa(logged_in_client, "Culto de Domingo")

        response = logged_in_client.post(
            f"/escala/{escala.id}/editar",
            data={"nome": "Culto de Quarta", "data": "", "horario": ""},
            follow_redirects=True,
        )
        html = response.data.decode("utf-8")
        assert response.status_code == 200
        assert "Nome atualizado de" in html and "Culto de Domingo" in html and "Culto de Quarta" in html

        atualizada = db.session.get(Escala, escala.id)
        assert atualizada.nome == "Culto de Quarta"


def test_editar_escala_sem_nome_mostra_erro(logged_in_client, app, db):
    with app.app_context():
        escala = _nova_escala_completa(logged_in_client, "Culto de Domingo")

        logged_in_client.post(
            f"/escala/{escala.id}/editar",
            data={"nome": "", "data": "", "horario": ""},
            follow_redirects=True,
        )
        assert db.session.get(Escala, escala.id).nome == "Culto de Domingo"


def test_editar_escala_recalcula_notificacoes_automaticas(logged_in_client, app, db):
    with app.app_context():
        escala = _nova_escala_completa(logged_in_client, "Culto de Domingo")
        escala.notificado_24h_em = db.func.now()
        escala.notificado_16h_em = db.func.now()
        db.session.commit()

        logged_in_client.post(
            f"/escala/{escala.id}/editar",
            data={"nome": escala.nome, "data": "2026-09-06", "horario": "10:00"},
            follow_redirects=True,
        )

        atualizada = db.session.get(Escala, escala.id)
        assert atualizada.notificado_24h_em is None
        assert atualizada.notificado_16h_em is None


def test_editar_escala_sem_mudanca_nao_reseta_notificacoes(logged_in_client, app, db):
    with app.app_context():
        escala = _nova_escala_completa(logged_in_client, "Culto de Domingo", departamento="Louvor")
        logged_in_client.post(
            f"/escala/{escala.id}/editar",
            data={"nome": escala.nome, "data": "2026-09-06", "horario": "10:00"},
            follow_redirects=True,
        )
        escala_atualizada = db.session.get(Escala, escala.id)
        escala_atualizada.notificado_24h_em = db.func.now()
        db.session.commit()
        nome_atual = escala_atualizada.nome

        # reenvia exatamente os mesmos valores -- nao deve mexer nas notificacoes
        response = logged_in_client.post(
            f"/escala/{escala.id}/editar",
            data={"nome": nome_atual, "data": "2026-09-06", "horario": "10:00"},
            follow_redirects=True,
        )
        assert "Nenhuma mudanca" in response.data.decode("utf-8")
        assert db.session.get(Escala, escala.id).notificado_24h_em is not None


def test_editar_escala_avisa_membros_ja_escalados(logged_in_client, app, db):
    from app.notificacoes import Notificacao
    from app.auth.models import User

    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        escala = _criar_escala(logged_in_client, ministerio.id, "Culto de Domingo", data="2026-09-01", horario="09:00")
        baixo = _funcao_por_nome(escala, "Baixo")
        membro = _criar_membro(logged_in_client, comunidade.id, "Bruno", email="bruno-mudanca@example.com")
        _escalar(logged_in_client, baixo.id, membro.id)

        # cria uma conta cujo email bate com o do membro, pra virar notificacao in-app
        usuario = User(email="bruno-mudanca@example.com", username="brunomudanca")
        usuario.set_password("senha123")
        db.session.add(usuario)
        db.session.commit()

        response = logged_in_client.post(
            f"/escala/{escala.id}/editar",
            data={"nome": "Culto de Domingo", "data": "2026-09-08", "horario": "19:00"},
            follow_redirects=True,
        )
        html = response.data.decode("utf-8")
        assert response.status_code == 200
        assert "Equipe avisada da mudanca" in html

        notificacao = Notificacao.query.filter_by(usuario_id=usuario.id).first()
        assert notificacao is not None
        assert "mudou de 01/09/2026" in notificacao.mensagem
        assert "08/09/2026" in notificacao.mensagem


def test_usuario_nao_consegue_editar_escala_de_outra_conta(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        escala = _nova_escala_completa(logged_in_client, "Culto de Domingo")
        escala_id = escala.id
        data_original = escala.data
        nome_original = escala.nome

    with sessao_isolada(app):
        response = outro_logged_in_client.post(
            f"/escala/{escala_id}/editar",
            data={"nome": "Invasao", "data": "2026-09-06", "horario": "10:00"},
            follow_redirects=True,
        )
        assert response.status_code == 404

    with sessao_isolada(app):
        atual = db.session.get(Escala, escala_id)
        assert atual.data == data_original
        assert atual.nome == nome_original
