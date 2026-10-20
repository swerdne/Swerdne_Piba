"""Aviso automatico pra quem e escalado e perfil de cada pessoa do diretorio."""
from datetime import date, timedelta

import pytest

from app.auth.models import User
from app.escala.models import Escala, Funcao, Membro
from app.ministerio.models import UsuarioMinisterio
from app.notificacoes import Notificacao
from tests.conftest import sessao_isolada
from tests.test_escala import _criar_comunidade, _criar_ministerio


@pytest.fixture
def whatsapps(monkeypatch):
    """Troca o envio real do aviso (template) por uma lista."""
    lista = []
    monkeypatch.setattr(
        "app.escala.routes.enviar_whatsapp_template",
        lambda destinatario, nome_template, parametros: lista.append((destinatario, nome_template, parametros)),
    )
    return lista


def _cenario(cliente, dias=3, **campos_escala):
    comunidade = _criar_comunidade(cliente, "Igreja")
    louvor = _criar_ministerio(cliente, comunidade.id, nome="Louvor")
    escala = Escala(ministerio_id=louvor.id, nome="Culto", departamento="Louvor",
                    data=date.today() + timedelta(days=dias), **campos_escala).save()
    funcao = Funcao(escala_id=escala.id, nome="Vocal", ordem=0).save()
    membro = Membro(comunidade_id=comunidade.id, nome="Carla", telefone="(28) 99935-9709",
                    email="ana@example.com").save()
    return comunidade, louvor, escala, funcao, membro


# --- Aviso ao escalar ---------------------------------------------------------------

def test_escalar_alguem_avisa_so_essa_pessoa(logged_in_client, whatsapps, app, db):
    with app.app_context():
        _, _, escala, funcao, membro = _cenario(logged_in_client)
        outra = Membro(comunidade_id=membro.comunidade_id, nome="Davi", telefone="11 91234-5678").save()
        Funcao(escala_id=escala.id, nome="Bateria", ordem=1, membro_id=outra.id, status="nao_notificado").save()

        resposta = logged_in_client.post(f"/escala/funcao/{funcao.id}/adicionar",
                                         data={"membro_id": membro.id}, follow_redirects=True)

        assert [w[1] for w in whatsapps] == ["pibachurch_escalado"]  # so a Carla, nao o Davi
        assert whatsapps[0][0] == "(28) 99935-9709"
        assert whatsapps[0][2][:3] == ["Carla", "Vocal", "Culto"]
        assert Notificacao.objects(escala_id=escala.id, tipo="escalado").count() == 1  # sino da conta vinculada
        assert Funcao.objects(id=funcao.id).first().notificado_em is not None
        assert "Aviso pra pessoa" in resposta.data.decode()


def test_atribuicao_em_lote_responde_json_curto_sem_montar_a_tela(logged_in_client, whatsapps, app, db):
    """O lote da tela da escala manda X-Requested-With: fetch -- a resposta e
    um JSON curto (antes seguia o redirect e montava a escala inteira a cada
    pessoa). O aviso sai igual e os flashes ficam pro recarregar do fim."""
    with app.app_context():
        _, _, escala, funcao, membro = _cenario(logged_in_client)
        resposta = logged_in_client.post(f"/escala/funcao/{funcao.id}/adicionar", data={"membro_id": membro.id},
                                         headers={"X-Requested-With": "fetch"})
        assert resposta.status_code == 200 and resposta.get_json() == {"ok": True}
        assert Funcao.objects(id=funcao.id).first().membro_id == membro.id
        assert [w[1] for w in whatsapps] == ["pibachurch_escalado"]
        assert "Aviso pra pessoa" in logged_in_client.get(f"/escala/{escala.id}").data.decode()

        invalido = logged_in_client.post(f"/escala/funcao/{funcao.id}/adicionar", data={"membro_id": 999999},
                                         headers={"X-Requested-With": "fetch"})
        assert invalido.status_code == 400 and invalido.get_json()["ok"] is False


