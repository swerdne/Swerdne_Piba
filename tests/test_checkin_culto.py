"""Secao "Check-in" do ministerio (tipo de uso, culto, tolerancia), check-in de
culto, visoes separadas nas estatisticas e historico individual."""
from datetime import datetime, time, timedelta

from app.auth.models import User
from app.escala.checkin import checkin_ligado
from app.escala.estatisticas import hoje_brasilia, montar, tipos_ligados
from app.escala.models import Escala, PresencaCulto
from app.ministerio.models import Ministerio, UsuarioMinisterio
from tests.conftest import sessao_isolada
from tests.test_checkin import IGREJA, LONGE, PERTO, _montar


def _config(cliente, ministerio, tipos, dias=(), horario=""):
    return cliente.post(f"/ministerio/{ministerio.id}/checkin/config", data={
        "acao": "tipo_uso", "tipo": list(tipos), "dia_culto": [str(d) for d in dias], "culto_horario": horario,
    })


def _checkin_culto(cliente, ministerio, ponto, precisao=20):
    return cliente.post(f"/ministerio/{ministerio.id}/culto/checkin",
                        data={"latitude": ponto[0], "longitude": ponto[1], "precisao": precisao})


def _hoje_e_culto(cliente, ministerio, horario="19:00"):
    return _config(cliente, ministerio, ["escala", "culto"], dias=[hoje_brasilia().weekday()], horario=horario)


def _recarregar(ministerio):
    return Ministerio.objects(id=ministerio.id).first()


def test_tipo_de_uso_salva_culto_e_desativado(logged_in_client, app, db):
    with app.app_context():
        _, ministerio, escala, _ = _montar(logged_in_client)
        _config(logged_in_client, ministerio, ["ensaio", "culto"], dias=[6, 2], horario="19:30")
        m = _recarregar(ministerio)
        assert (m.checkin_escala, m.checkin_ensaio, m.checkin_culto) == (False, True, True)
        assert m.dias_culto_efetivos == [2, 6] and m.culto_horario == time(19, 30)

        _config(logged_in_client, ministerio, [])  # nenhum = desativado
        m = _recarregar(ministerio)
        assert not any([m.checkin_escala, m.checkin_ensaio, m.checkin_culto])
        assert not checkin_ligado(Escala.objects(id=escala.id).first(), "escala")
        assert "data-checkin-card" not in logged_in_client.get(f"/minha-escala?escala={escala.id}").get_data(as_text=True)


def test_culto_sem_dias_ou_horario_invalido_nao_salva(logged_in_client, app, db):
    with app.app_context():
        _, ministerio, _, _ = _montar(logged_in_client)
        _config(logged_in_client, ministerio, ["culto"])
        assert not _recarregar(ministerio).checkin_culto
        _config(logged_in_client, ministerio, ["culto"], dias=[6], horario="25:99")
        assert not _recarregar(ministerio).checkin_culto


