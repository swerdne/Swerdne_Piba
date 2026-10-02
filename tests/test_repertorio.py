"""Banco de musicas do ministerio (versao de projecao x versao do louvor) e
como ele chega nas escalas: folha de projecao, cifras e "Minha escala"."""
from datetime import date, timedelta

from app.escala.models import (
    Escala,
    ItemRepertorio,
    Musica,
    blocos_da_letra,
    eh_funcao_de_projecao,
)
from tests.conftest import sessao_isolada
from tests.test_escala import (
    _criar_comunidade,
    _criar_ministerio,
    _criar_escala,
    _criar_membro,
    _escalar,
    _funcao_por_nome,
)

LETRA = "[VERSO 1]\nGRANDE E O SENHOR\nDIGNO DE LOUVOR\n\n[REFRAO]\nSANTO, SANTO\n"
CIFRA = "G        D\nGrande e o Senhor\nEm       C\nDigno de louvor\n"


def _montar(cliente, dias=3):
    comunidade = _criar_comunidade(cliente)
    ministerio = _criar_ministerio(cliente, comunidade.id)
    escala = _criar_escala(cliente, ministerio.id, "Culto de Domingo",
                           data=(date.today() + timedelta(days=dias)).isoformat(), horario="18:00")
    return comunidade, ministerio, escala


def _nova_musica(cliente, ministerio_id, nome="Grande e o Senhor", tom="G", tags="adoracao, abertura"):
    cliente.post(f"/ministerio/{ministerio_id}/repertorio/nova",
                 data={"nome": nome, "artista": "Adhemar", "tom": tom, "tags": tags, "link": ""})
    return Musica.objects(ministerio_id=ministerio_id, nome=nome).first()


def _preencher(cliente, musica):
    cliente.post(f"/ministerio/repertorio/{musica.id}/projecao", data={"letra_projecao": LETRA})
    cliente.post(f"/ministerio/repertorio/{musica.id}/louvor", data={"cifra_louvor": CIFRA})


# --- Helpers puros -----------------------------------------------------------

def test_blocos_da_letra_separa_rotulos_e_slides():
    blocos = blocos_da_letra(LETRA + "\nLINHA SOLTA")
    assert blocos == [
        {"rotulo": "VERSO 1", "linhas": ["GRANDE E O SENHOR", "DIGNO DE LOUVOR"]},
        {"rotulo": "REFRAO", "linhas": ["SANTO, SANTO"]},
        {"rotulo": None, "linhas": ["LINHA SOLTA"]},
    ]
    assert blocos_da_letra(None) == []


def test_funcoes_de_projecao_pelo_nome():
    for nome in ["Projeção", "Midia", "Mídia/Slides", "Datashow", "Telão", "Transmissao/Live"]:
        assert eh_funcao_de_projecao(nome), nome
    for nome in ["Baixo", "Violao", "Ministro", "Backing Vocal"]:
        assert not eh_funcao_de_projecao(nome), nome


# --- Banco de musicas --------------------------------------------------------

def test_lider_cadastra_musica_com_tags(logged_in_client, app, db):
    with app.app_context():
        _, ministerio, _ = _montar(logged_in_client)
        musica = _nova_musica(logged_in_client, ministerio.id)
        assert musica.tom == "G"
        assert musica.tags == ["adoracao", "abertura"]

        html = logged_in_client.get(f"/ministerio/{ministerio.id}/repertorio").data.decode("utf-8")
        assert "Grande e o Senhor" in html and "adoracao" in html


def test_versoes_de_projecao_e_louvor_sao_independentes(logged_in_client, app, db):
    with app.app_context():
        _, ministerio, _ = _montar(logged_in_client)
        musica = _nova_musica(logged_in_client, ministerio.id)
        _preencher(logged_in_client, musica)

        logged_in_client.post(f"/ministerio/repertorio/{musica.id}/projecao",
                              data={"letra_projecao": "[PONTE]\nNOVA LETRA"})
        musica.reload()
        assert musica.letra_projecao == "[PONTE]\nNOVA LETRA"
        assert musica.cifra_louvor == CIFRA  # a cifra nao foi tocada

        html = logged_in_client.get(f"/ministerio/repertorio/{musica.id}").data.decode("utf-8")
        assert "PONTE" in html and "NOVA LETRA" in html
        assert "Grande e o Senhor" in html


