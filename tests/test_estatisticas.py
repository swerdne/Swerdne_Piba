"""Estatisticas de comparecimento (app/escala/estatisticas.py)."""
from datetime import datetime, time, timedelta

from app.escala.estatisticas import hoje_brasilia, montar, verificar_faltas_seguidas
from app.escala.models import AlertaFaltas, Escala, Funcao, Membro, RegistroTroca
from app.ministerio.models import Ministerio
from app.notificacoes import Notificacao
from tests.conftest import sessao_isolada
from tests.test_escala import _criar_comunidade, _criar_ministerio, _escalar, _funcao_por_nome, _criar_escala


def _base(cliente):
    comunidade = _criar_comunidade(cliente)
    ministerio = _criar_ministerio(cliente, comunidade.id)
    ana = Membro(comunidade_id=comunidade.id, nome="Ana", email="ana@example.com").save()
    bia = Membro(comunidade_id=comunidade.id, nome="Bia").save()
    return comunidade, ministerio, ana, bia


def _escala(ministerio, dias_atras, pessoas, horario=time(19, 0), cancelada=False):
    """pessoas: [(membro, funcao, chegada)] -- chegada em minutos em relacao
    ao horario (check-in), "lider" (presente sem check-in) ou None (falta)."""
    data = hoje_brasilia() - timedelta(days=dias_atras)
    escala = Escala(ministerio_id=ministerio.id, nome="Culto", departamento="Louvor",
                    data=data, horario=horario, cancelada=cancelada).save()
    for membro, funcao, chegada in pessoas:
        f = Funcao(escala_id=escala.id, nome=funcao, membro_id=membro.id, status="confirmado")
        if chegada == "lider":
            f.status = "presente"
        elif chegada is not None:
            f.status = "presente"
            f.checkin_em = datetime.combine(data, horario or time(0)) + timedelta(minutes=chegada, hours=3)
        f.save()
    return escala


def _pessoa(dados, nome):
    return next(p for p in dados["pessoas"] if p["nome"] == nome)


def test_totais_taxa_e_pontualidade(logged_in_client, app, db):
    with app.app_context():
        _, ministerio, ana, bia = _base(logged_in_client)
        _escala(ministerio, 3, [(ana, "Baixo", -5), (bia, "Bateria", None)])
        _escala(ministerio, 10, [(ana, "Baixo", 8), (bia, "Bateria", 25)])
        _escala(ministerio, 17, [(ana, "Baixo", "lider"), (bia, "Bateria", None)])

        dados = montar([ministerio], "30d")
        k = dados["kpis"]
        assert (k["escalas"], k["escalados"], k["presencas"], k["checkins"], k["faltas"], k["taxa"]) == (3, 6, 4, 3, 2, 67)

        p = dados["pontualidade"]
        assert p["total"] == 3 and p["media"] == round((-5 + 8 + 25) / 3)
        assert p["faixas"]["adiantado"]["quantidade"] == 1
        assert p["faixas"]["no_horario"]["quantidade"] == 1  # 8 min, tolerancia padrao 10
        assert p["faixas"]["atrasado"]["quantidade"] == 1

        assert _pessoa(dados, "Ana")["taxa"] == 100 and _pessoa(dados, "Ana")["checkins"] == 2
        bia_dados = _pessoa(dados, "Bia")
        assert (bia_dados["faltas"], bia_dados["taxa"], bia_dados["chegada_media"], bia_dados["atrasos"]) == (2, 33, 25, 1)
        assert dados["pessoas"][0]["nome"] == "Ana"  # maior comparecimento primeiro

        funcoes = {f["nome"]: f["taxa"] for f in dados["por_funcao"]}
        assert funcoes == {"Baixo": 100, "Bateria": 33}
        assert dados["por_funcao"][0]["nome"] == "Bateria"  # menor taxa primeiro
        assert sum(d["escalados"] for d in dados["por_dia"]) == 6


def test_tolerancia_configurada_muda_a_faixa(logged_in_client, app, db):
    with app.app_context():
        _, ministerio, ana, _ = _base(logged_in_client)
        _escala(ministerio, 2, [(ana, "Baixo", 8)])
        ministerio.tolerancia_atraso_min = 5
        ministerio.save()
        faixas = montar([ministerio], "30d")["pontualidade"]["faixas"]
        assert faixas["atrasado"]["quantidade"] == 1 and faixas["no_horario"]["quantidade"] == 0


def test_fora_da_conta(logged_in_client, app, db):
    """Sem presenca registrada, cancelada, de hoje ou fora do periodo nao entram;
    check-in longe do horario conta presenca mas nao entra na media."""
    with app.app_context():
        _, ministerio, ana, bia = _base(logged_in_client)
        _escala(ministerio, 4, [(ana, "Baixo", None), (bia, "Bateria", None)])  # ninguem registrou
        _escala(ministerio, 5, [(ana, "Baixo", 0)], cancelada=True)
        _escala(ministerio, 0, [(ana, "Baixo", 0)])  # hoje
        _escala(ministerio, 40, [(ana, "Baixo", 0)])  # fora dos 30 dias
        _escala(ministerio, 6, [(ana, "Baixo", -600)])  # check-in de manha, culto a noite

        dados = montar([ministerio], "30d")
        assert dados["kpis"]["escalas"] == 1 and dados["kpis"]["sem_registro"] == 1
        assert dados["kpis"]["presencas"] == 1 and dados["pontualidade"]["total"] == 0


