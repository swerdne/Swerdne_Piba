"""Link de acesso direto (Comunidade e Ministerio) -- entrada como membro
comum sem convite individual, convivendo com o convite por e-mail."""
from app.auth.models import User
from app.comunidade.models import Comunidade, UsuarioComunidade
from app.convites.models import Convite
from app.ministerio.models import Ministerio, UsuarioMinisterio
from app.notificacoes import Notificacao
from tests.conftest import _registrar, sessao_isolada
from tests.test_escala import _criar_comunidade, _criar_ministerio

# Cabecalhos que o navegador manda quando a pessoa ABRE o link.
NAVEGAR = {"Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document", "Sec-Fetch-Site": "none"}


def _link_comunidade(cliente):
    comunidade = _criar_comunidade(cliente, "Igreja Ana")
    cliente.post(f"/comunidade/{comunidade.id}/papeis/link/gerar")
    return comunidade.id, Comunidade.objects(id=comunidade.id).first().token_convite_publico


def _link_ministerio(cliente):
    comunidade = _criar_comunidade(cliente, "Igreja Ana")
    ministerio = _criar_ministerio(cliente, comunidade.id, nome="Louvor")
    cliente.post(f"/ministerio/{ministerio.id}/papeis/link/gerar")
    return comunidade.id, ministerio.id, Ministerio.objects(id=ministerio.id).first().token_convite_publico


def _usuario(email):
    return User.objects(email=email).first()


# --- Comunidade ----------------------------------------------------------------

