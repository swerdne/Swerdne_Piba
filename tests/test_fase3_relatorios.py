"""Fase 3, item 5: relatorios -- filtro de datas livre e equilibrio de
escalas (quem esta servindo demais ou de menos)."""
from datetime import datetime, timedelta, timezone

from app.auth.models import User
from app.escala.estatisticas import equilibrio
from app.escala.models import Escala, Funcao, Membro, criar_escala_com_funcoes_padrao
from app.ministerio.models import Ministerio, UsuarioMinisterio
from tests.test_escala import _criar_comunidade, _criar_membro, _criar_ministerio


def _hoje():
    return (datetime.now(timezone.utc) - timedelta(hours=3)).date()


def _cenario(cliente):
    """Ana 6 escalas, Bruno e Carla 2, Dani (tem papel no ministerio) 0."""
    comunidade = _criar_comunidade(cliente)
    ministerio = _criar_ministerio(cliente, comunidade.id)
    pessoas = {n: _criar_membro(cliente, comunidade.id, n, email=f"{n.lower()}@exemplo.com")
               for n in ("Ana", "Bruno", "Carla", "Dani")}
    dani = User(email="dani@exemplo.com", name="Dani")
    dani.save()
    UsuarioMinisterio(usuario_id=dani.id, ministerio_id=ministerio.id, papel="membro").save()
    plano = ["Ana"] * 6 + ["Bruno", "Bruno", "Carla", "Carla"]
    for i, nome in enumerate(plano):
        escala = criar_escala_com_funcoes_padrao(ministerio_id=ministerio.id, nome=f"Culto {i}", departamento="Louvor",
                                                 data=_hoje() + timedelta(days=i - 5))
        funcao = Funcao.objects(escala_id=escala.id, nome="Baixo").first()
        funcao.membro_id = pessoas[nome].id
        funcao.save()
    # Cancelada nao conta.
    cancelada = criar_escala_com_funcoes_padrao(ministerio_id=ministerio.id, nome="Cancelada", departamento="Louvor",
                                                data=_hoje())
    Funcao.objects(escala_id=cancelada.id, nome="Baixo").update(set__membro_id=pessoas["Carla"].id)
    Escala.objects(id=cancelada.id).update(set__cancelada=True)
    return comunidade, Ministerio.objects(id=ministerio.id).first()


def test_equilibrio_conta_e_marca_demais_e_de_menos(logged_in_client, app, db):
    with app.app_context():
        _, ministerio = _cenario(logged_in_client)
        dados = equilibrio([ministerio], _hoje() - timedelta(days=30), _hoje() + timedelta(days=30))
        por_nome = {p["nome"]: p for p in dados["pessoas"]}
        assert {n: p["vezes"] for n, p in por_nome.items()} == {"Ana": 6, "Bruno": 2, "Carla": 2, "Dani": 0}
        assert dados["media"] == 2.5
        assert por_nome["Ana"]["situacao"] == "demais"
        assert por_nome["Dani"]["situacao"] == "de menos"
        assert por_nome["Bruno"]["situacao"] is None
        assert (dados["demais"], dados["de_menos"]) == (1, 1)


def test_equilibrio_so_no_periodo(logged_in_client, app, db):
    with app.app_context():
        _, ministerio = _cenario(logged_in_client)
        dados = equilibrio([ministerio], _hoje() + timedelta(days=1), _hoje() + timedelta(days=30))
        # So as 4 ultimas do plano caem no futuro: Bruno 2, Carla 2. Dani tem
        # papel no ministerio e entra com 0; Ana, sem escala nem papel, nao.
        assert {p["nome"]: p["vezes"] for p in dados["pessoas"]} == {"Bruno": 2, "Carla": 2, "Dani": 0}


def test_tela_mostra_equilibrio_e_filtro_de_datas(logged_in_client, app, db):
    with app.app_context():
        _, ministerio = _cenario(logged_in_client)
        html = logged_in_client.get(f"/ministerio/{ministerio.id}/estatisticas").get_data(as_text=True)
        assert "Equilíbrio de escalas" in html and 'data-equilibrio-pessoa="demais"' in html
        assert 'data-equilibrio-pessoa="de menos"' in html and "data-filtro-datas" in html

        de, ate = _hoje() - timedelta(days=10), _hoje() - timedelta(days=2)
        html = logged_in_client.get(f"/ministerio/{ministerio.id}/estatisticas?de={de}&ate={ate}").get_data(as_text=True)
        assert f"de {de:%d/%m/%Y} a {ate:%d/%m/%Y}" in html  # equilibrio nas datas escolhidas
        assert f'value="{de.isoformat()}"' in html and "Limpar datas" in html


def test_datas_so_no_futuro_avisam_que_presenca_conta_dias_encerrados(logged_in_client, app, db):
    with app.app_context():
        _, ministerio = _cenario(logged_in_client)
        de, ate = _hoje() + timedelta(days=1), _hoje() + timedelta(days=20)
        html = logged_in_client.get(f"/ministerio/{ministerio.id}/estatisticas?de={de}&ate={ate}").get_data(as_text=True)
        assert "O comparecimento só conta dias já encerrados" in html and "Equilíbrio de escalas" in html


def test_datas_invalidas_voltam_ao_periodo_pronto(logged_in_client, app, db):
    with app.app_context():
        _, ministerio = _cenario(logged_in_client)
        for consulta in ("de=2026-13-01&ate=2026-12-01", f"de={_hoje()}&ate={_hoje() - timedelta(days=3)}"):
            resposta = logged_in_client.get(f"/ministerio/{ministerio.id}/estatisticas?{consulta}")
            assert resposta.status_code == 200 and "Limpar datas" not in resposta.get_data(as_text=True)
