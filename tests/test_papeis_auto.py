"""Quem e escalado entra sozinho nos Papeis do ministerio como membro, e a
tela de Papeis tem a caixa "Lider: sim/nao" (ver app/ministerio/papeis_auto.py)."""
from datetime import date, timedelta

from app.auth.models import User
from app.comunidade.models import UsuarioComunidade
from app.escala.models import Escala, Funcao, Membro
from app.ministerio.models import Ministerio, UsuarioMinisterio
from tests.conftest import sessao_isolada
from tests.test_escala import _criar_comunidade, _criar_ministerio


def _conta(email, **campos):
    usuario = User(username=email.split("@")[0], email=email, **campos)
    usuario.set_password("senha12345")
    return usuario.save()


def _cenario(cliente):
    comunidade = _criar_comunidade(cliente, "Igreja")
    lights = _criar_ministerio(cliente, comunidade.id, nome="Lights")
    escala = Escala(ministerio_id=lights.id, nome="Culto", departamento="Louvor",
                    data=date.today() + timedelta(days=3)).save()
    funcao = Funcao(escala_id=escala.id, nome="Luz", ordem=0).save()
    return comunidade, lights, escala, funcao


def _papel(usuario, ministerio):
    linha = UsuarioMinisterio.objects(usuario_id=usuario.id, ministerio_id=ministerio.id).first()
    return linha.papel if linha else None


def test_escalar_quem_tem_conta_entra_como_membro(logged_in_client, app, db):
    with app.app_context():
        comunidade, lights, escala, funcao = _cenario(logged_in_client)
        carla = _conta("carla@example.com")
        membro = Membro(comunidade_id=comunidade.id, nome="Carla", email="Carla@Example.com").save()

        resposta = logged_in_client.post(f"/escala/funcao/{funcao.id}/adicionar",
                                         data={"membro_id": membro.id}, follow_redirects=True)

        assert _papel(carla, lights) == "membro"
        assert UsuarioComunidade.objects(usuario_id=carla.id, comunidade_id=comunidade.id).first().papel == "membro"
        assert "entrou nos Papeis do ministerio como membro" in resposta.data.decode()

        # escalar de novo nao duplica
        f2 = Funcao(escala_id=escala.id, nome="Som", ordem=1).save()
        logged_in_client.post(f"/escala/funcao/{f2.id}/adicionar", data={"membro_id": membro.id})
        assert UsuarioMinisterio.objects(usuario_id=carla.id, ministerio_id=lights.id).count() == 1


def test_nao_inclui_sem_conta_nem_rebaixa_lider_nem_quem_exige_aprovacao(logged_in_client, app, db):
    with app.app_context():
        comunidade, lights, escala, funcao = _cenario(logged_in_client)
        sem_conta = Membro(comunidade_id=comunidade.id, nome="Davi", email="davi@example.com").save()
        logged_in_client.post(f"/escala/funcao/{funcao.id}/adicionar", data={"membro_id": sem_conta.id})
        assert UsuarioMinisterio.objects(ministerio_id=lights.id).count() == 0

        lider = _conta("lider@example.com")
        UsuarioMinisterio(usuario_id=lider.id, ministerio_id=lights.id, papel="lider").save()
        m_lider = Membro(comunidade_id=comunidade.id, nome="Lider", email="lider@example.com").save()
        logged_in_client.post(f"/escala/funcao/{funcao.id}/adicionar", data={"membro_id": m_lider.id})
        assert _papel(lider, lights) == "lider"

        reservada = _conta("reservada@example.com", exige_aprovacao_grupos=True)
        m_res = Membro(comunidade_id=comunidade.id, nome="Reservada", email="reservada@example.com").save()
        logged_in_client.post(f"/escala/funcao/{funcao.id}/adicionar", data={"membro_id": m_res.id})
        assert _papel(reservada, lights) is None

        # admin da comunidade (a propria conta logada) nao vira "membro"
        ana = User.objects(username="ana").first()
        m_ana = Membro(comunidade_id=comunidade.id, nome="Ana", email=ana.email).save()
        logged_in_client.post(f"/escala/funcao/{funcao.id}/adicionar", data={"membro_id": m_ana.id})
        assert _papel(ana, lights) is None


