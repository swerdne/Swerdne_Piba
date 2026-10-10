"""Check-in configuravel (ministerio + cada escala) e check-in nos ensaios."""
from datetime import timedelta

from app.escala.checkin import checkin_ligado
from app.escala.estatisticas import montar
from app.escala.models import Ensaio, Escala, Funcao, PresencaEnsaio
from app.ministerio.models import Ministerio
from tests.conftest import sessao_isolada
from tests.test_checkin import LONGE, PERTO, _checkin, _hoje, _montar


def _ensaio(escala, dias=0, cancelado=False):
    return Ensaio(escala_id=escala.id, data=_hoje() + timedelta(days=dias), cancelado=cancelado).save()


def _checkin_ensaio(cliente, ensaio, ponto, precisao=20):
    return cliente.post(f"/escala/ensaio/{ensaio.id}/checkin",
                        data={"latitude": ponto[0], "longitude": ponto[1], "precisao": precisao})


def _ligar_ensaios(cliente, ministerio, escala=True, ensaio=True):
    tipos = [t for t, ligado in (("escala", escala), ("ensaio", ensaio)) if ligado]
    return cliente.post(f"/ministerio/{ministerio.id}/checkin/config", data={"acao": "tipo_uso", "tipo": tipos})


def test_padrao_liga_escala_e_desliga_ensaio(logged_in_client, app, db):
    with app.app_context():
        _, _, escala, _ = _montar(logged_in_client)
        assert checkin_ligado(escala, "escala") is True
        assert checkin_ligado(escala, "ensaio") is False


def test_ministerio_configura_e_escala_sobrepoe(logged_in_client, app, db):
    with app.app_context():
        _, ministerio, escala, _ = _montar(logged_in_client)
        _ligar_ensaios(logged_in_client, ministerio, escala=False, ensaio=True)
        ministerio = Ministerio.objects(id=ministerio.id).first()
        assert (ministerio.checkin_escala, ministerio.checkin_ensaio) == (False, True)
        escala = Escala.objects(id=escala.id).first()
        assert not checkin_ligado(escala, "escala") and checkin_ligado(escala, "ensaio")

        logged_in_client.post(f"/escala/{escala.id}/checkin/config",
                              data={"checkin_escala_modo": "ligado", "checkin_ensaio_modo": "desligado"})
        escala = Escala.objects(id=escala.id).first()
        assert checkin_ligado(escala, "escala") and not checkin_ligado(escala, "ensaio")

        # "Igual ao ministerio" volta a seguir o padrao dele.
        logged_in_client.post(f"/escala/{escala.id}/checkin/config", data={"checkin_escala_modo": "", "checkin_ensaio_modo": "x"})
        escala = Escala.objects(id=escala.id).first()
        assert (escala.checkin_escala_modo, escala.checkin_ensaio_modo) == (None, None)
        assert not checkin_ligado(escala, "escala")

        html = logged_in_client.get(f"/escala/{escala.id}").get_data(as_text=True)
        assert "Check-in desta escala" in html and "Igual ao ministério (desligado)" in html


