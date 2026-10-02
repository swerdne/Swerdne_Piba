"""Ensaios de uma Escala: adicionar, cancelar (so um dia, sem cancelar a
escala), reabrir, remover, avisos pra equipe e exibicao (Inicio, lista do
ministerio, calendario)."""
from datetime import date, timedelta

from app.escala.models import Ensaio, Escala
from app.notificacoes import Notificacao
from app.auth.models import User
from tests.conftest import sessao_isolada
from tests.test_escala import (
    _criar_comunidade,
    _criar_ministerio,
    _criar_escala,
    _criar_membro,
    _escalar,
    _funcao_por_nome,
)

DAQUI_3_DIAS = date.today() + timedelta(days=3)
DAQUI_5_DIAS = date.today() + timedelta(days=5)


def _montar(cliente, email_escalado="bruno@example.com"):
    comunidade = _criar_comunidade(cliente)
    ministerio = _criar_ministerio(cliente, comunidade.id)
    escala = _criar_escala(cliente, ministerio.id, "Culto de Domingo")
    membro = _criar_membro(cliente, comunidade.id, "Bruno", email=email_escalado)
    _escalar(cliente, _funcao_por_nome(escala, "Baixo").id, membro.id)
    return comunidade, ministerio, escala


def _adicionar_ensaio(cliente, escala_id, data=DAQUI_3_DIAS, horario="19:00", horario_fim="21:00", local="Templo"):
    return cliente.post(
        f"/escala/{escala_id}/ensaios",
        data={"ensaio-data": data.isoformat(), "ensaio-horario": horario,
              "ensaio-horario_fim": horario_fim, "ensaio-local": local},
        follow_redirects=True,
    )


def test_adicionar_ensaio_aparece_na_escala(logged_in_client, app, db):
    with app.app_context():
        _, _, escala = _montar(logged_in_client)
        resposta = _adicionar_ensaio(logged_in_client, escala.id)
        assert resposta.status_code == 200
        ensaio = Ensaio.objects(escala_id=escala.id).first()
        assert ensaio.data == DAQUI_3_DIAS and ensaio.local == "Templo"

        html = logged_in_client.get(f"/escala/{escala.id}").data.decode("utf-8")
        assert 'id="ensaios"' in html
        assert DAQUI_3_DIAS.strftime("%d/%m/%Y") in html
        assert "19:00 as 21:00" in html


def test_ensaio_com_fim_antes_do_inicio_e_recusado(logged_in_client, app, db):
    with app.app_context():
        _, _, escala = _montar(logged_in_client)
        resposta = _adicionar_ensaio(logged_in_client, escala.id, horario="21:00", horario_fim="19:00")
        assert "precisa ser depois do inicio" in resposta.data.decode("utf-8")
        assert Ensaio.objects(escala_id=escala.id).count() == 0


