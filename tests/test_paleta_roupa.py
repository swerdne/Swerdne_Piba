"""Paleta de cores do dia (codigo de roupa: blusa + calca) por escala:
escolher no criar/editar, mostrar na escala e em Minha escala, e mandar no
aviso (WhatsApp/e-mail) so quando definida."""
from datetime import date, timedelta

from app.escala.models import PALETA_PERSONALIZADA, PALETAS_ROUPA, Escala
from tests.test_escala import _criar_comunidade, _criar_membro, _criar_ministerio, _escalar, _funcao_por_nome


def _ministerio(cliente):
    return _criar_ministerio(cliente, _criar_comunidade(cliente).id)


def _nova(cliente, ministerio_id, nome="Culto", **campos):
    dados = {"nome": nome, "departamento": "Louvor", "data": "", "horario": ""}
    dados.update(campos)
    resposta = cliente.post(f"/escala/ministerio/{ministerio_id}/nova", data=dados, follow_redirects=True)
    return resposta, Escala.objects(nome=nome, ministerio_id=ministerio_id).first()


def test_presets_tem_os_combinados_e_personalizada_no_fim(logged_in_client, app, db):
    nomes = [p[1] for p in PALETAS_ROUPA]
    assert nomes[:4] == ["Branco e Jeans", "Preto e Jeans", "Total Black", "Total White"]
    assert {"Azul-marinho e Jeans", "Cinza e Preto", "Vinho/Bordô e Preto", "Branco e Preto"} <= set(nomes)
    with app.app_context():
        ministerio = _ministerio(logged_in_client)
        tela = logged_in_client.get(f"/escala/ministerio/{ministerio.id}/nova").data.decode()
        assert "Paleta de cores do dia" in tela
        assert tela.index("Branco e Preto") < tela.index("Personalizada (escrever)")


def test_preset_aparece_na_escala_e_em_minha_escala(logged_in_client, app, db):
    with app.app_context():
        ministerio = _ministerio(logged_in_client)
        _, escala = _nova(logged_in_client, ministerio.id, data=(date.today() + timedelta(days=2)).isoformat(),
                          paleta="branco-jeans")
        assert (escala.paleta_roupa, escala.paleta_do_dia) == ("branco-jeans", "blusa branca e calça jeans")

        tela = logged_in_client.get(f"/escala/{escala.id}").data.decode()
        assert "Roupa do dia" in tela and "Blusa branca e calça jeans" in tela and "data-paleta-do-dia" in tela

        eu = _criar_membro(logged_in_client, ministerio.comunidade_id, "Ana", email="ana@example.com")
        _escalar(logged_in_client, _funcao_por_nome(escala, "Baixo").id, eu.id)
        minha = logged_in_client.get(f"/minha-escala?escala={escala.id}").data.decode()
        assert "Roupa do dia" in minha and "Blusa branca e calça jeans" in minha


def test_personalizada_exige_texto_e_editar_pode_trocar_ou_tirar(logged_in_client, app, db):
    with app.app_context():
        ministerio = _ministerio(logged_in_client)
        resposta, escala = _nova(logged_in_client, ministerio.id, paleta=PALETA_PERSONALIZADA, paleta_texto="  ")
        assert escala is None and "Escreva a combinacao de roupa" in resposta.data.decode()

        _, escala = _nova(logged_in_client, ministerio.id, paleta=PALETA_PERSONALIZADA,
                          paleta_texto="Blusa azul royal e calça jeans escura")
        assert escala.paleta_do_dia == "Blusa azul royal e calça jeans escura"

        url = f"/escala/{escala.id}/editar"
        assert 'value="Blusa azul royal e calça jeans escura"' in logged_in_client.get(url).data.decode()
        logged_in_client.post(url, data={"nome": "Culto", "paleta": "total-black", "paleta_texto": "sobra"})
        escala = Escala.objects(id=escala.id).first()
        assert (escala.paleta_roupa, escala.paleta_roupa_texto, escala.paleta_do_dia) == (
            "total-black", None, "blusa preta e calça preta")

        logged_in_client.post(url, data={"nome": "Culto", "paleta": ""})
        escala = Escala.objects(id=escala.id).first()
        assert escala.paleta_do_dia is None
        assert "Roupa do dia" not in logged_in_client.get(f"/escala/{escala.id}").data.decode()


def test_aviso_leva_a_roupa_so_quando_definida(logged_in_client, app, db, monkeypatch):
    """WhatsApp: o template tem 4 variaveis fixas -- a roupa vai junto do nome
    da escala (3a variavel), sem 5a variavel. E-mail/SMS: linha propria."""
    enviados = []
    monkeypatch.setattr("app.escala.routes.enviar_whatsapp_template",
                        lambda destinatario, nome_template, parametros: enviados.append(parametros))
    with app.app_context():
        ministerio = _ministerio(logged_in_client)
        _, com = _nova(logged_in_client, ministerio.id, nome="Culto Branco", paleta="branco-preto")
        _, sem = _nova(logged_in_client, ministerio.id, nome="Culto Livre")
        pessoa = _criar_membro(logged_in_client, ministerio.comunidade_id, "Bia", telefone="(11) 91234-5678")
        _escalar(logged_in_client, _funcao_por_nome(com, "Baixo").id, pessoa.id)  # aviso ao escalar
        _escalar(logged_in_client, _funcao_por_nome(sem, "Baixo").id, pessoa.id)

        assert len(enviados) == 2 and all(len(p) == 4 for p in enviados)
        assert enviados[0][2] == "Culto Branco · roupa do dia: blusa branca e calça preta"
        assert "\n" not in enviados[0][2]  # variavel de template nao aceita quebra de linha
        assert enviados[1][2] == "Culto Livre"

        from app.escala.models import mensagem_para

        funcao = _funcao_por_nome(com, "Baixo")
        assert "Roupa do dia: blusa branca e calça preta." in mensagem_para(com, funcao, pessoa)
        assert "Roupa do dia" not in mensagem_para(sem, _funcao_por_nome(sem, "Baixo"), pessoa)
