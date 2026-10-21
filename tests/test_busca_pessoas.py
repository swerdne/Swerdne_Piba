"""Campo "Buscar pelo nome" nas listas de pessoas (Membros e Papeis): o
filtro roda no navegador (main.js, [data-busca-pessoas]); aqui confere que a
tela entrega o campo e cada pessoa com o texto que a busca procura."""
from app.escala.models import Membro
from tests.test_escala import _criar_comunidade, _criar_ministerio


def test_membros_tem_busca_e_cada_pessoa_e_pesquisavel(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client, "Igreja")
        url = f"/comunidade/{comunidade.id}/membros"
        Membro(comunidade_id=comunidade.id, nome="João Ávila", email="joao@ex.com").save()
        Membro(comunidade_id=comunidade.id, nome="Bia").save()
        html = logged_in_client.get(url).data.decode()
        assert "data-busca-pessoas" in html and 'placeholder="Buscar pelo nome"' in html
        assert 'data-busca-item="João Ávila joao@ex.com"' in html
        assert 'data-busca-item="Bia "' in html
        assert html.count("data-busca-lista") == 1 and html.count("data-busca-vazio") == 1
        # conta vinculada (quem criou a comunidade) tambem entra na busca
        assert html.count("data-busca-item=") >= 3


def test_papeis_do_ministerio_so_mostra_busca_com_lista_grande(logged_in_client, app, db):
    from app.auth.models import User
    from app.ministerio.models import UsuarioMinisterio

    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client, "Igreja")
        louvor = _criar_ministerio(logged_in_client, comunidade.id, nome="Louvor")
        url = f"/ministerio/{louvor.id}/papeis"
        assert "data-busca-pessoas" not in logged_in_client.get(url).data.decode()
        for i in range(6):
            conta = User(username=f"pessoa{i}", email=f"pessoa{i}@ex.com", name=f"Pessoa {i}")
            conta.set_password("senha12345")
            conta.save()
            UsuarioMinisterio(ministerio_id=louvor.id, usuario_id=conta.id, papel="membro").save()
        html = logged_in_client.get(url).data.decode()
        assert "data-busca-pessoas" in html and 'data-busca-item="Pessoa 3 pessoa3 pessoa3@ex.com"' in html