def test_secao_checkin_so_para_lider(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade, ministerio, _, _ = _montar(logged_in_client)
        html = logged_in_client.get(f"/ministerio/{ministerio.id}").get_data(as_text=True)
        assert 'id="checkin"' in html and "Tipo de uso" in html and "Tolerância de horário" in html
        assert "<details id=\"checkin\"" in html and "open" not in html.split('<details id="checkin"')[1].split(">")[0]
        aberta = logged_in_client.get(f"/ministerio/{ministerio.id}?checkin=1").get_data(as_text=True)
        assert "open" in aberta.split('<details id="checkin"')[1].split(">")[0]
        bruno = User.objects(email="bruno@example.com").first()
        UsuarioMinisterio(usuario_id=bruno.id, ministerio_id=ministerio.id, papel="membro").save()
    with sessao_isolada(app):
        html = outro_logged_in_client.get(f"/ministerio/{ministerio.id}").get_data(as_text=True)
        assert 'id="checkin"' not in html
        assert outro_logged_in_client.get(f"/ministerio/{ministerio.id}/estatisticas").status_code == 404
        assert outro_logged_in_client.post(f"/ministerio/{ministerio.id}/checkin/config",
                                           data={"acao": "tipo_uso", "tipo": ["culto"], "dia_culto": ["6"]}).status_code == 404
    with sessao_isolada(app):
        assert not _recarregar(ministerio).checkin_culto


def test_checkin_de_culto_para_membro_nao_escalado(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        _, ministerio, _, _ = _montar(logged_in_client)
        _hoje_e_culto(logged_in_client, ministerio)
        bruno = User.objects(email="bruno@example.com").first()
    with sessao_isolada(app):
        # Ainda sem papel no ministerio: nao pode.
        assert _checkin_culto(outro_logged_in_client, ministerio, PERTO).status_code == 404
    with sessao_isolada(app):
        UsuarioMinisterio(usuario_id=bruno.id, ministerio_id=ministerio.id, papel="membro").save()
    with sessao_isolada(app):
        inicio = outro_logged_in_client.get("/dashboard").get_data(as_text=True)
        assert f"/ministerio/{ministerio.id}/culto/checkin" in inicio and "js/checkin.js" in inicio
        assert _checkin_culto(outro_logged_in_client, ministerio, LONGE).get_json()["ok"] is False
        assert _checkin_culto(outro_logged_in_client, ministerio, PERTO).get_json()["ok"] is True
        assert _checkin_culto(outro_logged_in_client, ministerio, PERTO).get_json()["ja_feito"] is True
        assert PresencaCulto.objects(ministerio_id=ministerio.id, usuario_id=bruno.id).count() == 1
        assert "Presença confirmada às" in outro_logged_in_client.get("/dashboard").get_data(as_text=True)


def test_culto_fora_do_dia_ou_desligado(logged_in_client, app, db):
    with app.app_context():
        _, ministerio, _, _ = _montar(logged_in_client)
        outro_dia = (hoje_brasilia().weekday() + 1) % 7
        _config(logged_in_client, ministerio, ["culto"], dias=[outro_dia])
        assert "não é dia de culto" in _checkin_culto(logged_in_client, ministerio, PERTO).get_json()["mensagem"]
        _config(logged_in_client, ministerio, ["escala"], dias=[hoje_brasilia().weekday()])
        assert "não está ligado" in _checkin_culto(logged_in_client, ministerio, PERTO).get_json()["mensagem"]
        assert f"/ministerio/{ministerio.id}/culto/checkin" not in logged_in_client.get("/dashboard").get_data(as_text=True)


def test_estatisticas_de_culto_separadas_e_so_tipos_ligados(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        _, ministerio, _, _ = _montar(logged_in_client)
        ontem = hoje_brasilia() - timedelta(days=1)
        _config(logged_in_client, ministerio, ["culto"], dias=[ontem.weekday()], horario="19:00")
        ana = User.objects(email="ana@example.com").first()
        bruno = User.objects(email="bruno@example.com").first()
        for u in (ana, bruno):
            UsuarioMinisterio(usuario_id=u.id, ministerio_id=ministerio.id, papel="membro").save()
        # Ana chegou 5 min antes; Bruno faltou.
        PresencaCulto(ministerio_id=ministerio.id, data=ontem, usuario_id=ana.id,
                      checkin_em=datetime.combine(ontem, time(18, 55)) + timedelta(hours=3)).save()
        ministerio = _recarregar(ministerio)

        assert tipos_ligados([ministerio]) == ["cultos"]
        dados = montar([ministerio], "30d", "cultos")
        k = dados["kpis"]
        assert (k["escalas"], k["escalados"], k["presencas"], k["faltas"]) == (1, 2, 1, 1)
        assert dados["pontualidade"]["media"] == -5 and dados["alerta"] == 0
        nomes = {p["nome"] for p in dados["pessoas"]}
        assert nomes == {ana.name or ana.username or ana.email, bruno.name or bruno.username or bruno.email}
        # Escalas nao entram na visao de culto (e vice-versa).
        assert montar([ministerio], "30d", "escalas")["kpis"]["escalados"] == 0

        html = logged_in_client.get(f"/ministerio/{ministerio.id}/estatisticas?periodo=30d").get_data(as_text=True)
        assert "1 de 2 esperados" in html and 'aria-label="Tipo de check-in"' not in html  # um tipo so: sem abas
        assert "Mais trocas" not in html

        _config(logged_in_client, ministerio, ["escala", "culto"], dias=[ontem.weekday()])
        html = logged_in_client.get(f"/ministerio/{ministerio.id}/estatisticas?periodo=30d&tipo=cultos").get_data(as_text=True)
        assert 'aria-label="Tipo de check-in"' in html and ">Cultos</a>" in html and ">Ensaios</a>" not in html


def test_historico_individual_so_com_os_proprios_dados(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        _, ministerio, escala, _ = _montar(logged_in_client, dias=-1)
        ana = User.objects(email="ana@example.com").first()
        PresencaCulto(ministerio_id=ministerio.id, data=hoje_brasilia() - timedelta(days=2), usuario_id=ana.id,
                      checkin_em=datetime.utcnow()).save()
        html = logged_in_client.get("/minhas-presencas").get_data(as_text=True)
        assert "Meu histórico de presença" in html and "Culto" in html and "Sem presença" in html
        assert "/minhas-presencas" in logged_in_client.get(f"/minha-escala?escala={escala.id}").get_data(as_text=True)
    with sessao_isolada(app):
        html = outro_logged_in_client.get("/minhas-presencas").get_data(as_text=True)
        assert "Nenhuma escala, ensaio ou culto" in html


def test_local_aceita_latitude_zero_e_avisa_raio_em_portugues(logged_in_client, app, db):
    with app.app_context():
        comunidade, _, _, _ = _montar(logged_in_client, local=False)
        url = f"/comunidade/{comunidade.id}/local-checkin"
        html = logged_in_client.post(url, data={"latitude": IGREJA[0], "longitude": IGREJA[1], "raio_checkin_m": "100,5"}).get_data(as_text=True)
        assert "Use um número inteiro de metros" in html and "Not a valid" not in html
        logged_in_client.post(url, data={"latitude": "0", "longitude": "-50.1", "raio_checkin_m": 100})
        comunidade.reload()
        assert comunidade.latitude == 0.0 and comunidade.longitude == -50.1


def test_tela_do_mapa_sem_bloco_quando_usar(logged_in_client, app, db):
    with app.app_context():
        _, ministerio, _, _ = _montar(logged_in_client)
        html = logged_in_client.get(f"/ministerio/{ministerio.id}/local-checkin").get_data(as_text=True)
        assert "Quando usar o check-in" not in html and "mapa-leaflet" in html
