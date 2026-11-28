"""Fase 3, item 7: convite por link ou QR com validade, limite de entradas e
papel de entrada (no ministerio)."""
from datetime import datetime, timedelta, timezone

from app.comunidade.models import Comunidade, UsuarioComunidade
from app.ministerio.models import Ministerio, UsuarioMinisterio
from tests.conftest import _registrar, sessao_isolada
from tests.test_escala import _criar_comunidade, _criar_ministerio
from tests.test_link_acesso import NAVEGAR


def _nova_pessoa(app, nome):
    cliente = app.test_client()
    with sessao_isolada(app):
        _registrar(cliente, nome, f"{nome}@example.com")
    return cliente


def _id(email):
    from app.auth.models import User

    return User.objects(email=email).first().id


def test_gerar_link_com_validade_e_limite(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client, "Igreja")
        logged_in_client.post(f"/comunidade/{comunidade.id}/papeis/link/gerar", data={"validade": "7", "limite": "10"})
        c = Comunidade.objects(id=comunidade.id).first()
        assert c.convite_limite_usos == 10 and c.convite_usos == 0
        expira = c.convite_expira_em.replace(tzinfo=timezone.utc)
        assert timedelta(days=6, hours=23) < expira - datetime.now(timezone.utc) <= timedelta(days=7)
        html = logged_in_client.get(f"/comunidade/{comunidade.id}/membros").get_data(as_text=True)
        assert "data-regras-link" in html and "0 de 10 entradas" in html and "entra como membro" in html
        assert "data-qr-convite" in html and "qrcode.min.js" in html


def test_limite_de_entradas(logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade = _criar_comunidade(logged_in_client, "Igreja")
        logged_in_client.post(f"/comunidade/{comunidade.id}/papeis/link/gerar", data={"validade": "0", "limite": "5"})
        Comunidade.objects(id=comunidade.id).update(set__convite_limite_usos=1)  # 1 vaga so, pro teste
        token = Comunidade.objects(id=comunidade.id).first().token_convite_publico
    bruno, carla = _nova_pessoa(app, "bruno"), _nova_pessoa(app, "carla")
    with sessao_isolada(app):
        bruno.get(f"/comunidade/entrar/{token}", headers=NAVEGAR)
        assert UsuarioComunidade.objects(usuario_id=_id("bruno@example.com"), comunidade_id=comunidade.id).count() == 1
    with sessao_isolada(app):
        html = carla.get(f"/comunidade/entrar/{token}", headers=NAVEGAR).get_data(as_text=True)
        assert "número máximo de pessoas" in html
        assert UsuarioComunidade.objects(usuario_id=_id("carla@example.com"), comunidade_id=comunidade.id).count() == 0
    with sessao_isolada(app):
        # Quem ja entrou continua podendo abrir o link.
        assert bruno.get(f"/comunidade/entrar/{token}", headers=NAVEGAR).status_code == 302


def test_link_expirado(logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade = _criar_comunidade(logged_in_client, "Igreja")
        logged_in_client.post(f"/comunidade/{comunidade.id}/papeis/link/gerar", data={"validade": "1", "limite": "0"})
        Comunidade.objects(id=comunidade.id).update(set__convite_expira_em=datetime.now(timezone.utc) - timedelta(minutes=1))
        token = Comunidade.objects(id=comunidade.id).first().token_convite_publico
    bruno = _nova_pessoa(app, "bruno")
    with sessao_isolada(app):
        html = bruno.get(f"/comunidade/entrar/{token}", headers=NAVEGAR).get_data(as_text=True)
        assert "Este link de convite expirou" in html and "data-erro-link" in html
        assert UsuarioComunidade.objects(usuario_id=_id("bruno@example.com"), comunidade_id=comunidade.id).count() == 0
    # Sem conta: o link expirado avisa antes de mandar se cadastrar.
    with sessao_isolada(app):
        assert "expirou" in app.test_client().get(f"/comunidade/entrar/{token}").get_data(as_text=True)


def test_link_do_ministerio_pode_dar_lider(logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade = _criar_comunidade(logged_in_client, "Igreja")
        ministerio = _criar_ministerio(logged_in_client, comunidade.id, nome="Louvor")
        logged_in_client.post(f"/ministerio/{ministerio.id}/papeis/link/gerar",
                              data={"validade": "30", "limite": "0", "papel_link": "lider"})
        m = Ministerio.objects(id=ministerio.id).first()
        assert m.convite_papel == "lider"
        html = logged_in_client.get(f"/ministerio/{ministerio.id}/papeis").get_data(as_text=True)
        assert "entra como líder" in html and 'name="papel_link"' in html
    bruno = _nova_pessoa(app, "bruno")
    with sessao_isolada(app):
        bruno.get(f"/ministerio/entrar/{m.token_convite_publico}", headers=NAVEGAR)
        papel = UsuarioMinisterio.objects(usuario_id=_id("bruno@example.com"), ministerio_id=ministerio.id).first()
        assert papel.papel == "lider"
        assert Ministerio.objects(id=ministerio.id).first().convite_usos == 1


def test_link_da_comunidade_nunca_da_admin(logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade = _criar_comunidade(logged_in_client, "Igreja")
        logged_in_client.post(f"/comunidade/{comunidade.id}/papeis/link/gerar",
                              data={"validade": "0", "limite": "0", "papel_link": "admin"})
        token = Comunidade.objects(id=comunidade.id).first().token_convite_publico
        html = logged_in_client.get(f"/comunidade/{comunidade.id}/membros").get_data(as_text=True)
        assert 'name="papel_link"' not in html
    bruno = _nova_pessoa(app, "bruno")
    with sessao_isolada(app):
        bruno.get(f"/comunidade/entrar/{token}", headers=NAVEGAR)
        papel = UsuarioComunidade.objects(usuario_id=_id("bruno@example.com"), comunidade_id=comunidade.id).first()
        assert papel.papel == "membro"


def test_gerar_de_novo_zera_e_desliga_o_antigo(logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade = _criar_comunidade(logged_in_client, "Igreja")
        logged_in_client.post(f"/comunidade/{comunidade.id}/papeis/link/gerar", data={"validade": "7", "limite": "5"})
        antigo = Comunidade.objects(id=comunidade.id).first().token_convite_publico
        Comunidade.objects(id=comunidade.id).update(set__convite_usos=5)
        logged_in_client.post(f"/comunidade/{comunidade.id}/papeis/link/gerar", data={"validade": "0", "limite": "0"})
        c = Comunidade.objects(id=comunidade.id).first()
        assert c.token_convite_publico != antigo and c.convite_usos == 0 and c.convite_expira_em is None
    with sessao_isolada(app):
        assert app.test_client().get(f"/comunidade/entrar/{antigo}").status_code == 404
