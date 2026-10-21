"""Areas do ministerio (Criativo -> Projecao, Midia, Live): cadastro, escala
unica agrupada por area, lider de area (so as funcoes da area dele), areas na
tela Pessoas e a area nos avisos -- ver app/ministerio/areas.py."""
from datetime import date, timedelta

from app.auth.models import User
from app.escala.models import Escala, Funcao, Membro, mensagem_para
from app.ministerio.models import AreaMinisterio, UsuarioMinisterio
from app.notificacoes import Notificacao
from tests.conftest import sessao_isolada
from tests.test_escala import _criar_comunidade, _criar_ministerio


def _criativo(cliente):
    comunidade = _criar_comunidade(cliente, "Igreja")
    criativo = _criar_ministerio(cliente, comunidade.id, nome="Criativo")
    url = f"/ministerio/{criativo.id}/areas"
    cliente.post(url, data={"nome": "Projeção", "cor": "azul", "funcoes": "Operador\nLetras"})
    cliente.post(url, data={"nome": "Live", "cor": "vermelho", "funcoes": "Câmera 1\nCâmera 2\nCorte"})
    cliente.post(url, data={"nome": "Mídia", "funcoes": ""})
    areas = {a.nome: a for a in AreaMinisterio.objects(ministerio_id=criativo.id)}
    return comunidade, criativo, areas


def _escala_do_criativo(cliente, criativo, areas_marcadas):
    amanha = (date.today() + timedelta(days=1)).isoformat()
    cliente.post(f"/escala/ministerio/{criativo.id}/nova", data={
        "nome": "Culto Domingo", "departamento": "Midia", "data": amanha, "horario": "19:00",
        "areas": [str(a.id) for a in areas_marcadas],
    })
    return Escala.objects(ministerio_id=criativo.id).order_by("-id").first()


def test_cadastro_de_areas_e_escala_unica_agrupada(logged_in_client, app, db):
    with app.app_context():
        _, criativo, areas = _criativo(logged_in_client)
        assert [a.nome for a in AreaMinisterio.objects(ministerio_id=criativo.id).order_by("ordem")] == ["Projeção", "Live", "Mídia"]
        assert areas["Live"].funcoes_padrao == ["Câmera 1", "Câmera 2", "Corte"]
        tela = logged_in_client.get(f"/ministerio/{criativo.id}/areas").data.decode()
        assert "Projeção" in tela and "Câmera 1" in tela
        assert "Áreas" in logged_in_client.get(f"/ministerio/{criativo.id}").data.decode()

        # escala com Projecao e Live marcadas: uma escala so, funcoes das areas
        escala = _escala_do_criativo(logged_in_client, criativo, [areas["Projeção"], areas["Live"]])
        funcoes = list(Funcao.objects(escala_id=escala.id).order_by("ordem"))
        assert [(f.nome, f.area_id) for f in funcoes] == [
            ("Operador", areas["Projeção"].id), ("Letras", areas["Projeção"].id),
            ("Câmera 1", areas["Live"].id), ("Câmera 2", areas["Live"].id), ("Corte", areas["Live"].id),
        ]
        html = logged_in_client.get(f"/escala/{escala.id}").data.decode()
        assert html.count("data-area-cabecalho") == 2
        assert html.index(f'data-area-cabecalho="{areas["Projeção"].id}"') < html.index(f'data-area-cabecalho="{areas["Live"].id}"')

        # area sem funcoes padrao ganha 1 funcao com o nome dela
        so_midia = _escala_do_criativo(logged_in_client, criativo, [areas["Mídia"]])
        assert [f.nome for f in Funcao.objects(escala_id=so_midia.id)] == ["Mídia"]
        # nenhuma marcada: funcoes do departamento, como antes
        sem_area = _escala_do_criativo(logged_in_client, criativo, [])
        assert Funcao.objects(escala_id=sem_area.id, area_id__ne=None).count() == 0
        assert Funcao.objects(escala_id=sem_area.id).count() > 0

        # nova funcao numa area cai junto das outras da area na grade
        logged_in_client.post(f"/escala/{escala.id}/funcao/adicionar", data={"nome": "Slides", "area_id": areas["Projeção"].id})
        html = logged_in_client.get(f"/escala/{escala.id}").data.decode()
        assert html.index("Slides") < html.index(f'data-area-cabecalho="{areas["Live"].id}"')


def test_editar_ordenar_e_excluir_area(logged_in_client, app, db):
    with app.app_context():
        _, criativo, areas = _criativo(logged_in_client)
        base = f"/ministerio/{criativo.id}/areas/{areas['Live'].id}"
        logged_in_client.post(base + "/editar", data={"nome": "Transmissão", "cor": "roxo", "funcoes": "Câmera"})
        live = AreaMinisterio.objects(id=areas["Live"].id).first()
        assert (live.nome, live.cor, live.funcoes_padrao) == ("Transmissão", "roxo", ["Câmera"])
        logged_in_client.post(base + "/mover/cima")
        assert [a.nome for a in AreaMinisterio.objects(ministerio_id=criativo.id).order_by("ordem")] == ["Transmissão", "Projeção", "Mídia"]

        escala = _escala_do_criativo(logged_in_client, criativo, [live])
        logged_in_client.post(base + "/excluir")
        assert AreaMinisterio.objects(id=live.id).first() is None
        assert Funcao.objects(escala_id=escala.id).first().area_id is None  # funcao continua, sem area