def test_aviso_que_nao_sai_vira_alerta_no_sino_de_quem_escalou(logged_in_client, app, db, monkeypatch):
    """O aviso roda em segundo plano (a tela nao espera WhatsApp/e-mail/SMS);
    se nenhum canal funcionar, quem escalou fica sabendo pelo sino."""
    from app.whatsapp import WhatsappNaoEnviadoError

    def falha(*args, **kwargs):
        raise WhatsappNaoEnviadoError("recusado")
    monkeypatch.setattr("app.escala.routes.enviar_whatsapp_template", falha)
    with app.app_context():
        _, _, escala, funcao, _ = _cenario(logged_in_client)
        sem_conta = Membro(comunidade_id=escala.ministerio.comunidade_id, nome="Davi", telefone="11 91234-5678").save()
        logged_in_client.post(f"/escala/funcao/{funcao.id}/adicionar", data={"membro_id": sem_conta.id})
        alerta = Notificacao.objects(escala_id=escala.id, tipo="nao_notificado").first()
        assert alerta is not None and "Davi" in alerta.mensagem and "nao saiu" in alerta.mensagem


def test_escala_passada_ou_cancelada_nao_avisa(logged_in_client, whatsapps, app, db):
    with app.app_context():
        _, louvor, _, funcao, membro = _cenario(logged_in_client, dias=-2)
        logged_in_client.post(f"/escala/funcao/{funcao.id}/adicionar", data={"membro_id": membro.id})
        cancelada = Escala(ministerio_id=louvor.id, nome="Cancelada", departamento="Louvor",
                           data=date.today() + timedelta(days=5), cancelada=True).save()
        f2 = Funcao(escala_id=cancelada.id, nome="Vocal", ordem=0).save()
        logged_in_client.post(f"/escala/funcao/{f2.id}/adicionar", data={"membro_id": membro.id})
        assert whatsapps == []


def test_aprovar_troca_avisa_quem_assume(logged_in_client, whatsapps, app, db):
    with app.app_context():
        _, _, _, funcao, membro = _cenario(logged_in_client)
        substituto = Membro(comunidade_id=membro.comunidade_id, nome="Davi", telefone="11 91234-5678").save()
        Funcao.objects(id=funcao.id).update(set__membro_id=membro.id, set__status="troca_solicitada")
        logged_in_client.post(f"/escala/funcao/{funcao.id}/troca/aprovar", data={"membro_id": substituto.id})
        assert [w[2][0] for w in whatsapps] == ["Davi"]


# --- Perfil ----------------------------------------------------------------------------

def test_perfil_mostra_contato_e_proximas_escalas_e_admin_edita(logged_in_client, app, db):
    with app.app_context():
        comunidade, _, escala, funcao, membro = _cenario(logged_in_client)
        Funcao.objects(id=funcao.id).update(set__membro_id=membro.id, set__status="confirmado")
        url = f"/comunidade/{comunidade.id}/membros/{membro.id}"

        html = logged_in_client.get(url).data.decode()
        assert "Carla" in html and "https://wa.me/5528999359709" in html
        assert "Culto" in html and "Confirmado" in html and "Tem conta no site" in html
        assert "Editar dados" in html
        assert url in logged_in_client.get(f"/comunidade/{comunidade.id}/membros").data.decode()
        assert url in logged_in_client.get(f"/escala/{escala.id}").data.decode()

        logged_in_client.post(url, data={"nome": "Carla Souza", "telefone": "28 3333-4444", "email": ""})
        membro = Membro.objects(id=membro.id).first()
        assert (membro.nome, membro.telefone, membro.email) == ("Carla Souza", "(28) 3333-4444", None)  # padronizado