def test_pedido_de_troca_fica_registrado(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        escala = _criar_escala(logged_in_client, ministerio.id, "Culto",
                               data=(hoje_brasilia() - timedelta(days=2)).isoformat(), horario="19:00")
        ana = Membro(comunidade_id=comunidade.id, nome="Ana", email="ana@example.com").save()
        funcao = _funcao_por_nome(escala, "Baixo")
        _escalar(logged_in_client, funcao.id, ana.id)

        logged_in_client.post(f"/escala/funcao/{funcao.id}/status", data={"status": "troca_solicitada", "troca_motivo": "Viagem"})
        logged_in_client.post(f"/escala/funcao/{funcao.id}/status", data={"status": "troca_solicitada"})  # repetido nao conta de novo
        assert RegistroTroca.objects(membro_id=ana.id).count() == 1

        dados = montar([ministerio], "30d")
        assert dados["kpis"]["trocas"] == 1 and _pessoa(dados, "Ana")["trocas"] == 1


def test_alerta_de_faltas_seguidas(logged_in_client, app, db):
    with app.app_context():
        _, ministerio, ana, bia = _base(logged_in_client)
        _escala(ministerio, 15, [(ana, "Baixo", None), (bia, "Bateria", 0)])
        _escala(ministerio, 8, [(ana, "Baixo", None), (bia, "Bateria", 0)])
        _escala(ministerio, 1, [(ana, "Baixo", None), (bia, "Bateria", 0)])

        verificar_faltas_seguidas()
        avisos = list(Notificacao.objects(tipo="faltas_seguidas"))
        assert len(avisos) == 1 and "Ana: 3 faltas seguidas" in avisos[0].titulo
        assert _pessoa(montar([ministerio], "30d"), "Ana")["em_alerta"] is True

        verificar_faltas_seguidas()  # mesma sequencia: nao avisa de novo
        assert Notificacao.objects(tipo="faltas_seguidas").count() == 1
        assert AlertaFaltas.objects.count() == 1


def test_alerta_desligado(logged_in_client, app, db):
    with app.app_context():
        _, ministerio, ana, bia = _base(logged_in_client)
        ministerio.alerta_faltas_seguidas = 0
        ministerio.save()
        for dias in (15, 8, 1):
            _escala(ministerio, dias, [(ana, "Baixo", None), (bia, "Bateria", 0)])
        verificar_faltas_seguidas()
        assert Notificacao.objects(tipo="faltas_seguidas").count() == 0


def test_tela_do_ministerio_e_ajustes(logged_in_client, outro_logged_in_client, app, db):
    with app.app_context():
        _, ministerio, ana, bia = _base(logged_in_client)
        _escala(ministerio, 3, [(ana, "Baixo", -5), (bia, "Bateria", None)])

        url = f"/ministerio/{ministerio.id}/estatisticas"
        html = logged_in_client.get(url + "?periodo=30d").get_data(as_text=True)
        assert "Estatísticas de comparecimento" in html and "50%" in html and "grafico-evolucao" in html
        assert "5 min antes" in html
        with sessao_isolada(app):
            assert outro_logged_in_client.get(url).status_code == 404

        config = f"/ministerio/{ministerio.id}/checkin/config"
        logged_in_client.post(config, data={"acao": "tolerancia", "tolerancia_atraso_min": 0, "alerta_faltas_seguidas": 5})
        ministerio = Ministerio.objects(id=ministerio.id).first()
        assert (ministerio.tolerancia_atraso_min, ministerio.alerta_faltas_seguidas) == (0, 5)

        logged_in_client.post(config, data={"acao": "tolerancia", "tolerancia_atraso_min": 99, "alerta_faltas_seguidas": 5})
        assert Ministerio.objects(id=ministerio.id).first().tolerancia_atraso_min == 0

        assert f"/ministerio/{ministerio.id}/estatisticas" in logged_in_client.get(f"/ministerio/{ministerio.id}").get_data(as_text=True)


def test_tela_da_comunidade_filtra_por_ministerio(logged_in_client, outro_logged_in_client, app, db):
    with app.app_context():
        comunidade, louvor, ana, bia = _base(logged_in_client)
        midia = _criar_ministerio(logged_in_client, comunidade.id, nome="Midia")
        _escala(louvor, 3, [(ana, "Baixo", 0), (bia, "Bateria", 0)])
        _escala(midia, 3, [(ana, "Projecao", None), (bia, "Som", 0)])

        url = f"/comunidade/{comunidade.id}/estatisticas"
        todos = logged_in_client.get(url + "?periodo=30d").get_data(as_text=True)
        assert "75%" in todos and "Todos os ministérios" in todos
        so_midia = logged_in_client.get(url + f"?periodo=30d&ministerio={midia.id}").get_data(as_text=True)
        assert "50%" in so_midia and "Projecao" in so_midia and "Bateria" not in so_midia
        with sessao_isolada(app):
            assert outro_logged_in_client.get(url).status_code == 404
        assert url in logged_in_client.get(f"/comunidade/{comunidade.id}").get_data(as_text=True)


def test_tela_sem_dados(logged_in_client, app, db):
    with app.app_context():
        _, ministerio, _, _ = _base(logged_in_client)
        html = logged_in_client.get(f"/ministerio/{ministerio.id}/estatisticas").get_data(as_text=True)
        assert "Ainda não há presenças registradas" in html and "chart.umd" not in html