def test_lider_de_area_gerencia_so_a_area_dele(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade, criativo, areas = _criativo(logged_in_client)
        escala = _escala_do_criativo(logged_in_client, criativo, [areas["Projeção"], areas["Live"]])
        bruno = User.objects(email="bruno@example.com").first()
        UsuarioMinisterio(usuario_id=bruno.id, ministerio_id=criativo.id, papel="membro").save()
        linha = UsuarioMinisterio.objects(usuario_id=bruno.id, ministerio_id=criativo.id).first()
        # o lider do ministerio define: Bruno lidera a Live (liderar = atuar)
        logged_in_client.post(f"/ministerio/{criativo.id}/papeis/{linha.id}/areas", data={"areas_lider": [str(areas["Live"].id)]})
        linha.reload()
        assert linha.areas_lider == [areas["Live"].id] and linha.areas == [areas["Live"].id]
        pessoas = logged_in_client.get(f"/ministerio/{criativo.id}/papeis").data.decode()
        assert f'data-area-selo="{areas["Live"].id}"' in pessoas and "Live · líder" in pessoas
        carla = Membro(comunidade_id=comunidade.id, nome="Carla", email="carla@example.com").save()
        camera = Funcao.objects(escala_id=escala.id, nome="Câmera 1").first()
        operador = Funcao.objects(escala_id=escala.id, nome="Operador").first()

    with sessao_isolada(app):
        html = outro_logged_in_client.get(f"/escala/{escala.id}").data.decode()
        assert "Você lidera" in html
        # so as vagas da Live tem a escolha de pessoa (3 funcoes)
        assert html.count("data-atribuicao-item=") == 3
        assert outro_logged_in_client.post(f"/escala/funcao/{camera.id}/adicionar", data={"membro_id": carla.id}).status_code == 302
        assert Funcao.objects(id=camera.id).first().membro_id == carla.id
        assert outro_logged_in_client.post(f"/escala/funcao/{operador.id}/adicionar", data={"membro_id": carla.id}).status_code == 404
        assert Funcao.objects(id=operador.id).first().membro_id is None
        # nao cria escala nem mexe nas areas
        assert outro_logged_in_client.get(f"/ministerio/{criativo.id}/areas").status_code == 404


def test_area_nos_avisos_e_lider_da_area_avisado(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade, criativo, areas = _criativo(logged_in_client)
        escala = _escala_do_criativo(logged_in_client, criativo, [areas["Live"]])
        bruno = User.objects(email="bruno@example.com").first()
        UsuarioMinisterio(usuario_id=bruno.id, ministerio_id=criativo.id, papel="membro",
                          areas=[areas["Live"].id], areas_lider=[areas["Live"].id]).save()
        ana = User.objects(email="ana@example.com").first()
        eu = Membro(comunidade_id=comunidade.id, nome="Ana", email=ana.email).save()
        camera = Funcao.objects(escala_id=escala.id, nome="Câmera 1").first()
        logged_in_client.post(f"/escala/funcao/{camera.id}/adicionar", data={"membro_id": eu.id})
        camera.reload()
        assert camera.nome_exibido == "Câmera 1 · Live"
        assert "Câmera 1 · Live" in mensagem_para(escala, camera, eu)
        assert Notificacao.objects(usuario_id=ana.id, tipo="escalado", titulo__contains="Câmera 1 · Live").count() == 1
        # escalada numa funcao da Live, a conta passa a constar na area
        linha_ana = UsuarioMinisterio.objects(usuario_id=ana.id, ministerio_id=criativo.id).first()
        assert linha_ana is None or areas["Live"].id in (linha_ana.areas or [])

        # a propria escalada pede troca: o lider da Live (Bruno) e avisado
        logged_in_client.post(f"/escala/funcao/{camera.id}/status", data={"status": "troca_solicitada", "troca_sugestao_membro_id": 0})
        assert Notificacao.objects(usuario_id=bruno.id, tipo="troca_solicitada").count() == 1


def test_escalado_na_area_entra_na_area(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade, criativo, areas = _criativo(logged_in_client)
        escala = _escala_do_criativo(logged_in_client, criativo, [areas["Live"]])
        bruno_membro = Membro(comunidade_id=comunidade.id, nome="Bruno", email="bruno@example.com").save()
        camera = Funcao.objects(escala_id=escala.id, nome="Câmera 1").first()
        logged_in_client.post(f"/escala/funcao/{camera.id}/adicionar", data={"membro_id": bruno_membro.id})
        bruno = User.objects(email="bruno@example.com").first()
        linha = UsuarioMinisterio.objects(usuario_id=bruno.id, ministerio_id=criativo.id).first()
        assert linha is not None and linha.areas == [areas["Live"].id] and not linha.areas_lider

        # na proxima escala, quem atua na Live vem primeiro (com o nome da area)
        outra = _escala_do_criativo(logged_in_client, criativo, [areas["Live"]])
        html = logged_in_client.get(f"/escala/{outra.id}").data.decode()
        assert "Bruno · Live" in html
