"""Telefone dos integrantes: formato, cadastro no Perfil e PRIVACIDADE (quem
pode ver/editar, conferido no servidor). E o formulario de Ciclos."""
from datetime import date, timedelta

import pytest

from app.auth.models import User
from app.comunidade.models import UsuarioComunidade
from app.escala.models import Escala, Funcao, Membro
from app.ministerio.models import UsuarioMinisterio
from app.telefones import formatar_telefone
from tests.conftest import sessao_isolada
from tests.test_escala import _criar_comunidade, _criar_ministerio

NUMERO = "(28) 99935-9709"


# --- Formato -----------------------------------------------------------------------

@pytest.mark.parametrize("entrada,esperado", [
    ("28999359709", NUMERO), ("+55 28 99935-9709", NUMERO), ("(28) 99935 9709", NUMERO),
    ("028 99935-9709", NUMERO), ("11 3333-4444", "(11) 3333-4444"), ("", None), ("   ", None),
    ("+55 (28) 99935-9709", NUMERO),  # como a mascara mostra quem digita com +55
])
def test_formatar_telefone(entrada, esperado):
    assert formatar_telefone(entrada) == esperado


@pytest.mark.parametrize("entrada", ["99935-9709", "123", "(28) 89935-9709", "(00) 99935-9709", "(11) 0333-4444",
                                     "+1 555 177 4928"])
def test_formatar_telefone_invalido(entrada):
    with pytest.raises(ValueError):
        formatar_telefone(entrada)


# --- Cadastro ----------------------------------------------------------------------------

def test_diretorio_valida_e_padroniza_o_telefone(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client, "Igreja")
        url = f"/comunidade/{comunidade.id}/membros"
        logged_in_client.post(url, data={"nome": "Errado", "telefone": "123"})
        assert Membro.objects(nome="Errado").count() == 0
        logged_in_client.post(url, data={"nome": "Carla", "telefone": "+55 28 99935-9709"})
        logged_in_client.post(url, data={"nome": "Sem telefone", "telefone": ""})
        assert Membro.objects(nome="Carla").first().telefone == NUMERO
        assert Membro.objects(nome="Sem telefone").first().telefone is None
        assert "data-mascara-telefone" in logged_in_client.get(url).data.decode()


def test_usuario_cadastra_edita_e_apaga_o_proprio_telefone_no_perfil(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client, "Igreja")
        membro = Membro(comunidade_id=comunidade.id, nome="Ana", email="ANA@example.com").save()

        assert "Telefone (WhatsApp)" in logged_in_client.get("/dashboard").data.decode()
        logged_in_client.post("/perfil/telefone", data={"telefone": "28999359709"})
        assert User.objects(email="ana@example.com").first().telefone == NUMERO
        assert Membro.objects(id=membro.id).first().telefone == NUMERO  # vale pro diretorio (avisos)
        assert NUMERO in logged_in_client.get("/dashboard").data.decode()

        logged_in_client.post("/perfil/telefone", data={"telefone": "abc"})
        assert User.objects(email="ana@example.com").first().telefone == NUMERO  # invalido nao troca

        logged_in_client.post("/perfil/telefone", data={"telefone": ""})
        assert User.objects(email="ana@example.com").first().telefone is None
        assert Membro.objects(id=membro.id).first().telefone is None


# --- Privacidade -----------------------------------------------------------------------------

def _cenario(admin_cliente):
    """Ana (admin) com Louvor e Kids; Carla (sem conta) escalada no Louvor;
    Bruno (conta) no diretorio, com telefone."""
    comunidade = _criar_comunidade(admin_cliente, "Igreja")
    louvor = _criar_ministerio(admin_cliente, comunidade.id, nome="Louvor")
    kids = _criar_ministerio(admin_cliente, comunidade.id, nome="Kids")
    carla = Membro(comunidade_id=comunidade.id, nome="Carla", telefone=NUMERO).save()
    escala = Escala(ministerio_id=louvor.id, nome="Culto", departamento="Louvor",
                    data=date.today() + timedelta(days=3)).save()
    Funcao(escala_id=escala.id, nome="Vocal", membro_id=carla.id).save()
    ana_membro = Membro(comunidade_id=comunidade.id, nome="Ana", telefone="(11) 98765-4321",
                        email="ana@example.com").save()
    return comunidade, louvor, kids, carla, ana_membro


def _bruno():
    return User.objects(email="bruno@example.com").first()