def test_quem_nao_lidera_nao_edita_nem_ve_banco_alheio(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        _, ministerio, _ = _montar(logged_in_client)
        musica = _nova_musica(logged_in_client, ministerio.id)
        _preencher(logged_in_client, musica)
    with sessao_isolada(app):
        assert outro_logged_in_client.get(f"/ministerio/{ministerio.id}/repertorio").status_code == 404
        resposta = outro_logged_in_client.post(f"/ministerio/repertorio/{musica.id}/louvor",
                                               data={"cifra_louvor": "hackeado"})
        assert resposta.status_code == 404
        assert Musica.objects(id=musica.id).first().cifra_louvor == CIFRA


def test_excluir_musica_mantem_item_avulso_na_escala(logged_in_client, app, db):
    with app.app_context():
        _, ministerio, escala = _montar(logged_in_client)
        musica = _nova_musica(logged_in_client, ministerio.id)
        logged_in_client.post(f"/escala/{escala.id}/repertorio/banco",
                              data={"banco-musica_id": musica.id, "banco-momento": "", "banco-tom": ""})
        logged_in_client.post(f"/ministerio/repertorio/{musica.id}/excluir")

        assert Musica.objects(id=musica.id).count() == 0
        item = ItemRepertorio.objects(escala_id=escala.id).first()
        assert item.nome_musica == "Grande e o Senhor" and item.musica_id is None


# --- Escala puxando do banco -------------------------------------------------

def test_adicionar_do_banco_copia_nome_e_tom(logged_in_client, app, db):
    with app.app_context():
        _, ministerio, escala = _montar(logged_in_client)
        musica = _nova_musica(logged_in_client, ministerio.id)
        outra = _nova_musica(logged_in_client, ministerio.id, nome="Santo", tom="D")
        logged_in_client.post(f"/escala/{escala.id}/repertorio/banco",
                              data={"banco-musica_id": musica.id, "banco-momento": "Abertura", "banco-tom": ""})
        logged_in_client.post(f"/escala/{escala.id}/repertorio/banco",
                              data={"banco-musica_id": outra.id, "banco-momento": "", "banco-tom": "E"})

        itens = list(ItemRepertorio.objects(escala_id=escala.id).order_by("ordem"))
        assert [(i.nome_musica, i.tom, i.momento, i.musica_id) for i in itens] == [
            ("Grande e o Senhor", "G", "Abertura", musica.id),
            ("Santo", "E", None, outra.id),
        ]
        html = logged_in_client.get(f"/escala/{escala.id}").data.decode("utf-8")
        assert "Folha de projecao" in html and "Abertura" in html


def test_musica_de_outro_ministerio_nao_entra(logged_in_client, app, db):
    with app.app_context():
        comunidade, ministerio, escala = _montar(logged_in_client)
        outro = _criar_ministerio(logged_in_client, comunidade.id, nome="Outro")
        alheia = _nova_musica(logged_in_client, outro.id)
        logged_in_client.post(f"/escala/{escala.id}/repertorio/banco",
                              data={"banco-musica_id": alheia.id, "banco-momento": "", "banco-tom": ""})
        assert ItemRepertorio.objects(escala_id=escala.id).count() == 0


def test_folhas_de_projecao_e_cifras(logged_in_client, app, db):
    with app.app_context():
        _, ministerio, escala = _montar(logged_in_client)
        musica = _nova_musica(logged_in_client, ministerio.id)
        _preencher(logged_in_client, musica)
        logged_in_client.post(f"/escala/{escala.id}/repertorio/banco",
                              data={"banco-musica_id": musica.id, "banco-momento": "Abertura", "banco-tom": "A"})
        logged_in_client.post(f"/escala/{escala.id}/repertorio/observacoes",
                              data={"observacoes_repertorio": "Ministracao livre no fim"})

        projecao = logged_in_client.get(f"/escala/{escala.id}/repertorio/projecao").data.decode("utf-8")
        data_curta = Escala.objects(id=escala.id).first().data.strftime("%d.%m.%y")
        assert f"Escala Louvor &ndash; [{data_curta}]" in projecao
        assert "18:00h" in projecao
        assert "1. Grande e o Senhor - Abertura" in projecao
        assert "TOM A" in projecao
        assert "[VERSO 1]" in projecao and "DIGNO DE LOUVOR" in projecao
        assert "G        D" not in projecao  # projecao nao leva cifra
        assert "OBSERVACOES GERAIS" in projecao and "Ministracao livre no fim" in projecao

        cifras = logged_in_client.get(f"/escala/{escala.id}/repertorio/cifras").data.decode("utf-8")
        assert "A        E" in cifras and "Grande e o Senhor" in cifras  # tom do dia A


def test_folha_fechada_pra_quem_nao_e_da_equipe(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        _, _, escala = _montar(logged_in_client)
    with sessao_isolada(app):
        assert outro_logged_in_client.get(f"/escala/{escala.id}/repertorio/projecao").status_code == 404


def test_repertorio_avulso_continua_funcionando(logged_in_client, app, db):
    with app.app_context():
        _, _, escala = _montar(logged_in_client)
        logged_in_client.post(f"/escala/{escala.id}/repertorio/adicionar",
                              data={"nome_musica": "Musica Livre", "tom": "C", "link": ""})
        cifras = logged_in_client.get(f"/escala/{escala.id}/repertorio/cifras").data.decode("utf-8")
        assert "Musica Livre" in cifras and "fora do banco" in cifras


# --- Minha escala: cada funcao recebe a sua versao ---------------------------

def test_minha_escala_entrega_a_versao_da_funcao(logged_in_client, app, db):
    with app.app_context():
        comunidade, ministerio, escala = _montar(logged_in_client)
        musica = _nova_musica(logged_in_client, ministerio.id)
        logged_in_client.post(f"/escala/{escala.id}/repertorio/banco",
                              data={"banco-musica_id": musica.id, "banco-momento": "", "banco-tom": ""})
        membro = _criar_membro(logged_in_client, comunidade.id, "Ana", email="ana@example.com")
        baixo = _funcao_por_nome(escala, "Baixo")
        _escalar(logged_in_client, baixo.id, membro.id)

        html = logged_in_client.get("/minha-escala").data.decode("utf-8")
        assert f"/escala/{escala.id}/repertorio/cifras" in html
        assert f"/escala/{escala.id}/repertorio/projecao" not in html

        baixo.reload()
        baixo.nome = "Projeção"
        baixo.save()
        html = logged_in_client.get("/minha-escala").data.decode("utf-8")
        assert f"/escala/{escala.id}/repertorio/projecao" in html
        assert f"/escala/{escala.id}/repertorio/cifras" not in html


# --- Transposicao de tom -----------------------------------------------------

def test_transpor_cifra_mantem_letra_e_alinhamento():
    from app.escala.models import transpor_cifra
    cifra = "Intro: G  D/F#  Em7 | x2\n[Verso 1]\nG              D\nA graca de Deus\n"
    assert transpor_cifra(cifra, 2) == (
        "Intro: A  E/G#  F#m7 | x2\n[Verso 1]\nA              E\nA graca de Deus\n"
    )
    # Bemol quando o tom pede (G -> Bb), e o acorde maior "come" espaco depois dele.
    assert transpor_cifra("G   C9\nletra", 3, bemol=True) == "Bb  Eb9\nletra"


def test_transpor_tom_escolhe_a_grafia_do_tom():
    from app.escala.models import transpor_tom, semitons_entre
    assert transpor_tom("G", 3) == "Bb"
    assert transpor_tom("D", 4) == "F#"
    assert transpor_tom("Am", 5) == "Dm"
    assert transpor_tom("F#m", 1) == "Gm"
    assert semitons_entre("G", "A") == 2 and semitons_entre("G", "Gm") == 0
    assert semitons_entre(None, "A") is None


def test_salvar_cifra_transposta_atualiza_o_tom(logged_in_client, app, db):
    with app.app_context():
        _, ministerio, _ = _montar(logged_in_client)
        musica = _nova_musica(logged_in_client, ministerio.id)
        logged_in_client.post(f"/ministerio/repertorio/{musica.id}/louvor",
                              data={"cifra_louvor": "A        E", "tom": "A"})
        musica.reload()
        assert musica.tom == "A" and musica.cifra_louvor == "A        E"
        html = logged_in_client.get(f"/ministerio/repertorio/{musica.id}").data.decode("utf-8")
        assert "data-transpor" in html and "js/transpor.js" in html


def test_folha_de_cifras_sai_no_tom_do_dia(logged_in_client, app, db):
    with app.app_context():
        _, ministerio, escala = _montar(logged_in_client)
        musica = _nova_musica(logged_in_client, ministerio.id)  # tom G
        _preencher(logged_in_client, musica)
        logged_in_client.post(f"/escala/{escala.id}/repertorio/banco",
                              data={"banco-musica_id": musica.id, "banco-momento": "", "banco-tom": "A"})
        cifras = logged_in_client.get(f"/escala/{escala.id}/repertorio/cifras").data.decode("utf-8")
        assert "A        E\nGrande e o Senhor" in cifras
        assert "transposta do original em G" in cifras
        musica.reload()
        assert musica.cifra_louvor == CIFRA  # o banco continua no tom original