def test_quem_ja_estava_escalado_entra_uma_vez_ao_abrir_papeis(logged_in_client, app, db):
    with app.app_context():
        comunidade, lights, escala, funcao = _cenario(logged_in_client)
        joao = _conta("joao@example.com")
        m = Membro(comunidade_id=comunidade.id, nome="Joao", email="joao@example.com").save()
        Funcao.objects(id=funcao.id).update(set__membro_id=m.id)  # escalado "antes" da inclusao automatica

        html = logged_in_client.get(f"/ministerio/{lights.id}/papeis").data.decode()
        assert _papel(joao, lights) == "membro" and "joao@example.com" in html
        assert Ministerio.objects(id=lights.id).first().papeis_escalados_sincronizados

        # removido a mao nao volta sozinho ao abrir de novo
        linha = UsuarioMinisterio.objects(usuario_id=joao.id, ministerio_id=lights.id).first()
        logged_in_client.post(f"/ministerio/{lights.id}/papeis/{linha.id}/remover")
        logged_in_client.get(f"/ministerio/{lights.id}/papeis")
        assert _papel(joao, lights) is None


def test_caixa_lider_na_lista_e_ao_adicionar(logged_in_client, app, db):
    with app.app_context():
        _, lights, _, _ = _cenario(logged_in_client)
        maria = _conta("maria@example.com")
        UsuarioMinisterio(usuario_id=maria.id, ministerio_id=lights.id, papel="membro").save()
        linha = UsuarioMinisterio.objects(usuario_id=maria.id, ministerio_id=lights.id).first()

        html = logged_in_client.get(f"/ministerio/{lights.id}/papeis").data.decode()
        assert 'role="switch"' in html and 'name="lider"' in html and 'select name="papel"' not in html

        logged_in_client.post(f"/ministerio/{lights.id}/papeis/{linha.id}/lider", data={"lider": "sim"})
        assert _papel(maria, lights) == "lider"
        logged_in_client.post(f"/ministerio/{lights.id}/papeis/{linha.id}/lider", data={"lider": "nao"})
        assert _papel(maria, lights) == "membro"

        # adicionar por e-mail continua: sem a caixa = membro, com a caixa = lider
        pedro = _conta("pedro@example.com")
        lucas = _conta("lucas@example.com")
        logged_in_client.post(f"/ministerio/{lights.id}/papeis", data={"email": "pedro@example.com"})
        logged_in_client.post(f"/ministerio/{lights.id}/papeis", data={"email": "lucas@example.com", "lider": "sim"})
        assert (_papel(pedro, lights), _papel(lucas, lights)) == ("membro", "lider")


def test_lider_comum_nao_promove_ninguem(logged_in_client, outro_logged_in_client, app, db):
    with app.app_context():
        _, lights, _, _ = _cenario(logged_in_client)
        bruno = User.objects(username="bruno").first()
        UsuarioMinisterio(usuario_id=bruno.id, ministerio_id=lights.id, papel="lider").save()
        maria = _conta("maria@example.com")
        UsuarioMinisterio(usuario_id=maria.id, ministerio_id=lights.id, papel="membro").save()
        linha = UsuarioMinisterio.objects(usuario_id=maria.id, ministerio_id=lights.id).first()

        with sessao_isolada(app):
            html = outro_logged_in_client.get(f"/ministerio/{lights.id}/papeis").data.decode()
            assert 'role="switch"' not in html and 'name="lider"' not in html
            outro_logged_in_client.post(f"/ministerio/{lights.id}/papeis/{linha.id}/lider", data={"lider": "sim"})
        assert _papel(maria, lights) == "membro"


def test_entrar_na_fila_do_rodizio_inclui_nos_papeis(logged_in_client, app, db):
    from tests.test_plantao import _criar_turno_teste

    with app.app_context():
        comunidade, lights, _, _ = _cenario(logged_in_client)
        rita = _conta("rita@example.com")
        m = Membro(comunidade_id=comunidade.id, nome="Rita", email="rita@example.com").save()
        turno = _criar_turno_teste(lights.id, data_inicio=date.today())
        logged_in_client.post(f"/plantao/{turno.id}/fila/adicionar", data={"membro_id": m.id, "equipe_turno_id": "0"})
        assert _papel(rita, lights) == "membro"
