"""Quem entra na comunidade (link/convite) aparece pro admin como "Aguardando
entrar no diretorio", com Aceitar/Recusar."""
from app.auth.models import User
from app.comunidade.models import Comunidade, UsuarioComunidade
from app.escala.models import Membro
from tests.conftest import _registrar, sessao_isolada
from tests.test_escala import _criar_comunidade, _criar_membro

NAVEGAR = {"Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"}


def _comunidade_com_entradas(app, logged_in_client, *pessoas):
    with sessao_isolada(app):
        comunidade = _criar_comunidade(logged_in_client, "PIBA")
        logged_in_client.post(f"/comunidade/{comunidade.id}/papeis/link/gerar")
        token = Comunidade.objects(id=comunidade.id).first().token_convite_publico
    for usuario, email in pessoas:
        with sessao_isolada(app):
            cliente = app.test_client()
            _registrar(cliente, usuario, email)
            cliente.get(f"/comunidade/entrar/{token}", headers=NAVEGAR)
    return comunidade.id


def _conta(comunidade_id, email):
    usuario = User.objects(email=email).first()
    return UsuarioComunidade.objects(usuario_id=usuario.id, comunidade_id=comunidade_id).first()


def test_quem_entrou_pelo_link_aparece_aguardando(logged_in_client, app, db):
    comunidade_id = _comunidade_com_entradas(app, logged_in_client, ("raony", "raony@example.com"))
    with sessao_isolada(app):
        html = logged_in_client.get(f"/comunidade/{comunidade_id}/membros").data.decode("utf-8")
        assert "Aguardando entrar no diretorio (1)" in html and "raony@example.com" in html
        # a propria admin (ana) nao aparece como pedido
        secao_pedidos = html.split("Aguardando entrar no diretorio")[1].split("Adicionar ao diretorio")[0]
        assert "ana@example.com" not in secao_pedidos
        detalhe = logged_in_client.get(f"/comunidade/{comunidade_id}").data.decode("utf-8")
        assert "1 aguardando" in detalhe


def test_aceitar_coloca_no_diretorio_com_nome_e_email(logged_in_client, app, db):
    comunidade_id = _comunidade_com_entradas(app, logged_in_client, ("raony", "raony@example.com"))
    with sessao_isolada(app):
        conta = _conta(comunidade_id, "raony@example.com")
        logged_in_client.post(f"/comunidade/{comunidade_id}/membros/pedidos/{conta.id}/aceitar")
        membro = Membro.objects(comunidade_id=comunidade_id, email="raony@example.com").first()
        assert membro is not None and membro.nome == "raony"
        html = logged_in_client.get(f"/comunidade/{comunidade_id}/membros").data.decode("utf-8")
        assert "Aguardando entrar no diretorio" not in html
        # aceitar de novo nao duplica
        logged_in_client.post(f"/comunidade/{comunidade_id}/membros/pedidos/{conta.id}/aceitar")
        assert Membro.objects(comunidade_id=comunidade_id, email="raony@example.com").count() == 1


def test_recusar_tira_da_lista_mas_mantem_na_comunidade(logged_in_client, app, db):
    comunidade_id = _comunidade_com_entradas(app, logged_in_client, ("raony", "raony@example.com"))
    with sessao_isolada(app):
        conta = _conta(comunidade_id, "raony@example.com")
        logged_in_client.post(f"/comunidade/{comunidade_id}/membros/pedidos/{conta.id}/recusar")
        assert Membro.objects(comunidade_id=comunidade_id).count() == 0
        conta.reload()
        assert conta.diretorio_recusado and conta.papel == "membro"
        html = logged_in_client.get(f"/comunidade/{comunidade_id}/membros").data.decode("utf-8")
        assert "Aguardando entrar no diretorio" not in html
        # da pra colocar depois pela lista de contas
        assert f"/membros/pedidos/{conta.id}/aceitar" in html


def test_quem_ja_esta_no_diretorio_nao_vira_pedido(logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade = _criar_comunidade(logged_in_client, "PIBA")
        _criar_membro(logged_in_client, comunidade.id, "Raony Amaral", email="Raony@Example.com")
        logged_in_client.post(f"/comunidade/{comunidade.id}/papeis/link/gerar")
        token = Comunidade.objects(id=comunidade.id).first().token_convite_publico
    with sessao_isolada(app):
        cliente = app.test_client()
        _registrar(cliente, "raony", "raony@example.com")
        cliente.get(f"/comunidade/entrar/{token}", headers=NAVEGAR)
    with sessao_isolada(app):
        html = logged_in_client.get(f"/comunidade/{comunidade.id}/membros").data.decode("utf-8")
        assert "Aguardando entrar no diretorio" not in html


def test_aceitar_todos(logged_in_client, app, db):
    comunidade_id = _comunidade_com_entradas(
        app, logged_in_client, ("raony", "raony@example.com"), ("raquel", "raquel@example.com"),
    )
    with sessao_isolada(app):
        logged_in_client.post(f"/comunidade/{comunidade_id}/membros/pedidos/aceitar-todos")
        emails = sorted(m.email for m in Membro.objects(comunidade_id=comunidade_id))
        assert emails == ["raony@example.com", "raquel@example.com"]


def test_so_admin_responde_pedido(logged_in_client, app, db):
    comunidade_id = _comunidade_com_entradas(app, logged_in_client, ("raony", "raony@example.com"))
    with sessao_isolada(app):
        conta = _conta(comunidade_id, "raony@example.com")
        raony = app.test_client()
        raony.post("/auth/login", data={"email": "raony@example.com", "password": "senha123"})
        assert raony.post(f"/comunidade/{comunidade_id}/membros/pedidos/{conta.id}/aceitar").status_code == 404
        assert Membro.objects(comunidade_id=comunidade_id).count() == 0