def test_logado_abre_o_link_e_ja_entra(logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade_id, token = _link_comunidade(logged_in_client)
    with sessao_isolada(app):
        bruno = app.test_client()
        _registrar(bruno, "bruno", "bruno@example.com")
        resposta = bruno.get(f"/comunidade/entrar/{token}", headers=NAVEGAR)
        assert resposta.status_code == 302
        assert resposta.headers["Location"] == f"/comunidade/{comunidade_id}/escalados"
        papel = UsuarioComunidade.objects(usuario_id=_usuario("bruno@example.com").id, comunidade_id=comunidade_id).first()
        assert papel.papel == "membro"

        ana = _usuario("ana@example.com")
        aviso = Notificacao.objects(usuario_id=ana.id, tipo="novo_membro").first()
        assert aviso is not None and "bruno" in aviso.titulo


def test_prefetch_ou_imagem_embutida_nao_inscreve(logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade_id, token = _link_comunidade(logged_in_client)
    with sessao_isolada(app):
        bruno = app.test_client()
        _registrar(bruno, "bruno", "bruno@example.com")
        bruno.get(f"/comunidade/entrar/{token}", headers={**NAVEGAR, "Sec-Purpose": "prefetch"})
        bruno.get(f"/comunidade/entrar/{token}", headers={"Sec-Fetch-Mode": "no-cors", "Sec-Fetch-Dest": "image"})
        assert UsuarioComunidade.objects(usuario_id=_usuario("bruno@example.com").id, comunidade_id=comunidade_id).count() == 0


def test_sem_conta_cadastra_pelo_link_e_entra_sozinho(logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade_id, token = _link_comunidade(logged_in_client)
    with sessao_isolada(app):
        visitante = app.test_client()
        tela = visitante.get(f"/comunidade/entrar/{token}").data.decode("utf-8")
        assert "Criar conta" in tela and "Continuar com Google" in tela

        resposta = visitante.post("/auth/register", data={
            "username": "carla", "email": "carla@example.com", "password": "senha123", "confirm": "senha123",
        })
        assert resposta.headers["Location"] == f"/comunidade/{comunidade_id}/escalados"
        carla = _usuario("carla@example.com")
        assert UsuarioComunidade.objects(usuario_id=carla.id, comunidade_id=comunidade_id).first().papel == "membro"


def test_link_revogado_antes_do_cadastro_nao_inscreve(logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade_id, token = _link_comunidade(logged_in_client)
    with sessao_isolada(app):
        visitante = app.test_client()
        visitante.get(f"/comunidade/entrar/{token}")
    with sessao_isolada(app):
        logged_in_client.post(f"/comunidade/{comunidade_id}/papeis/link/gerar")  # revoga
    with sessao_isolada(app):
        resposta = visitante.post("/auth/register", data={
            "username": "carla", "email": "carla@example.com", "password": "senha123", "confirm": "senha123",
        })
        assert resposta.headers["Location"].endswith("/dashboard") or resposta.headers["Location"] == "/"
        assert UsuarioComunidade.objects(usuario_id=_usuario("carla@example.com").id).count() == 0


def test_link_nunca_rebaixa_admin(logged_in_client, app, db):
    with app.app_context():
        comunidade_id, token = _link_comunidade(logged_in_client)
        logged_in_client.get(f"/comunidade/entrar/{token}", headers=NAVEGAR)
        ana = _usuario("ana@example.com")
        assert UsuarioComunidade.objects(usuario_id=ana.id, comunidade_id=comunidade_id).first().papel == "admin"
        assert Notificacao.objects(tipo="novo_membro").count() == 0


# --- Ministerio ----------------------------------------------------------------

def test_lider_gera_e_revoga_link_do_ministerio(logged_in_client, app, db):
    with app.app_context():
        _, ministerio_id, token = _link_ministerio(logged_in_client)
        assert token and len(token) <= 15
        html = logged_in_client.get(f"/ministerio/{ministerio_id}/papeis").data.decode("utf-8")
        assert f"/ministerio/entrar/{token}" in html and "Link de acesso direto" in html

        logged_in_client.post(f"/ministerio/{ministerio_id}/papeis/link/gerar")
        novo = Ministerio.objects(id=ministerio_id).first().token_convite_publico
        assert novo != token
        assert logged_in_client.get(f"/ministerio/entrar/{token}").status_code == 404


def test_quem_nao_lidera_nao_gera_link(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        _, ministerio_id, token = _link_ministerio(logged_in_client)
    with sessao_isolada(app):
        assert outro_logged_in_client.post(f"/ministerio/{ministerio_id}/papeis/link/gerar").status_code == 404
        assert Ministerio.objects(id=ministerio_id).first().token_convite_publico == token


def test_entrar_no_ministerio_pelo_link_vira_membro_e_avisa_lideres(logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade_id, ministerio_id, token = _link_ministerio(logged_in_client)
    with sessao_isolada(app):
        bruno = app.test_client()
        _registrar(bruno, "bruno", "bruno@example.com")
        resposta = bruno.get(f"/ministerio/entrar/{token}", headers=NAVEGAR)
        assert resposta.headers["Location"] == f"/ministerio/{ministerio_id}"

        id_bruno = _usuario("bruno@example.com").id
        assert UsuarioMinisterio.objects(usuario_id=id_bruno, ministerio_id=ministerio_id).first().papel == "membro"
        # tambem vira membro comum da comunidade do ministerio
        assert UsuarioComunidade.objects(usuario_id=id_bruno, comunidade_id=comunidade_id).first().papel == "membro"
        assert bruno.get(f"/ministerio/{ministerio_id}").status_code == 200

        ana = _usuario("ana@example.com")
        aviso = Notificacao.objects(usuario_id=ana.id, tipo="novo_membro").first()
        assert aviso is not None and '"Louvor"' in aviso.titulo


def test_sem_conta_entra_no_ministerio_depois_do_login(logged_in_client, app, db):
    with sessao_isolada(app):
        _, ministerio_id, token = _link_ministerio(logged_in_client)
    with sessao_isolada(app):
        _registrar(app.test_client(), "bruno", "bruno@example.com")  # conta ja existe, mas nao esta logado
    with sessao_isolada(app):
        visitante = app.test_client()
        tela = visitante.get(f"/ministerio/entrar/{token}").data.decode("utf-8")
        assert "Louvor" in tela and "Igreja Ana" in tela
        resposta = visitante.post("/auth/login", data={"email": "bruno@example.com", "password": "senha123"})
        assert resposta.headers["Location"] == f"/ministerio/{ministerio_id}"
        assert UsuarioMinisterio.objects(usuario_id=_usuario("bruno@example.com").id, ministerio_id=ministerio_id).count() == 1


def test_link_nao_rebaixa_lider_e_convite_por_email_continua(logged_in_client, app, db):
    """Os dois metodos convivem: o convite por e-mail ainda da papel de lider
    (com aceite), e o link nunca tira esse papel."""
    with sessao_isolada(app):
        _, ministerio_id, token = _link_ministerio(logged_in_client)
        logged_in_client.post(f"/ministerio/{ministerio_id}/papeis", data={"email": "bruno@example.com", "papel": "lider"})
        convite = Convite.objects(email="bruno@example.com").first()
        assert convite.papel == "lider" and convite.status == "pendente"
    with sessao_isolada(app):
        bruno = app.test_client()
        _registrar(bruno, "bruno", "bruno@example.com")
        bruno.post(f"/convite/{convite.token}/aceitar")
        bruno.get(f"/ministerio/entrar/{token}", headers=NAVEGAR)
        papel = UsuarioMinisterio.objects(usuario_id=_usuario("bruno@example.com").id, ministerio_id=ministerio_id).first()
        assert papel.papel == "lider"
