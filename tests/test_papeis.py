"""Testes do sistema de papeis e convites (app/convites, UsuarioComunidade,
UsuarioMinisterio) -- hierarquia Super Admin > Admin da Comunidade > Lider de
Ministerio > Membro, concedida sempre via convite por e-mail aceito (exceto
o admin automatico de quem cria a comunidade).
"""
from app.auth.models import User
from app.comunidade.models import Comunidade, UsuarioComunidade
from app.ministerio.models import UsuarioMinisterio
from app.convites.models import Convite, STATUS_PENDENTE, STATUS_ACEITO, STATUS_RECUSADO
from tests.conftest import sessao_isolada
from tests.test_escala import _criar_comunidade, _criar_ministerio, _criar_escala, _funcao_por_nome


def _registrar(cliente, username, email):
    cliente.post(
        "/auth/register",
        data={"username": username, "email": email, "password": "senha123", "confirm": "senha123"},
        follow_redirects=True,
    )
    return User.objects(email=email).first()


def _convidar_comunidade(cliente, comunidade_id, email, papel):
    return cliente.post(
        f"/comunidade/{comunidade_id}/papeis", data={"email": email, "papel": papel}, follow_redirects=True
    )


def _convidar_ministerio(cliente, ministerio_id, email, papel):
    return cliente.post(
        f"/ministerio/{ministerio_id}/papeis", data={"email": email, "papel": papel}, follow_redirects=True
    )


def _convite_de(email, escopo_tipo, escopo_id):
    return (
        Convite.objects(escopo_tipo=escopo_tipo, escopo_id=escopo_id, email=email)
        .order_by("-id")
        .first()
    )


# --- Admin automatico do criador ------------------------------------------------

