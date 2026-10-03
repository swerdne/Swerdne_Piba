"""Adicao direta x convite na tela de Papeis, conforme a preferencia de
privacidade de quem e adicionado (User.exige_aprovacao_grupos) -- ver
app/convites/adicao.py. O fluxo de convite em si (aceitar/recusar) e
coberto por tests/test_papeis.py."""
from app.auth.models import User
from app.comunidade.models import UsuarioComunidade
from app.ministerio.models import UsuarioMinisterio
from app.convites.models import Convite, STATUS_PENDENTE
from app.notificacoes import Notificacao
from tests.conftest import sessao_isolada
from tests.test_escala import _criar_comunidade, _criar_ministerio


def _adicionar(cliente, url_papeis, email, papel):
    return cliente.post(url_papeis, data={"email": email, "papel": papel}, follow_redirects=True)


def _bruno():
    return User.objects(email="bruno@example.com").first()


def test_conta_sem_preferencia_entra_direto_na_comunidade(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade = _criar_comunidade(logged_in_client, "Comunidade Ana")
        comunidade_id = comunidade.id
        resposta = _adicionar(logged_in_client, f"/comunidade/{comunidade_id}/papeis", "bruno@example.com", "membro")
        assert "foi adicionado(a)" in resposta.data.decode("utf-8")

    with sessao_isolada(app):
        bruno = _bruno()
        papel = UsuarioComunidade.objects(usuario_id=bruno.id, comunidade_id=comunidade_id).first()
        assert papel is not None and papel.papel == "membro"
        assert Convite.objects(escopo_tipo="comunidade", escopo_id=comunidade_id).count() == 0
        # Aviso no sino pra pessoa nao ser pega de surpresa.
        assert Notificacao.objects(usuario_id=bruno.id, tipo="adicionado_grupo").count() == 1
        # E ja tem acesso, sem aceitar nada.
        assert outro_logged_in_client.get(f"/comunidade/{comunidade_id}/escalados").status_code == 200


def test_conta_que_exige_aprovacao_recebe_convite(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        User.objects(email="bruno@example.com").update(set__exige_aprovacao_grupos=True)
        comunidade = _criar_comunidade(logged_in_client, "Comunidade Ana")
        comunidade_id = comunidade.id
        resposta = _adicionar(logged_in_client, f"/comunidade/{comunidade_id}/papeis", "bruno@example.com", "membro")
        assert "exige aprovacao" in resposta.data.decode("utf-8")

    with sessao_isolada(app):
        assert UsuarioComunidade.objects(usuario_id=_bruno().id, comunidade_id=comunidade_id).first() is None
        convite = Convite.objects(escopo_tipo="comunidade", escopo_id=comunidade_id).first()
        assert convite is not None and convite.status == STATUS_PENDENTE
        assert outro_logged_in_client.get(f"/comunidade/{comunidade_id}/escalados").status_code == 404


def test_email_sem_conta_continua_recebendo_convite(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        resposta = _adicionar(logged_in_client, f"/comunidade/{comunidade.id}/papeis", "ninguem@example.com", "membro")
        assert "ainda nao tem conta" in resposta.data.decode("utf-8")
        assert Convite.objects(email="ninguem@example.com", status=STATUS_PENDENTE).count() == 1


def test_adicao_direta_no_ministerio_tambem_da_membro_na_comunidade(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade = _criar_comunidade(logged_in_client, "Comunidade Ana")
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        comunidade_id, ministerio_id = comunidade.id, ministerio.id
        _adicionar(logged_in_client, f"/ministerio/{ministerio_id}/papeis", "bruno@example.com", "lider")

    with sessao_isolada(app):
        bruno = _bruno()
        assert UsuarioMinisterio.objects(usuario_id=bruno.id, ministerio_id=ministerio_id).first().papel == "lider"
        assert UsuarioComunidade.objects(usuario_id=bruno.id, comunidade_id=comunidade_id).first().papel == "membro"


def test_mudar_papel_de_quem_ja_faz_parte_vira_convite(logged_in_client, outro_logged_in_client, app, db):
    """Adicao direta nunca troca o papel de quem ja esta no grupo (poderia
    rebaixar alguem sem o aceite dele) -- a mudanca vai por convite."""
    with sessao_isolada(app):
        comunidade = _criar_comunidade(logged_in_client, "Comunidade Ana")
        comunidade_id = comunidade.id
        url = f"/comunidade/{comunidade_id}/papeis"
        _adicionar(logged_in_client, url, "bruno@example.com", "admin")
        resposta = _adicionar(logged_in_client, url, "bruno@example.com", "membro")
        assert "ja faz parte com outro papel" in resposta.data.decode("utf-8")

    with sessao_isolada(app):
        papel = UsuarioComunidade.objects(usuario_id=_bruno().id, comunidade_id=comunidade_id).first()
        assert papel.papel == "admin"  # continua o mesmo ate aceitar
        assert Convite.objects(escopo_id=comunidade_id, papel="membro", status=STATUS_PENDENTE).count() == 1


def test_adicao_direta_descarta_convite_pendente_antigo(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        User.objects(email="bruno@example.com").update(set__exige_aprovacao_grupos=True)
        comunidade = _criar_comunidade(logged_in_client, "Comunidade Ana")
        comunidade_id = comunidade.id
        url = f"/comunidade/{comunidade_id}/papeis"
        _adicionar(logged_in_client, url, "bruno@example.com", "membro")
        assert Convite.objects(escopo_id=comunidade_id, status=STATUS_PENDENTE).count() == 1

        User.objects(email="bruno@example.com").update(set__exige_aprovacao_grupos=False)
        _adicionar(logged_in_client, url, "bruno@example.com", "membro")
        assert Convite.objects(escopo_id=comunidade_id, status=STATUS_PENDENTE).count() == 0


def test_salvar_preferencia_de_privacidade(outro_logged_in_client, app, db):
    with sessao_isolada(app):
        outro_logged_in_client.post("/perfil/privacidade", data={"exige_aprovacao_grupos": "y"})
        assert _bruno().exige_aprovacao_grupos is True
        # Checkbox desmarcado nao vai no POST -- desliga.
        outro_logged_in_client.post("/perfil/privacidade", data={})
        assert _bruno().exige_aprovacao_grupos is False


def test_ligar_preferencia_nao_remove_de_grupos_atuais(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade = _criar_comunidade(logged_in_client, "Comunidade Ana")
        comunidade_id = comunidade.id
        _adicionar(logged_in_client, f"/comunidade/{comunidade_id}/papeis", "bruno@example.com", "membro")

    with sessao_isolada(app):
        outro_logged_in_client.post("/perfil/privacidade", data={"exige_aprovacao_grupos": "y"})
        assert UsuarioComunidade.objects(usuario_id=_bruno().id, comunidade_id=comunidade_id).first() is not None
        assert outro_logged_in_client.get(f"/comunidade/{comunidade_id}/escalados").status_code == 200


def test_verificar_adicao_mostra_o_que_vai_acontecer(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade = _criar_comunidade(logged_in_client, "Comunidade Ana")
        base = f"/convite/verificar-adicao?escopo_tipo=comunidade&escopo_id={comunidade.id}&papel=membro"

        assert logged_in_client.get(base + "&email=bruno@example.com").get_json()["modo"] == "adicionar"
        sem_conta = logged_in_client.get(base + "&email=ninguem@example.com").get_json()
        assert sem_conta == {"modo": "convite", "motivo": "sem_conta"}

        User.objects(email="bruno@example.com").update(set__exige_aprovacao_grupos=True)
        exige = logged_in_client.get(base + "&email=bruno@example.com").get_json()
        assert exige == {"modo": "convite", "motivo": "exige_aprovacao"}


def test_verificar_adicao_da_404_pra_quem_nao_gerencia(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade = _criar_comunidade(logged_in_client, "Comunidade Ana")
        comunidade_id = comunidade.id

    with sessao_isolada(app):
        resposta = outro_logged_in_client.get(
            f"/convite/verificar-adicao?escopo_tipo=comunidade&escopo_id={comunidade_id}"
            "&papel=membro&email=ana@example.com"
        )
        assert resposta.status_code == 404