def test_cancelar_um_ensaio_avisa_a_equipe_e_nao_cancela_a_escala(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        _, _, escala = _montar(logged_in_client)
        _adicionar_ensaio(logged_in_client, escala.id)
        ensaio = Ensaio.objects(escala_id=escala.id).first()

        resposta = logged_in_client.post(f"/escala/ensaio/{ensaio.id}/cancelar", follow_redirects=True)
        assert resposta.status_code == 200

        ensaio = Ensaio.objects(id=ensaio.id).first()
        assert ensaio.cancelado is True
        assert Escala.objects(id=escala.id).first().cancelada is False

        bruno = User.objects(email="bruno@example.com").first()
        aviso = Notificacao.objects(usuario_id=bruno.id, tipo="ensaio_cancelado").first()
        assert aviso is not None and "Culto de Domingo" in aviso.titulo


def test_cancelar_ensaio_escolhido_na_secao_de_cancelar(logged_in_client, app, db):
    with app.app_context():
        _, _, escala = _montar(logged_in_client)
        _adicionar_ensaio(logged_in_client, escala.id, data=DAQUI_3_DIAS)
        _adicionar_ensaio(logged_in_client, escala.id, data=DAQUI_5_DIAS)
        segundo = Ensaio.objects(escala_id=escala.id, data=DAQUI_5_DIAS).first()

        logged_in_client.post(f"/escala/{escala.id}/ensaios/cancelar", data={"ensaio_id": segundo.id})

        assert Ensaio.objects(id=segundo.id).first().cancelado is True
        assert Ensaio.objects(escala_id=escala.id, data=DAQUI_3_DIAS).first().cancelado is False


def test_cancelar_ensaio_de_outra_escala_pelo_seletor_nao_funciona(logged_in_client, app, db):
    with app.app_context():
        _, ministerio, escala = _montar(logged_in_client)
        outra = _criar_escala(logged_in_client, ministerio.id, "Outra")
        _adicionar_ensaio(logged_in_client, outra.id)
        ensaio_da_outra = Ensaio.objects(escala_id=outra.id).first()

        logged_in_client.post(f"/escala/{escala.id}/ensaios/cancelar", data={"ensaio_id": ensaio_da_outra.id})

        assert Ensaio.objects(id=ensaio_da_outra.id).first().cancelado is False


def test_reabrir_e_remover_ensaio(logged_in_client, app, db):
    with app.app_context():
        _, _, escala = _montar(logged_in_client)
        _adicionar_ensaio(logged_in_client, escala.id)
        ensaio = Ensaio.objects(escala_id=escala.id).first()
        logged_in_client.post(f"/escala/ensaio/{ensaio.id}/cancelar")
        logged_in_client.post(f"/escala/ensaio/{ensaio.id}/reabrir")
        assert Ensaio.objects(id=ensaio.id).first().cancelado is False

        logged_in_client.post(f"/escala/ensaio/{ensaio.id}/excluir")
        assert Ensaio.objects(id=ensaio.id).first() is None


def test_quem_nao_lidera_nao_mexe_em_ensaio(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        _, _, escala = _montar(logged_in_client)
        _adicionar_ensaio(logged_in_client, escala.id)
        ensaio = Ensaio.objects(escala_id=escala.id).first()

    with sessao_isolada(app):
        assert outro_logged_in_client.post(f"/escala/ensaio/{ensaio.id}/cancelar").status_code == 404
        assert outro_logged_in_client.post(
            f"/escala/{escala.id}/ensaios",
            data={"ensaio-data": DAQUI_5_DIAS.isoformat()},
        ).status_code == 404
        assert Ensaio.objects(id=ensaio.id).first().cancelado is False


def test_excluir_escala_apaga_os_ensaios(logged_in_client, app, db):
    with app.app_context():
        _, _, escala = _montar(logged_in_client)
        _adicionar_ensaio(logged_in_client, escala.id)
        logged_in_client.post(f"/escala/{escala.id}/excluir", follow_redirects=True)
        assert Ensaio.objects(escala_id=escala.id).count() == 0


def test_inicio_mostra_ensaios_e_cancelamentos_de_quem_esta_escalado(logged_in_client, app, db):
    with app.app_context():
        _, _, escala = _montar(logged_in_client, email_escalado="ana@example.com")
        _adicionar_ensaio(logged_in_client, escala.id, data=DAQUI_3_DIAS)
        _adicionar_ensaio(logged_in_client, escala.id, data=DAQUI_5_DIAS)
        cancelado = Ensaio.objects(escala_id=escala.id, data=DAQUI_5_DIAS).first()
        logged_in_client.post(f"/escala/ensaio/{cancelado.id}/cancelar")

        html = logged_in_client.get("/dashboard").data.decode("utf-8")
        assert "Ensaios e avisos" in html
        assert "Ensaio · Culto de Domingo" in html
        assert ">Cancelado<" in html


def test_lista_do_ministerio_mostra_proximo_ensaio(logged_in_client, app, db):
    with app.app_context():
        _, ministerio, escala = _montar(logged_in_client)
        _adicionar_ensaio(logged_in_client, escala.id, data=DAQUI_3_DIAS)
        html = logged_in_client.get(f"/ministerio/{ministerio.id}").data.decode("utf-8")
        assert "Proximo ensaio:" in html
        assert DAQUI_3_DIAS.strftime("%d/%m") in html


def test_calendario_marca_o_dia_do_ensaio(logged_in_client, app, db):
    with app.app_context():
        comunidade, ministerio, escala = _montar(logged_in_client)
        _adicionar_ensaio(logged_in_client, escala.id, data=DAQUI_3_DIAS)
        consulta = f"?ano={DAQUI_3_DIAS.year}&mes={DAQUI_3_DIAS.month}"

        html_ministerio = logged_in_client.get(f"/ministerio/{ministerio.id}/calendario{consulta}").data.decode("utf-8")
        assert "Ensaio &middot; Culto de Domingo" in html_ministerio

        html_comunidade = logged_in_client.get(f"/comunidade/{comunidade.id}/calendario{consulta}").data.decode("utf-8")
        assert "Ensaio &middot; Culto de Domingo" in html_comunidade