def test_criador_da_comunidade_vira_admin_automaticamente(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        usuario = User.objects(email="ana@example.com").first()
        papel = UsuarioComunidade.objects(usuario_id=usuario.id, comunidade_id=comunidade.id).first()
        assert papel is not None
        assert papel.papel == "admin"


# --- Convite de comunidade -------------------------------------------------------

def test_admin_convida_admin_e_membro_na_comunidade(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)

        r1 = _convidar_comunidade(logged_in_client, comunidade.id, "novo1@example.com", "admin")
        assert r1.status_code == 200
        r2 = _convidar_comunidade(logged_in_client, comunidade.id, "novo2@example.com", "membro")
        assert r2.status_code == 200

        assert _convite_de("novo1@example.com", "comunidade", comunidade.id).papel == "admin"
        assert _convite_de("novo2@example.com", "comunidade", comunidade.id).papel == "membro"


def test_convite_de_comunidade_fica_pendente_sem_dar_acesso(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade = _criar_comunidade(logged_in_client, "Comunidade Ana")
        comunidade_id = comunidade.id
        _convidar_comunidade(logged_in_client, comunidade_id, "bruno@example.com", "admin")

    with sessao_isolada(app):
        # bruno (outro_logged_in_client) ainda NAO tem acesso -- convite pendente
        assert outro_logged_in_client.get(f"/comunidade/{comunidade_id}").status_code == 404
        convite = _convite_de("bruno@example.com", "comunidade", comunidade_id)
        assert convite.status == STATUS_PENDENTE


def test_nao_admin_nao_acessa_tela_de_papeis(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade = _criar_comunidade(logged_in_client, "Comunidade Ana")
        comunidade_id = comunidade.id

    with sessao_isolada(app):
        response = outro_logged_in_client.get(f"/comunidade/{comunidade_id}/papeis")
        assert response.status_code == 404


# --- Alterar papel (promover membro a admin / rebaixar admin a membro) ----------

def test_admin_promove_membro_a_admin(logged_in_client, app, db):
    # Setup e acao em sessao_isolada separadas: registrar bruno (um segundo
    # "login" de fato, via app.test_client()) dentro do MESMO app_context da
    # acao contaminaria o cache de current_user do Flask-Login (preso a
    # flask.g, ver sessao_isolada em conftest.py) e a acao seguinte, feita
    # como ana, seria avaliada com o usuario errado.
    with sessao_isolada(app):
        comunidade = _criar_comunidade(logged_in_client)
        comunidade_id = comunidade.id
        bruno = _registrar(app.test_client(), "bruno", "bruno@example.com")
        UsuarioComunidade(usuario_id=bruno.id, comunidade_id=comunidade_id, papel="membro").save()
        papel_bruno_id = UsuarioComunidade.objects(usuario_id=bruno.id, comunidade_id=comunidade_id).first().id

    with sessao_isolada(app):
        response = logged_in_client.post(
            f"/comunidade/{comunidade_id}/papeis/{papel_bruno_id}/alterar-papel", follow_redirects=True
        )
        assert response.status_code == 200
        assert "agora e administrador".encode() in response.data

        atualizado = UsuarioComunidade.objects(id=papel_bruno_id).first()
        assert atualizado.papel == "admin"


def test_admin_rebaixa_outro_admin_a_membro(logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade = _criar_comunidade(logged_in_client)
        comunidade_id = comunidade.id
        bruno = _registrar(app.test_client(), "bruno", "bruno@example.com")
        UsuarioComunidade(usuario_id=bruno.id, comunidade_id=comunidade_id, papel="admin").save()
        papel_bruno_id = UsuarioComunidade.objects(usuario_id=bruno.id, comunidade_id=comunidade_id).first().id

    with sessao_isolada(app):
        response = logged_in_client.post(
            f"/comunidade/{comunidade_id}/papeis/{papel_bruno_id}/alterar-papel", follow_redirects=True
        )
        assert response.status_code == 200
        assert "agora e membro".encode() in response.data

        atualizado = UsuarioComunidade.objects(id=papel_bruno_id).first()
        assert atualizado.papel == "membro"


def test_nao_pode_rebaixar_o_ultimo_admin(logged_in_client, app, db):
    """Sem esse bloqueio, o unico admin poderia se rebaixar (ou rebaixar o
    unico outro admin) e ninguem mais conseguiria acessar /papeis pra
    reverter -- ver comentario em alterar_papel."""
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ana = User.objects(email="ana@example.com").first()
        papel_ana = UsuarioComunidade.objects(usuario_id=ana.id, comunidade_id=comunidade.id).first()

        response = logged_in_client.post(
            f"/comunidade/{comunidade.id}/papeis/{papel_ana.id}/alterar-papel", follow_redirects=True
        )
        assert response.status_code == 200
        assert "ultimo administrador".encode() in response.data

        atualizado = UsuarioComunidade.objects(id=papel_ana.id).first()
        assert atualizado.papel == "admin"


def test_nao_admin_nao_pode_alterar_papel(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade = _criar_comunidade(logged_in_client, "Comunidade Ana")
        comunidade_id = comunidade.id
        ana = User.objects(email="ana@example.com").first()
        papel_ana_id = UsuarioComunidade.objects(usuario_id=ana.id, comunidade_id=comunidade_id).first().id

    with sessao_isolada(app):
        response = outro_logged_in_client.post(f"/comunidade/{comunidade_id}/papeis/{papel_ana_id}/alterar-papel")
        assert response.status_code == 404


# --- Aceitar/recusar convite -------------------------------------------------

def test_aceitar_convite_de_comunidade_cria_papel_e_da_acesso(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade = _criar_comunidade(logged_in_client, "Comunidade Ana")
        comunidade_id = comunidade.id
        _convidar_comunidade(logged_in_client, comunidade_id, "bruno@example.com", "admin")
        token = _convite_de("bruno@example.com", "comunidade", comunidade_id).token

    with sessao_isolada(app):
        ver = outro_logged_in_client.get(f"/convite/{token}")
        assert ver.status_code == 200
        assert b"Aceitar" in ver.data

        aceitar = outro_logged_in_client.post(f"/convite/{token}/aceitar", data={}, follow_redirects=True)
        assert aceitar.status_code == 200

    with sessao_isolada(app):
        bruno = User.objects(email="bruno@example.com").first()
        papel = UsuarioComunidade.objects(usuario_id=bruno.id, comunidade_id=comunidade_id).first()
        assert papel is not None and papel.papel == "admin"
        assert _convite_de("bruno@example.com", "comunidade", comunidade_id).status == STATUS_ACEITO

        # agora bruno consegue acessar a tela de gestao da comunidade
        assert outro_logged_in_client.get(f"/comunidade/{comunidade_id}").status_code == 200


def test_recusar_convite_nao_cria_papel(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade = _criar_comunidade(logged_in_client, "Comunidade Ana")
        comunidade_id = comunidade.id
        _convidar_comunidade(logged_in_client, comunidade_id, "bruno@example.com", "membro")
        token = _convite_de("bruno@example.com", "comunidade", comunidade_id).token

    with sessao_isolada(app):
        response = outro_logged_in_client.post(f"/convite/{token}/recusar", data={}, follow_redirects=True)
        assert response.status_code == 200

    with sessao_isolada(app):
        bruno = User.objects(email="bruno@example.com").first()
        assert UsuarioComunidade.objects(usuario_id=bruno.id, comunidade_id=comunidade_id).first() is None
        convite = _convite_de("bruno@example.com", "comunidade", comunidade_id)
        assert convite.status == STATUS_RECUSADO
        assert outro_logged_in_client.get(f"/comunidade/{comunidade_id}").status_code == 404


def test_aceitar_convite_de_outro_email_e_rejeitado(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade = _criar_comunidade(logged_in_client, "Comunidade Ana")
        comunidade_id = comunidade.id
        # convite enviado pra um e-mail que NAO e nem ana nem bruno
        _convidar_comunidade(logged_in_client, comunidade_id, "terceiro@example.com", "membro")
        token = _convite_de("terceiro@example.com", "comunidade", comunidade_id).token

    with sessao_isolada(app):
        response = outro_logged_in_client.post(f"/convite/{token}/aceitar", data={}, follow_redirects=True)
        assert response.status_code == 200
        assert "outro e-mail" in response.data.decode("utf-8")

    with sessao_isolada(app):
        convite = _convite_de("terceiro@example.com", "comunidade", comunidade_id)
        assert convite.status == STATUS_PENDENTE


def test_aceitar_convite_ja_respondido_e_rejeitado(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade = _criar_comunidade(logged_in_client, "Comunidade Ana")
        comunidade_id = comunidade.id
        _convidar_comunidade(logged_in_client, comunidade_id, "bruno@example.com", "membro")
        token = _convite_de("bruno@example.com", "comunidade", comunidade_id).token

    with sessao_isolada(app):
        outro_logged_in_client.post(f"/convite/{token}/recusar", data={}, follow_redirects=True)
        response = outro_logged_in_client.post(f"/convite/{token}/aceitar", data={}, follow_redirects=True)
        assert response.status_code == 200
        assert "ja foi respondido" in response.data.decode("utf-8")

    with sessao_isolada(app):
        bruno = User.objects(email="bruno@example.com").first()
        assert UsuarioComunidade.objects(usuario_id=bruno.id, comunidade_id=comunidade_id).first() is None


def test_convite_pendente_mostra_tela_de_login_pra_quem_nao_tem_conta(logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade = _criar_comunidade(logged_in_client)
        _convidar_comunidade(logged_in_client, comunidade.id, "naoexiste@example.com", "membro")
        token = _convite_de("naoexiste@example.com", "comunidade", comunidade.id).token

    # sessao isolada de proposito: flask-login cacheia current_user em `g`,
    # preso ao app_context (ver docstring de sessao_isolada em conftest.py) --
    # sem um contexto novo, este client "anonimo" herdaria o login de ana.
    with sessao_isolada(app):
        client_anonimo = app.test_client()
        response = client_anonimo.get(f"/convite/{token}")
        assert response.status_code == 200
        html = response.data.decode("utf-8")
        assert "Criar conta" in html


# --- Hierarquia: quem pode conceder qual papel no ministerio -------------------

def test_papel_super_admin_nao_e_uma_escolha_valida_de_convite(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        total_antes = Convite.objects.count()
        # SelectField com validate_choice (padrao) rejeita valor fora das
        # choices -- "super_admin" nunca esta nas choices (PAPEIS_COMUNIDADE
        # so tem admin/membro), entao o form falha e nenhum convite e criado.
        response = _convidar_comunidade(logged_in_client, comunidade.id, "x@example.com", "super_admin")
        assert response.status_code == 200
        assert Convite.objects.count() == total_antes


def test_admin_da_comunidade_pode_convidar_lider_no_ministerio(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)

        response = _convidar_ministerio(logged_in_client, ministerio.id, "novo@example.com", "lider")
        assert response.status_code == 200
        assert _convite_de("novo@example.com", "ministerio", ministerio.id).papel == "lider"


def test_lider_so_pode_convidar_membro_nunca_lider_ou_admin(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade = _criar_comunidade(logged_in_client, "Comunidade Ana")
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        ministerio_id = ministerio.id

        _convidar_ministerio(logged_in_client, ministerio_id, "bruno@example.com", "lider")
        token = _convite_de("bruno@example.com", "ministerio", ministerio_id).token

    with sessao_isolada(app):
        outro_logged_in_client.post(f"/convite/{token}/aceitar", data={}, follow_redirects=True)

    with sessao_isolada(app):
        # bruno agora e lider -- consegue convidar "membro"...
        response = _convidar_ministerio(outro_logged_in_client, ministerio_id, "carlos@example.com", "membro")
        assert response.status_code == 200
        assert _convite_de("carlos@example.com", "ministerio", ministerio_id).papel == "membro"

        # ...mas NAO consegue conceder "lider" (nem manipulando o POST direto,
        # a escolha nem aparece nas choices do form pra ele) -- defesa em
        # profundidade confirma no servidor, nao so esconde na UI.
        total_antes = Convite.objects(escopo_tipo="ministerio", escopo_id=ministerio_id, papel="lider").count()
        outro_logged_in_client.post(
            f"/ministerio/{ministerio_id}/papeis", data={"email": "daniel@example.com", "papel": "lider"},
            follow_redirects=True,
        )
        total_depois = Convite.objects(escopo_tipo="ministerio", escopo_id=ministerio_id, papel="lider").count()
        assert total_depois == total_antes  # nao criou o convite de lider


def test_admin_da_comunidade_gerencia_qualquer_ministerio_sem_linha_propria(logged_in_client, app, db):
    """Admin da comunidade tem autoridade cascata sobre todo ministerio dela,
    mesmo sem uma linha em UsuarioMinisterio -- nao precisa se autoconvidar."""
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)

        assert UsuarioMinisterio.query.filter_by(ministerio_id=ministerio.id).count() == 0
        assert logged_in_client.get(f"/ministerio/{ministerio.id}/papeis").status_code == 200
        assert logged_in_client.get(f"/escala/ministerio/{ministerio.id}/nova").status_code == 200


# --- Visibilidade de membro comum -------------------------------------------------

def test_membro_do_ministerio_ve_escala_mas_nao_gerencia(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade = _criar_comunidade(logged_in_client, "Comunidade Ana")
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        ministerio_id = ministerio.id
        escala = _criar_escala(logged_in_client, ministerio_id, "Culto de Domingo")
        escala_id = escala.id

        _convidar_ministerio(logged_in_client, ministerio_id, "bruno@example.com", "membro")
        token = _convite_de("bruno@example.com", "ministerio", ministerio_id).token

    with sessao_isolada(app):
        outro_logged_in_client.post(f"/convite/{token}/aceitar", data={}, follow_redirects=True)

    with sessao_isolada(app):
        # membro ve o ministerio e a escala (leitura)...
        assert outro_logged_in_client.get(f"/ministerio/{ministerio_id}").status_code == 200
        assert outro_logged_in_client.get(f"/escala/{escala_id}").status_code == 200

        # ...mas nao gerencia: sem botao de nova escala, sem acesso a criar
        html = outro_logged_in_client.get(f"/ministerio/{ministerio_id}").data.decode("utf-8")
        assert "Nova escala" not in html
        assert outro_logged_in_client.get(f"/escala/ministerio/{ministerio_id}/nova").status_code == 404
        assert outro_logged_in_client.get(f"/ministerio/{ministerio_id}/papeis").status_code == 404


def test_membro_escalado_marca_o_proprio_status(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade = _criar_comunidade(logged_in_client, "Comunidade Ana")
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        escala = _criar_escala(logged_in_client, ministerio.id, "Culto de Domingo")
        baixo = _funcao_por_nome(escala, "Baixo")
        escala_id = escala.id
        funcao_id = baixo.id

        # bruno precisa estar no diretorio (Membro) com o MESMO e-mail da
        # conta, e escalado na funcao, pra "marcar o proprio status" ter
        # alguem de verdade pra marcar.
        from app.escala.models import Membro
        from app.extensions import db as _db
        membro_bruno = Membro(comunidade_id=comunidade.id, nome="Bruno", email="bruno@example.com")
        _db.session.add(membro_bruno)
        _db.session.commit()
        baixo.membro_id = membro_bruno.id
        _db.session.commit()

        _convidar_ministerio(logged_in_client, ministerio.id, "bruno@example.com", "membro")
        token = _convite_de("bruno@example.com", "ministerio", ministerio.id).token

    with sessao_isolada(app):
        outro_logged_in_client.post(f"/convite/{token}/aceitar", data={}, follow_redirects=True)

    with sessao_isolada(app):
        response = outro_logged_in_client.post(
            f"/escala/funcao/{funcao_id}/status", data={"status": "presente"}, follow_redirects=True
        )
        assert response.status_code == 200

    with sessao_isolada(app):
        from app.escala.models import Funcao
        assert db.session.get(Funcao, funcao_id).status == "presente"


def test_nao_membro_nao_ve_ministerio_nem_escala(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade = _criar_comunidade(logged_in_client, "Comunidade Ana")
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        ministerio_id = ministerio.id
        escala = _criar_escala(logged_in_client, ministerio_id, "Culto de Domingo")
        escala_id = escala.id

    with sessao_isolada(app):
        assert outro_logged_in_client.get(f"/ministerio/{ministerio_id}").status_code == 404
        assert outro_logged_in_client.get(f"/escala/{escala_id}").status_code == 404


# --- Super Admin ---------------------------------------------------------------

def test_bootstrap_super_admin_via_cli(logged_in_client, app, db):
    with app.app_context():
        runner = app.test_cli_runner()
        resultado = runner.invoke(args=["criar-super-admin", "ana@example.com"])
        assert "Super Admin" in resultado.output

        usuario = User.objects(email="ana@example.com").first()
        assert usuario.eh_super_admin is True


def test_cli_recusa_email_sem_conta(app, db):
    with app.app_context():
        runner = app.test_cli_runner()
        resultado = runner.invoke(args=["criar-super-admin", "naoexiste@example.com"])
        assert "Nenhuma conta encontrada" in resultado.output


def test_super_admin_acessa_qualquer_comunidade_sem_papel(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade = _criar_comunidade(logged_in_client, "Comunidade Ana")
        comunidade_id = comunidade.id

        bruno = User.objects(email="bruno@example.com").first()
        bruno.eh_super_admin = True
        bruno.save()

    with sessao_isolada(app):
        assert UsuarioComunidade.objects(
            usuario_id=User.objects(email="bruno@example.com").first().id, comunidade_id=comunidade_id
        ).first() is None
        assert outro_logged_in_client.get(f"/comunidade/{comunidade_id}").status_code == 200


# --- Link generico de convite (entrada direta como membro) ----------------------

def test_gerar_link_convite_cria_token(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        assert comunidade.token_convite_publico is None

        logged_in_client.post(f"/comunidade/{comunidade.id}/papeis/link/gerar", follow_redirects=True)

        atualizada = Comunidade.objects(id=comunidade.id).first()
        assert atualizada.token_convite_publico is not None
        # 8 bytes urlsafe (~11 chars) -- curto o suficiente pra ficar
        # apresentavel ao compartilhar, mas ainda com entropia alta (64
        # bits) pra nao virar adivinhavel por forca bruta.
        assert len(atualizada.token_convite_publico) <= 15


def test_gerar_link_de_novo_invalida_o_anterior(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        logged_in_client.post(f"/comunidade/{comunidade.id}/papeis/link/gerar", follow_redirects=True)
        token_antigo = Comunidade.objects(id=comunidade.id).first().token_convite_publico

        logged_in_client.post(f"/comunidade/{comunidade.id}/papeis/link/gerar", follow_redirects=True)
        token_novo = Comunidade.objects(id=comunidade.id).first().token_convite_publico

        assert token_antigo != token_novo
        assert logged_in_client.get(f"/comunidade/entrar/{token_antigo}", follow_redirects=True).status_code == 404


def test_entrar_via_link_get_nao_muda_nada_so_post_confirma(logged_in_client, app, db):
    """GET nunca muda estado (so mostra a tela de confirmacao) -- entrar de
    fato exige POST, ver comunidade.routes::entrar_via_link. Sem isso, um
    preview de link (WhatsApp/Telegram) ou um <img src="..."> em outro site
    poderia inscrever alguem so por ele visitar o link, sem intencao."""
    with sessao_isolada(app):
        comunidade = _criar_comunidade(logged_in_client, "Comunidade Ana")
        comunidade_id = comunidade.id
        logged_in_client.post(f"/comunidade/{comunidade_id}/papeis/link/gerar", follow_redirects=True)
        token = Comunidade.objects(id=comunidade_id).first().token_convite_publico

    with sessao_isolada(app):
        bruno_client = app.test_client()
        _registrar(bruno_client, "bruno", "bruno@example.com")
        bruno = User.objects(email="bruno@example.com").first()

        resposta_get = bruno_client.get(f"/comunidade/entrar/{token}")
        assert resposta_get.status_code == 200
        assert UsuarioComunidade.objects(usuario_id=bruno.id, comunidade_id=comunidade_id).first() is None

        resposta_post = bruno_client.post(f"/comunidade/entrar/{token}", follow_redirects=True)
        assert resposta_post.status_code == 200

        papel = UsuarioComunidade.objects(usuario_id=bruno.id, comunidade_id=comunidade_id).first()
        assert papel is not None
        assert papel.papel == "membro"


def test_entrar_via_link_ja_admin_nao_rebaixa_pra_membro(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        logged_in_client.post(f"/comunidade/{comunidade.id}/papeis/link/gerar", follow_redirects=True)
        token = Comunidade.objects(id=comunidade.id).first().token_convite_publico

        logged_in_client.get(f"/comunidade/entrar/{token}", follow_redirects=True)

        ana = User.objects(email="ana@example.com").first()
        papel = UsuarioComunidade.objects(usuario_id=ana.id, comunidade_id=comunidade.id).first()
        assert papel.papel == "admin"


def test_entrar_via_link_deslogado_pede_login_e_completa_depois(logged_in_client, app, db):
    """logged_in_client (Ana) cria o link; um segundo test_client, sem
    cookies dela, simula a visita anonima -- mesmo raciocinio de
    outro_logged_in_client, so que pra uma conta que nem existe ainda.
    sessao_isolada em volta do visitante pelo mesmo motivo de sempre:
    Flask-Login/SQLAlchemy cacheiam por app_context, e sem isolar aqui a
    conta de Ana (que fez a request anterior) vazaria pra essa request."""
    comunidade = _criar_comunidade(logged_in_client, "Comunidade Ana")
    comunidade_id = comunidade.id
    logged_in_client.post(f"/comunidade/{comunidade_id}/papeis/link/gerar", follow_redirects=True)
    token = Comunidade.objects(id=comunidade_id).first().token_convite_publico

    with sessao_isolada(app):
        visitante = app.test_client()
        resposta_anonima = visitante.get(f"/comunidade/entrar/{token}")
        assert resposta_anonima.status_code == 200
        assert "Entrar".encode() in resposta_anonima.data

        resposta_cadastro = visitante.post(
            "/auth/register",
            data={"username": "carla", "email": "carla@example.com", "password": "senha123", "confirm": "senha123"},
            follow_redirects=True,
        )
        assert resposta_cadastro.status_code == 200

        carla = User.objects(email="carla@example.com").first()
        # Cadastro sozinho nao completa a entrada -- cai na tela de
        # confirmacao (o redirect pos-login e sempre GET, que nunca muda
        # estado). Precisa do POST explicito pra realmente entrar.
        assert UsuarioComunidade.objects(usuario_id=carla.id, comunidade_id=comunidade_id).first() is None
        assert "Entrar em".encode() in resposta_cadastro.data

        resposta_confirmar = visitante.post(f"/comunidade/entrar/{token}", follow_redirects=True)
        assert resposta_confirmar.status_code == 200

        papel = UsuarioComunidade.objects(usuario_id=carla.id, comunidade_id=comunidade_id).first()
        assert papel is not None
        assert papel.papel == "membro"


def test_entrar_via_link_leva_pra_tela_que_mostra_a_comunidade(logged_in_client, app, db):
    """Bug relatado: quem entra via link (papel=membro) caia de volta no
    main.dashboard, que e so perfil/notificacoes -- sem nenhuma lista de
    comunidades nele, ficava parecendo que a entrada nao tinha funcionado.
    Um "membro" simples tambem nao acessa comunidade.detalhe (admin-only),
    entao o redirect precisa cair em comunidade.escalados (mesma rota que
    comunidade/lista.html usa pras comunidades em que so participa) -- ali
    o nome da comunidade aparece no cabecalho, confirmando visualmente."""
    with sessao_isolada(app):
        comunidade = _criar_comunidade(logged_in_client, "Comunidade Ana")
        comunidade_id = comunidade.id
        logged_in_client.post(f"/comunidade/{comunidade_id}/papeis/link/gerar", follow_redirects=True)
        token = Comunidade.objects(id=comunidade_id).first().token_convite_publico

    with sessao_isolada(app):
        bruno_client = app.test_client()
        _registrar(bruno_client, "bruno", "bruno@example.com")

        resposta = bruno_client.post(f"/comunidade/entrar/{token}", follow_redirects=False)
        assert resposta.status_code == 302
        assert resposta.headers["Location"] == f"/comunidade/{comunidade_id}/escalados"

        pagina = bruno_client.get(resposta.headers["Location"])
        assert "Comunidade Ana".encode() in pagina.data


def test_token_de_link_invalido_devolve_404(client):
    response = client.get("/comunidade/entrar/token-que-nao-existe")
    assert response.status_code == 404
