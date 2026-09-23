"""Testes do modulo comunidade."""
from app.comunidade.models import Comunidade
from app.escala.models import Membro, CicloDisponibilidade, SegmentoCiclo
from tests.conftest import sessao_isolada, _registrar
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


def test_excluir_comunidade_remove_e_redireciona_para_lista(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client, "Comunidade a Apagar")
        comunidade_id = comunidade.id

        response = logged_in_client.post(
            f"/comunidade/{comunidade_id}/excluir", data={}, follow_redirects=True
        )
        assert response.status_code == 200
        assert db.session.get(Comunidade, comunidade_id) is None
        assert "excluida" in response.data.decode("utf-8")


def test_excluir_comunidade_apaga_ministerios_e_diretorio_em_cascata(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        membro = _criar_membro(logged_in_client, comunidade.id, "Fulano")

        ministerio_id = ministerio.id
        membro_id = membro.id

        logged_in_client.post(f"/comunidade/{comunidade.id}/excluir", data={}, follow_redirects=True)

        from app.ministerio.models import Ministerio
        assert db.session.get(Ministerio, ministerio_id) is None
        assert db.session.get(Membro, membro_id) is None


def test_usuario_nao_consegue_excluir_comunidade_de_outra_conta(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade = _criar_comunidade(logged_in_client, "Comunidade Ana")
        comunidade_id = comunidade.id

    with sessao_isolada(app):
        response = outro_logged_in_client.post(
            f"/comunidade/{comunidade_id}/excluir", data={}, follow_redirects=True
        )
        assert response.status_code == 404

    with sessao_isolada(app):
        assert db.session.get(Comunidade, comunidade_id) is not None


# --- Exclusao em lote (JS chama a rota individual de cada item, um por vez) --

def test_lista_marca_checkbox_com_url_de_exclusao_individual(logged_in_client, app, db):
    """A selecao em lote (comunidade/lista.html) nao tem rota de "excluir
    varias" propria -- o JS (app/static/js/main.js) exclui um item por vez,
    via fetch sequencial, direto na rota de exclusao individual de cada
    comunidade (evita uma unica requisicao grande o bastante pra estourar
    timeout num lote grande). Esse teste so confere que o template aponta
    pra URL certa em cada checkbox; a exclusao em si ja e coberta por
    test_excluir_comunidade_remove_e_redireciona_para_lista."""
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client, "Comunidade Teste")
        _criar_comunidade(logged_in_client, "Segunda Comunidade")  # >1 pra "Selecionar" aparecer

        html = logged_in_client.get("/comunidade/").data.decode("utf-8")
        assert f'data-selecao-url="/comunidade/{comunidade.id}/excluir"' in html


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


def test_lista_tem_logo_que_volta_direto_pro_inicio(logged_in_client, app, db):
    """Mesmo atalho de escala/detalhe.html, ver
    app/templates/_macros.html::logo_inicio -- confere que tambem esta
    presente num modulo diferente (comunidade), nao so em escala."""
    with app.app_context():
        html = logged_in_client.get("/comunidade/").data.decode("utf-8")
        assert 'title="Ir para o inicio"' in html
        assert 'href="/dashboard"' in html


# --- Diretorio de membros -----------------------------------------------------

def test_adicionar_membro_ao_diretorio(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        membro = _criar_membro(logged_in_client, comunidade.id, "Fulano", email="fulano@example.com")
        assert membro is not None

        response = logged_in_client.get(f"/comunidade/{comunidade.id}/membros")
        assert "Fulano" in response.data.decode("utf-8")


def test_adicionar_membro_com_proximo_volta_pra_escala(logged_in_client, app, db):
    """Ver escala/detalhe.html: o link "Adicionar novo membro ao diretorio"
    carrega ?proximo=<url da escala> pra, depois de cadastrar, voltar direto
    pra tela de edicao da escala em vez de ficar em Comunidade > Membros."""
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        escala = _criar_escala(logged_in_client, ministerio.id, "Culto de Domingo")
        destino = f"/escala/{escala.id}"

        response = logged_in_client.post(
            f"/comunidade/{comunidade.id}/membros?proximo={destino}",
            data={"nome": "Fulano", "telefone": "", "email": ""},
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert response.headers["Location"] == destino


def test_adicionar_membro_ignora_proximo_externo(logged_in_client, app, db):
    """proximo=//evil.com ou http://evil.com nao pode virar open redirect --
    cai no comportamento padrao (fica em Comunidade > Membros)."""
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)

        response = logged_in_client.post(
            f"/comunidade/{comunidade.id}/membros?proximo=//evil.com",
            data={"nome": "Fulano", "telefone": "", "email": ""},
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert response.headers["Location"] == f"/comunidade/{comunidade.id}/membros"


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


# --- Ciclo de disponibilidade --------------------------------------------------

def _criar_ciclo(cliente, comunidade_id, membro_id, nome, data_inicio, segmentos):
    """segmentos: lista de tuplas (nome, dias, indisponivel)."""
    dados = {"nome": nome, "data_inicio": data_inicio}
    for indice, (nome_segmento, dias, indisponivel) in enumerate(segmentos):
        dados[f"segmento_nome_{indice}"] = nome_segmento
        dados[f"segmento_dias_{indice}"] = str(dias)
        if indisponivel:
            dados[f"segmento_indisponivel_{indice}"] = "on"

    cliente.post(
        f"/comunidade/{comunidade_id}/membros/{membro_id}/disponibilidade/nova",
        data=dados,
        follow_redirects=True,
    )
    return (
        CicloDisponibilidade.query.filter_by(membro_id=membro_id, nome=nome)
        .order_by(CicloDisponibilidade.id.desc())
        .first()
    )


def test_criar_ciclo_disponibilidade_com_segmentos(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        membro = _criar_membro(logged_in_client, comunidade.id, "Fulano")

        ciclo = _criar_ciclo(
            logged_in_client, comunidade.id, membro.id, "Turno da empresa", "2026-08-07",
            segmentos=[("Trabalho", 4, True), ("Folga", 4, False)],
        )
        assert ciclo is not None
        assert len(ciclo.segmentos) == 2
        assert ciclo.segmentos[0].nome == "Trabalho"
        assert ciclo.segmentos[0].indisponivel is True
        assert ciclo.segmentos[1].nome == "Folga"
        assert ciclo.segmentos[1].indisponivel is False

        html = logged_in_client.get(f"/comunidade/{comunidade.id}/membros/{membro.id}/disponibilidade").data.decode("utf-8")
        assert "Turno da empresa" in html
        assert "ciclo de 8 dia(s)" in html


def test_ciclo_sem_segmento_valido_mostra_erro(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        membro = _criar_membro(logged_in_client, comunidade.id, "Fulano")

        response = logged_in_client.post(
            f"/comunidade/{comunidade.id}/membros/{membro.id}/disponibilidade/nova",
            data={"nome": "Turno vazio", "data_inicio": "2026-08-07"},
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert "Adicione pelo menos um segmento" in response.data.decode("utf-8")
        assert CicloDisponibilidade.query.filter_by(membro_id=membro.id).count() == 0


def test_excluir_ciclo_disponibilidade(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        membro = _criar_membro(logged_in_client, comunidade.id, "Fulano")
        ciclo = _criar_ciclo(
            logged_in_client, comunidade.id, membro.id, "Turno", "2026-08-07",
            segmentos=[("Trabalho", 4, True), ("Folga", 4, False)],
        )
        ciclo_id = ciclo.id

        response = logged_in_client.post(
            f"/comunidade/{comunidade.id}/disponibilidade/{ciclo_id}/excluir", data={}, follow_redirects=True
        )
        assert response.status_code == 200
        assert db.session.get(CicloDisponibilidade, ciclo_id) is None
        # segmentos somem junto (cascade)
        assert SegmentoCiclo.query.filter_by(ciclo_id=ciclo_id).count() == 0


def test_usuario_nao_consegue_ver_ou_excluir_disponibilidade_de_outra_conta(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade = _criar_comunidade(logged_in_client)
        membro = _criar_membro(logged_in_client, comunidade.id, "Fulano")
        ciclo = _criar_ciclo(
            logged_in_client, comunidade.id, membro.id, "Turno", "2026-08-07",
            segmentos=[("Trabalho", 4, True)],
        )
        comunidade_id, membro_id, ciclo_id = comunidade.id, membro.id, ciclo.id

    with sessao_isolada(app):
        resposta_ver = outro_logged_in_client.get(f"/comunidade/{comunidade_id}/membros/{membro_id}/disponibilidade")
        assert resposta_ver.status_code == 404

        resposta_excluir = outro_logged_in_client.post(
            f"/comunidade/{comunidade_id}/disponibilidade/{ciclo_id}/excluir", data={}, follow_redirects=True
        )
        assert resposta_excluir.status_code == 404


def test_calculo_do_ciclo_bate_com_padrao_4x4_real(logged_in_client, app, db):
    """Reproduz o caso real mapeado de um app de turno de trabalho: 4 dias
    de trabalho, 4 de folga, ciclo de 8 dias, ancorado num dia de inicio de
    bloco de trabalho -- confere segmento_na_data pra varias datas dentro e
    fora do primeiro ciclo."""
    from datetime import date
    from app.escala.models import avisos_disponibilidade

    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        membro = _criar_membro(logged_in_client, comunidade.id, "Fulano")
        ciclo = _criar_ciclo(
            logged_in_client, comunidade.id, membro.id, "Turno 4x4", "2026-08-07",
            segmentos=[("Trabalho", 4, True), ("Folga", 4, False)],
        )

        casos = [
            (date(2026, 8, 7), "Trabalho"),
            (date(2026, 8, 10), "Trabalho"),
            (date(2026, 8, 11), "Folga"),
            (date(2026, 8, 14), "Folga"),
            (date(2026, 8, 15), "Trabalho"),  # inicio do proximo ciclo (8 dias depois)
            (date(2026, 8, 22), "Folga"),
            (date(2026, 8, 23), "Trabalho"),
            (date(2026, 8, 3), "Folga"),  # antes da data_inicio, mesma logica ciclica
        ]
        for data, esperado in casos:
            segmento = ciclo.segmento_na_data(data)
            assert segmento.nome == esperado, f"{data}: esperava {esperado}, veio {segmento.nome}"

        assert avisos_disponibilidade(membro, date(2026, 8, 8)) == ["Trabalho"]
        assert avisos_disponibilidade(membro, date(2026, 8, 12)) == []


# --- Aviso de disponibilidade na tela da Escala --------------------------------

def test_escala_mostra_aviso_quando_pessoa_indisponivel_na_data(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        escala = _criar_escala(logged_in_client, ministerio.id, "Culto", data="2026-08-08", horario="19:00")
        baixo = _funcao_por_nome(escala, "Baixo")
        guitarra = _funcao_por_nome(escala, "Guitarra")
        membro = _criar_membro(logged_in_client, comunidade.id, "Fulano")
        _criar_ciclo(
            logged_in_client, comunidade.id, membro.id, "Turno 4x4", "2026-08-07",
            segmentos=[("Trabalho", 4, True), ("Folga", 4, False)],
        )
        _escalar(logged_in_client, baixo.id, membro.id)  # 8/ago cai em "Trabalho"

        html = logged_in_client.get(f"/escala/{escala.id}").data.decode("utf-8")
        assert "Possivel conflito" in html  # badge junto de quem ja esta escalado
        assert "indisponivel: Trabalho" in html  # rotulo no <select> da funcao ainda vaga (Guitarra)


def test_escala_sem_data_nao_mostra_aviso(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        escala = _criar_escala(logged_in_client, ministerio.id, "Culto sem data")  # sem data
        baixo = _funcao_por_nome(escala, "Baixo")
        membro = _criar_membro(logged_in_client, comunidade.id, "Fulano")
        _criar_ciclo(
            logged_in_client, comunidade.id, membro.id, "Turno 4x4", "2026-08-07",
            segmentos=[("Trabalho", 4, True), ("Folga", 4, False)],
        )
        _escalar(logged_in_client, baixo.id, membro.id)

        html = logged_in_client.get(f"/escala/{escala.id}").data.decode("utf-8")
        assert "Possivel conflito" not in html
        assert "indisponivel:" not in html


def test_escala_nao_mostra_aviso_quando_pessoa_disponivel_na_data(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        escala = _criar_escala(logged_in_client, ministerio.id, "Culto", data="2026-08-12", horario="19:00")
        baixo = _funcao_por_nome(escala, "Baixo")
        membro = _criar_membro(logged_in_client, comunidade.id, "Fulano")
        _criar_ciclo(
            logged_in_client, comunidade.id, membro.id, "Turno 4x4", "2026-08-07",
            segmentos=[("Trabalho", 4, True), ("Folga", 4, False)],
        )
        _escalar(logged_in_client, baixo.id, membro.id)  # 12/ago cai em "Folga"

        html = logged_in_client.get(f"/escala/{escala.id}").data.decode("utf-8")
        assert "Possivel conflito" not in html


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


# --- Tutorial guiado (spotlight) ----------------------------------------------

def test_tutorial_inicia_sozinho_na_primeira_visita_a_comunidade(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)

        html = logged_in_client.get(f"/comunidade/{comunidade.id}").data.decode("utf-8")
        assert 'id="tutorial-dados"' in html
        assert '"autoIniciar": true' in html
        assert "Bem-vindo a sua comunidade" in html


def test_marcar_tutorial_visto_impede_iniciar_sozinho_mas_dados_continuam_no_html(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)

        resposta = logged_in_client.post("/tutorial-comunidade-visto")
        assert resposta.status_code == 200
        assert resposta.get_json() == {"ok": True}

        # O bloco de dados continua no HTML (o botao de rever tutorial no
        # cabecalho depende dele pra funcionar a qualquer momento) -- so o
        # disparo automatico e que fica desligado.
        html = logged_in_client.get(f"/comunidade/{comunidade.id}").data.decode("utf-8")
        assert 'id="tutorial-dados"' in html
        assert '"autoIniciar": false' in html
        assert 'data-tutorial-reiniciar' in html


def test_tutorial_visto_sem_login_redireciona(client):
    response = client.post("/tutorial-comunidade-visto", follow_redirects=False)
    assert response.status_code == 302


# --- Calendario da comunidade (junta escalas de todos os Ministerios) -------

def test_calendario_da_comunidade_junta_escalas_de_ministerios_diferentes(logged_in_client, app, db):
    import datetime as dt

    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio_a = _criar_ministerio(logged_in_client, comunidade.id, "Louvor")
        ministerio_b = _criar_ministerio(logged_in_client, comunidade.id, "Midia")

        hoje = dt.date.today()
        data_str = hoje.strftime("%Y-%m-%d")
        _criar_escala(logged_in_client, ministerio_a.id, "Ensaio Louvor", data=data_str, horario="19:00")
        _criar_escala(logged_in_client, ministerio_b.id, "Ensaio Midia", departamento="Midia",
                       data=data_str, horario="20:00")

        response = logged_in_client.get(f"/comunidade/{comunidade.id}/calendario")
        html = response.data.decode("utf-8")

        assert response.status_code == 200
        assert "Ensaio Louvor" in html
        assert "Ensaio Midia" in html
        assert "Louvor" in html and "Midia" in html  # nome do ministerio no titulo do evento


def test_calendario_da_comunidade_sem_login_redireciona(client):
    response = client.get("/comunidade/1/calendario", follow_redirects=False)
    assert response.status_code == 302


def test_calendario_da_comunidade_exige_vinculo(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade = _criar_comunidade(logged_in_client)
        comunidade_id = comunidade.id

    with sessao_isolada(app):
        response = outro_logged_in_client.get(f"/comunidade/{comunidade_id}/calendario")
        assert response.status_code == 404


# --- Diretorio de lideres ----------------------------------------------------

def test_diretorio_de_lideres_mostra_admin_com_todos_os_ministerios(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        _criar_ministerio(logged_in_client, comunidade.id, "Louvor")
        _criar_ministerio(logged_in_client, comunidade.id, "Midia")

        html = logged_in_client.get(f"/comunidade/{comunidade.id}/lideres").data.decode("utf-8")

        assert "ana@example.com" in html
        assert "Admin" in html
        assert "Louvor" in html
        assert "Midia" in html


def test_diretorio_de_lideres_mostra_lider_so_do_proprio_ministerio(logged_in_client, outro_logged_in_client, app, db):
    from app.auth.models import User
    from app.ministerio.models import UsuarioMinisterio

    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio_a = _criar_ministerio(logged_in_client, comunidade.id, "Louvor")
        _criar_ministerio(logged_in_client, comunidade.id, "Midia")

        bruno = User.query.filter_by(email="bruno@example.com").first()
        db.session.add(UsuarioMinisterio(usuario_id=bruno.id, ministerio_id=ministerio_a.id, papel="lider"))
        db.session.commit()

        html = logged_in_client.get(f"/comunidade/{comunidade.id}/lideres").data.decode("utf-8")

        assert "bruno@example.com" in html
        # Bruno aparece vinculado a Louvor mas nao tem o selo de Admin
        idx_bruno = html.index("bruno@example.com")
        bloco_bruno = html[max(0, idx_bruno - 700):idx_bruno + 700]
        assert "Louvor" in bloco_bruno


def test_diretorio_de_lideres_sem_login_redireciona(client):
    response = client.get("/comunidade/1/lideres", follow_redirects=False)
    assert response.status_code == 302


# --- Excluir comunidade so na lista (nao mais dentro da tela da comunidade) -

def test_botao_excluir_fica_na_lista_nao_na_tela_da_comunidade(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)

        html_lista = logged_in_client.get("/comunidade/").data.decode("utf-8")
        assert f'data-excluir-item="/comunidade/{comunidade.id}/excluir"' in html_lista

        html_detalhe = logged_in_client.get(f"/comunidade/{comunidade.id}").data.decode("utf-8")
        assert f'/comunidade/{comunidade.id}/excluir' not in html_detalhe


# --- Contagem de membros (diretorio + contas vinculadas) --------------------


def test_contagem_de_membros_inclui_quem_entrou_via_link(logged_in_client, app, db):
    """Bug relatado: quem entra via link de convite (UsuarioComunidade) nao
    contava em "Membros (N)" na tela da comunidade -- so o diretorio de
    escalacao (Membro) era contado, entao a quantidade nao mudava quando
    alguem de fato entrava."""
    from app.auth.models import User

    with sessao_isolada(app):
        comunidade = _criar_comunidade(logged_in_client, "Comunidade Ana")
        comunidade_id = comunidade.id
        logged_in_client.post(f"/comunidade/{comunidade_id}/papeis/link/gerar", follow_redirects=True)
        token = db.session.get(Comunidade, comunidade_id).token_convite_publico

        # Quem criou a comunidade ja conta como 1 (vira admin automaticamente).
        html_antes = logged_in_client.get(f"/comunidade/{comunidade_id}").data.decode("utf-8")
        assert "Membros" in html_antes and "(1)" in html_antes

    with sessao_isolada(app):
        bruno_client = app.test_client()
        _registrar(bruno_client, "bruno", "bruno@example.com")
        bruno_client.post(f"/comunidade/entrar/{token}", follow_redirects=True)

    with sessao_isolada(app):
        html_depois = logged_in_client.get(f"/comunidade/{comunidade_id}").data.decode("utf-8")
        assert "(2)" in html_depois


def test_contagem_de_membros_nao_duplica_quem_esta_no_diretorio_e_tem_conta(logged_in_client, app, db):
    """Quem ja esta no diretorio (Membro, por e-mail) e tambem entra via
    link com o mesmo e-mail conta so 1 vez, nao 2."""
    with sessao_isolada(app):
        comunidade = _criar_comunidade(logged_in_client, "Comunidade Ana")
        comunidade_id = comunidade.id
        _criar_membro(logged_in_client, comunidade_id, "Bruno", email="bruno@example.com")
        logged_in_client.post(f"/comunidade/{comunidade_id}/papeis/link/gerar", follow_redirects=True)
        token = db.session.get(Comunidade, comunidade_id).token_convite_publico

        # Ana (admin) + Bruno (diretorio) = 2, antes de Bruno ter conta.
        html_antes = logged_in_client.get(f"/comunidade/{comunidade_id}").data.decode("utf-8")
        assert "(2)" in html_antes

    with sessao_isolada(app):
        bruno_client = app.test_client()
        _registrar(bruno_client, "bruno", "bruno@example.com")
        bruno_client.post(f"/comunidade/entrar/{token}", follow_redirects=True)

    with sessao_isolada(app):
        # Mesmo e-mail do diretorio -- continua 2, nao vira 3.
        html_depois = logged_in_client.get(f"/comunidade/{comunidade_id}").data.decode("utf-8")
        assert "(2)" in html_depois


# --- Notificacao ao entrar via link ------------------------------------------


def test_admin_e_notificado_quando_alguem_entra_via_link(logged_in_client, app, db):
    from app.notificacoes import Notificacao
    from app.auth.models import User

    with sessao_isolada(app):
        comunidade = _criar_comunidade(logged_in_client, "Comunidade Ana")
        comunidade_id = comunidade.id
        logged_in_client.post(f"/comunidade/{comunidade_id}/papeis/link/gerar", follow_redirects=True)
        token = db.session.get(Comunidade, comunidade_id).token_convite_publico

    with sessao_isolada(app):
        bruno_client = app.test_client()
        _registrar(bruno_client, "bruno", "bruno@example.com")
        bruno_client.post(f"/comunidade/entrar/{token}", follow_redirects=True)

    with sessao_isolada(app):
        ana = User.query.filter_by(email="ana@example.com").first()
        notificacao = Notificacao.query.filter_by(usuario_id=ana.id, tipo="novo_membro").first()
        assert notificacao is not None
        assert "bruno" in notificacao.titulo.lower()