def test_lider_ve_perfil_mas_nao_edita_e_estranho_nao_ve(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade, louvor, _, _, membro = _cenario(logged_in_client)
        cid, mid, lid = comunidade.id, membro.id, louvor.id
    url = f"/comunidade/{cid}/membros/{mid}"
    with sessao_isolada(app):
        assert outro_logged_in_client.get(url).status_code == 404  # bruno nao tem papel nenhum
        bruno = User.objects(email="bruno@example.com").first()
        UsuarioMinisterio(usuario_id=bruno.id, ministerio_id=lid, papel="lider").save()
    with sessao_isolada(app):
        html = outro_logged_in_client.get(url).data.decode()
        assert "Carla" in html and "Editar dados" not in html
        assert outro_logged_in_client.post(url, data={"nome": "Hack"}).status_code == 404
        assert Membro.objects(id=mid).first().nome == "Carla"


PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def test_admin_envia_troca_e_remove_foto_e_ela_aparece_nas_telas(logged_in_client, app, db):
    import io

    from app.imagens import ImagemArmazenada

    with app.app_context():
        comunidade, _, escala, funcao, membro = _cenario(logged_in_client)
        Funcao.objects(id=funcao.id).update(set__membro_id=membro.id)
        url_foto = f"/comunidade/{comunidade.id}/membros/{membro.id}/foto"

        logged_in_client.post(url_foto, data={"foto": (io.BytesIO(PNG), "carla.png")},
                              content_type="multipart/form-data")
        foto = Membro.objects(id=membro.id).first().foto
        assert foto and foto.startswith("/imagem/")
        assert logged_in_client.get(foto).status_code == 200
        for tela in (f"/comunidade/{comunidade.id}/membros/{membro.id}", f"/comunidade/{comunidade.id}/membros",
                     f"/escala/{escala.id}"):
            assert foto in logged_in_client.get(tela).data.decode(), tela

        # Trocar apaga a antiga; arquivo que nao e imagem e recusado.
        logged_in_client.post(url_foto, data={"foto": (io.BytesIO(PNG), "nova.png")}, content_type="multipart/form-data")
        nova = Membro.objects(id=membro.id).first().foto
        assert nova != foto and ImagemArmazenada.objects(id=foto.rsplit("/", 1)[-1]).count() == 0
        logged_in_client.post(url_foto, data={"foto": (io.BytesIO(b"oi"), "virus.exe")}, content_type="multipart/form-data")
        assert Membro.objects(id=membro.id).first().foto == nova

        logged_in_client.post(url_foto, data={"remover": "1"})
        assert Membro.objects(id=membro.id).first().foto is None
        assert ImagemArmazenada.objects.count() == 0


def test_sem_foto_propria_usa_a_da_conta(logged_in_client, app, db):
    with app.app_context():
        comunidade, _, _, _, membro = _cenario(logged_in_client)  # e-mail da Carla = conta logada (ana)
        User.objects(email="ana@example.com").update(set__foto_perfil="/imagem/fotodaconta")
        html = logged_in_client.get(f"/comunidade/{comunidade.id}/membros").data.decode()
        assert "/imagem/fotodaconta" in html


def test_so_admin_muda_foto(logged_in_client, outro_logged_in_client, app, db):
    import io

    with sessao_isolada(app):
        comunidade, louvor, _, _, membro = _cenario(logged_in_client)
        cid, mid = comunidade.id, membro.id
        bruno = User.objects(email="bruno@example.com").first()
        UsuarioMinisterio(usuario_id=bruno.id, ministerio_id=louvor.id, papel="lider").save()
    with sessao_isolada(app):
        assert "Enviar foto" not in outro_logged_in_client.get(f"/comunidade/{cid}/membros/{mid}").data.decode()
        resposta = outro_logged_in_client.post(f"/comunidade/{cid}/membros/{mid}/foto",
                                               data={"foto": (io.BytesIO(PNG), "x.png")},
                                               content_type="multipart/form-data")
        assert resposta.status_code == 404
        assert Membro.objects(id=mid).first().foto is None


def test_perfil_de_membro_de_outra_comunidade_e_404(logged_in_client, app, db):
    with app.app_context():
        comunidade, _, _, _, _ = _cenario(logged_in_client)
        alheio = Membro(comunidade_id=comunidade.id + 999, nome="X").save()
        assert logged_in_client.get(f"/comunidade/{comunidade.id}/membros/{alheio.id}").status_code == 404