def test_admin_ve_lider_do_ministerio_ve_lider_de_outro_nao(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade, louvor, kids, carla, _ = _cenario(logged_in_client)
        cid, carla_id, louvor_id, kids_id = comunidade.id, carla.id, louvor.id, kids.id
        assert NUMERO in logged_in_client.get(f"/comunidade/{cid}/membros/{carla_id}").data.decode()
    url = f"/comunidade/{cid}/membros/{carla_id}"

    with sessao_isolada(app):
        UsuarioMinisterio(usuario_id=_bruno().id, ministerio_id=kids_id, papel="lider").save()
    with sessao_isolada(app):
        html = outro_logged_in_client.get(url).data.decode()  # lider do Kids: Carla so serve no Louvor
        assert NUMERO not in html and "28999359709" not in html and "Telefone privado" in html
        assert outro_logged_in_client.post(url, data={"so_telefone": "1", "telefone": "11 91111-1111"}).status_code == 404

    with sessao_isolada(app):
        UsuarioMinisterio(usuario_id=_bruno().id, ministerio_id=louvor_id, papel="lider").save()
    with sessao_isolada(app):
        html = outro_logged_in_client.get(url).data.decode()
        assert NUMERO in html and "Salvar telefone" in html and "Editar dados" not in html
        outro_logged_in_client.post(url, data={"so_telefone": "1", "telefone": "11 91111-1111"})
        assert Membro.objects(id=carla_id).first().telefone == "(11) 91111-1111"
        # Nome/e-mail continuam so do admin.
        assert outro_logged_in_client.post(url, data={"nome": "Hack", "telefone": "", "email": ""}).status_code == 404


def test_pessoa_pode_esconder_o_telefone_dos_lideres_mas_nao_do_admin(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade, louvor, _, _, _ = _cenario(logged_in_client)
        cid = comunidade.id
        bruno_membro = Membro(comunidade_id=cid, nome="Bruno", email="bruno@example.com", telefone=NUMERO).save()
        escala = Escala.objects(nome="Culto").first()
        Funcao(escala_id=escala.id, nome="Bateria", membro_id=bruno_membro.id).save()
        bid = bruno_membro.id
    url = f"/comunidade/{cid}/membros/{bid}"

    with sessao_isolada(app):
        # Bruno desliga "lideres podem ver meu telefone" (e continua recebendo avisos).
        outro_logged_in_client.post("/perfil/privacidade", data={"exige_aprovacao_grupos": ""})
        assert _bruno().telefone_visivel_lider is False

    with sessao_isolada(app):
        assert NUMERO in logged_in_client.get(url).data.decode()  # ana e admin: ve igual

    # Um lider do Louvor que nao e admin: cria a conta Davi e faz login.
    with sessao_isolada(app):
        from tests.conftest import _registrar

        cliente_davi = app.test_client()
        _registrar(cliente_davi, "davi", "davi@example.com")
        UsuarioMinisterio(usuario_id=User.objects(email="davi@example.com").first().id,
                          ministerio_id=louvor.id, papel="lider").save()
    with sessao_isolada(app):
        html = cliente_davi.get(url).data.decode()
        assert NUMERO not in html and "Telefone privado" in html
        assert cliente_davi.post(url, data={"so_telefone": "1", "telefone": "11 91111-1111"}).status_code == 404


def test_membro_comum_nao_ve_telefone_nem_na_tela_de_lideres(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade, _, _, carla, _ = _cenario(logged_in_client)
        cid, carla_id = comunidade.id, carla.id
        UsuarioComunidade(usuario_id=_bruno().id, comunidade_id=cid, papel="membro").save()
        assert "(11) 98765-4321" in logged_in_client.get(f"/comunidade/{cid}/lideres").data.decode()
    with sessao_isolada(app):
        html = outro_logged_in_client.get(f"/comunidade/{cid}/lideres").data.decode()
        assert "ana@example.com" in html and "(11) 98765-4321" not in html
        assert outro_logged_in_client.get(f"/comunidade/{cid}/membros/{carla_id}").status_code == 404
        assert outro_logged_in_client.get(f"/comunidade/{cid}/membros").status_code == 404


def test_outra_comunidade_nao_ve(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade, _, _, carla, _ = _cenario(logged_in_client)
        cid, carla_id = comunidade.id, carla.id
    with sessao_isolada(app):
        _criar_comunidade(outro_logged_in_client, "Outra igreja")  # bruno e admin de OUTRA comunidade
        assert outro_logged_in_client.get(f"/comunidade/{cid}/membros/{carla_id}").status_code == 404
        assert outro_logged_in_client.get(f"/comunidade/{cid}/lideres").status_code == 404


# --- Tela de Ciclos ------------------------------------------------------------------------------

def test_formulario_de_ciclo_tem_rotulos_e_fica_recolhido(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client, "Igreja")
        membro = Membro(comunidade_id=comunidade.id, nome="Carla").save()
        html = logged_in_client.get(f"/comunidade/{comunidade.id}/membros/{membro.id}/disponibilidade").data.decode()
        for rotulo in ("Nome do ciclo", "Data de início do ciclo", "Nome do segmento", "Dias", "Segmentos do ciclo"):
            assert rotulo in html, rotulo
        assert "<details" in html and "<details class=\"group" in html and " open" not in html.split("<details", 1)[1].split(">", 1)[0]
        assert "w-full sm:w-auto" in html  # botao de salvar largo no celular