def test_so_lider_configura_a_escala(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        _, _, escala, _ = _montar(logged_in_client)
    with sessao_isolada(app):
        resposta = outro_logged_in_client.post(f"/escala/{escala.id}/checkin/config", data={"checkin_escala_modo": "desligado"})
        assert resposta.status_code == 404
    with sessao_isolada(app):
        assert Escala.objects(id=escala.id).first().checkin_escala_modo is None


def test_checkin_desligado_libera_presente_manual(logged_in_client, app, db):
    with app.app_context():
        _, _, escala, funcao = _montar(logged_in_client)
        logged_in_client.post(f"/escala/{escala.id}/checkin/config", data={"checkin_escala_modo": "desligado"})

        assert _checkin(logged_in_client, escala, PERTO).get_json()["ok"] is False
        html = logged_in_client.get(f"/minha-escala?escala={escala.id}").get_data(as_text=True)
        assert "data-checkin-card" not in html and 'value="presente"' in html

        logged_in_client.post(f"/escala/funcao/{funcao.id}/status", data={"status": "presente"})
        assert Funcao.objects(id=funcao.id).first().status == "presente"


def test_checkin_no_ensaio(logged_in_client, app, db):
    with app.app_context():
        _, ministerio, escala, _ = _montar(logged_in_client, dias=5)
        ensaio = _ensaio(escala)

        # Desligado (padrao): recusa.
        assert _checkin_ensaio(logged_in_client, ensaio, PERTO).get_json()["ok"] is False
        assert f"/escala/ensaio/{ensaio.id}/checkin" not in logged_in_client.get(f"/minha-escala?escala={escala.id}").get_data(as_text=True)

        _ligar_ensaios(logged_in_client, ministerio)
        html = logged_in_client.get(f"/minha-escala?escala={escala.id}").get_data(as_text=True)
        assert f"/escala/ensaio/{ensaio.id}/checkin" in html

        assert _checkin_ensaio(logged_in_client, ensaio, LONGE).get_json()["ok"] is False
        resposta = _checkin_ensaio(logged_in_client, ensaio, PERTO).get_json()
        assert resposta["ok"] is True and "ensaio" in resposta["mensagem"]
        assert PresencaEnsaio.objects(ensaio_id=ensaio.id).count() == 1
        assert _checkin_ensaio(logged_in_client, ensaio, PERTO).get_json()["ja_feito"] is True
        assert PresencaEnsaio.objects(ensaio_id=ensaio.id).count() == 1

        # A escala em si nao vira "presente" por causa do ensaio.
        assert all(f.status != "presente" for f in Funcao.objects(escala_id=escala.id, membro_id__ne=None))
        assert "Check-in feito às" in logged_in_client.get(f"/minha-escala?escala={escala.id}").get_data(as_text=True)
        assert "Check-in: 1 de 1" in logged_in_client.get(f"/escala/{escala.id}").get_data(as_text=True)


def test_ensaio_fora_do_dia_ou_cancelado(logged_in_client, app, db):
    with app.app_context():
        _, ministerio, escala, _ = _montar(logged_in_client, dias=5)
        _ligar_ensaios(logged_in_client, ministerio)
        amanha, cancelado = _ensaio(escala, dias=1), _ensaio(escala, cancelado=True)
        assert "abre no dia do ensaio" in _checkin_ensaio(logged_in_client, amanha, PERTO).get_json()["mensagem"]
        assert "cancelado" in _checkin_ensaio(logged_in_client, cancelado, PERTO).get_json()["mensagem"]
        assert PresencaEnsaio.objects.count() == 0


def test_quem_nao_esta_escalado_nao_faz_checkin_no_ensaio(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        _, ministerio, escala, _ = _montar(logged_in_client, dias=5)
        _ligar_ensaios(logged_in_client, ministerio)
        ensaio = _ensaio(escala)
    with sessao_isolada(app):
        assert _checkin_ensaio(outro_logged_in_client, ensaio, PERTO).status_code == 404


def test_excluir_ensaio_apaga_as_presencas(logged_in_client, app, db):
    with app.app_context():
        _, ministerio, escala, _ = _montar(logged_in_client, dias=5)
        _ligar_ensaios(logged_in_client, ministerio)
        ensaio = _ensaio(escala)
        _checkin_ensaio(logged_in_client, ensaio, PERTO)
        logged_in_client.post(f"/escala/ensaio/{ensaio.id}/excluir")
        assert PresencaEnsaio.objects(ensaio_id=ensaio.id).count() == 0


def test_estatisticas_de_ensaio_separadas(logged_in_client, app, db):
    with app.app_context():
        _, ministerio, escala, funcao = _montar(logged_in_client, dias=5)
        ontem, anteontem, sem_ninguem = _ensaio(escala, dias=-1), _ensaio(escala, dias=-2), _ensaio(escala, dias=-3)
        funcao = Funcao.objects(id=funcao.id).first()
        PresencaEnsaio(ensaio_id=ontem.id, escala_id=escala.id, membro_id=funcao.membro_id, checkin_em=Ensaio.objects(id=ontem.id).first().criado_em).save()

        dados = montar([ministerio], "30d", "ensaios")
        k = dados["kpis"]
        assert (k["escalas"], k["escalados"], k["presencas"], k["faltas"], k["sem_registro"]) == (1, 1, 1, 0, 2)
        assert dados["alerta"] == 0
        assert montar([ministerio], "30d", "escalas")["kpis"]["escalados"] == 0  # a escala ainda nao aconteceu

        html = logged_in_client.get(f"/ministerio/{ministerio.id}/estatisticas?periodo=30d&tipo=ensaios").get_data(as_text=True)
        assert 'aria-current="page"' in html and "100%" in html and "Mais trocas" not in html


def test_email_do_diretorio_com_maiusculas_acha_a_conta(logged_in_client, app, db):
    """O diretorio guarda o e-mail como foi digitado; a conta e "ana@example.com"."""
    with app.app_context():
        _, ministerio, escala, funcao = _montar(logged_in_client, email="Ana@Example.COM")
        _ligar_ensaios(logged_in_client, ministerio)
        ensaio = _ensaio(escala)
        html = logged_in_client.get("/minha-escala").get_data(as_text=True)
        assert "nao esta escalado" not in html and f"/escala/ensaio/{ensaio.id}/checkin" in html
        assert _checkin_ensaio(logged_in_client, ensaio, PERTO).get_json()["ok"] is True
