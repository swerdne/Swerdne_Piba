"""Banco de musicas do ministerio (versao de projecao x versao do louvor) e
como ele chega nas escalas: folha de projecao, cifras e "Minha escala"."""
import re
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
    return Musica.objects(nome=nome).order_by("-id").first()  # banco e da comunidade (1 por teste)


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

        # Endereco antigo (por ministerio) leva pro banco da comunidade.
        html = logged_in_client.get(f"/ministerio/{ministerio.id}/repertorio", follow_redirects=True).data.decode("utf-8")
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


def test_escala_usa_banco_oficial_e_o_local_do_proprio_ministerio(logged_in_client, app, db):
    """Entra na escala: musica do banco OFICIAL da comunidade e do banco LOCAL
    do proprio ministerio. Nao entra: banco local de OUTRO ministerio nem
    musica de OUTRA comunidade."""
    with app.app_context():
        comunidade, ministerio, escala = _montar(logged_in_client)
        logged_in_client.post(f"/ministerio/musicas/{comunidade.id}/nova", data={"nome": "Oficial"})
        oficial = Musica.objects(nome="Oficial").first()
        local = _nova_musica(logged_in_client, ministerio.id, nome="Local")
        outro = _criar_ministerio(logged_in_client, comunidade.id, nome="Outro")
        local_de_outro = _nova_musica(logged_in_client, outro.id, nome="Local de outro")
        outra_comunidade = _criar_comunidade(logged_in_client, "Outra Comunidade")
        ministerio_de_fora = _criar_ministerio(logged_in_client, outra_comunidade.id, nome="De fora")
        de_fora = _nova_musica(logged_in_client, ministerio_de_fora.id, nome="De fora")
        assert oficial.oficial and local.oficial is False and local.ministerio_id == ministerio.id

        for musica in (oficial, local, local_de_outro, de_fora):
            logged_in_client.post(f"/escala/{escala.id}/repertorio/banco",
                                  data={"banco-musica_id": musica.id, "banco-momento": "", "banco-tom": ""})
        assert [i.musica_id for i in ItemRepertorio.objects(escala_id=escala.id)] == [oficial.id, local.id]


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
        # Formato do modelo de projecao: "1. [NOME] - Momento", Observacoes e Letra destacadas.
        assert "1. [GRANDE E O SENHOR] - Abertura" in projecao
        assert "Observa&ccedil;&otilde;es: TOM A" in projecao and "Letra:" in projecao
        assert 'class="proj-letra"' in projecao
        assert "TOM A" in projecao
        assert "[VERSO 1]" in projecao and "DIGNO DE LOUVOR" in projecao
        assert "G        D" not in projecao  # projecao nao leva cifra
        assert "OBSERVACOES GERAIS" in projecao and "Ministracao livre no fim" in projecao

        cifras = logged_in_client.get(f"/escala/{escala.id}/repertorio/cifras").data.decode("utf-8")
        # Tom do dia A, acordes destacados (cor forte) na folha.
        assert '<span class="acorde">A</span>        <span class="acorde">E</span>' in cifras
        assert "Grande e o Senhor" in cifras


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


def _inputs_tom_escondidos(html, acao):
    """Campos hidden name=tom dentro do form que posta em `acao`."""
    import re
    form = re.search(r'<form[^>]*action="' + re.escape(acao) + r'".*?</form>', html, re.S).group(0)
    return [c for c in re.findall(r'<input[^>]*>', form) if 'name="tom"' in c and 'type="hidden"' in c]


def test_form_da_cifra_tem_um_unico_campo_tom(logged_in_client, app, db):
    """Regressao: o hidden_tag() renderizava um 2o "tom" vazio que vinha
    antes do tom convertido -- o servidor lia o vazio e a cifra transposta
    sobrescrevia a original."""
    with app.app_context():
        _, ministerio, _ = _montar(logged_in_client)
        musica = _nova_musica(logged_in_client, ministerio.id)
        html = logged_in_client.get(f"/ministerio/repertorio/{musica.id}").data.decode("utf-8")
        campos = _inputs_tom_escondidos(html, f"/ministerio/repertorio/{musica.id}/louvor")
        assert len(campos) == 1 and 'value="G"' in campos[0]
        assert "data-transpor" in html and "js/transpor.js" in html


def test_salva_cifra_em_varios_tons_sem_mexer_na_original(logged_in_client, app, db):
    with app.app_context():
        _, ministerio, _ = _montar(logged_in_client)
        musica = _nova_musica(logged_in_client, ministerio.id)  # tom G
        _preencher(logged_in_client, musica)
        url = f"/ministerio/repertorio/{musica.id}/louvor"

        logged_in_client.post(url, data={"cifra_louvor": "D        A\nGrande e o Senhor", "tom": "D"})
        logged_in_client.post(url, data={"cifra_louvor": "A        E\nGrande e o Senhor", "tom": "A"})
        # salvar de novo em D atualiza a versao D, nao cria outra
        logged_in_client.post(url, data={"cifra_louvor": "D        A\nGrande e o Senhor (v2)", "tom": "D"})

        musica.reload()
        assert musica.tom == "G" and musica.cifra_louvor == CIFRA  # original intacta
        assert [(v.tom, v.cifra) for v in musica.versoes_cifra] == [
            ("D", "D        A\nGrande e o Senhor (v2)"),
            ("A", "A        E\nGrande e o Senhor"),
        ]
        assert musica.tons_salvos == [("G", True), ("D", False), ("A", False)]
        assert musica.cifra_no_tom("A").startswith("A        E")
        assert musica.cifra_no_tom("G") == CIFRA

        # alternar entre os tons salvos na aba Louvor
        html = logged_in_client.get(f"/ministerio/repertorio/{musica.id}?tom=A").data.decode("utf-8")
        assert "Versao no tom A" in html and "A        E" in html
        assert 'data-tom-salvo="G"' in html and 'data-tom-salvo="D"' in html
        html = logged_in_client.get(f"/ministerio/repertorio/{musica.id}").data.decode("utf-8")
        assert "Cifra original" in html and "G        D" in html

        # salvar no tom do cadastro continua editando a original
        logged_in_client.post(url, data={"cifra_louvor": "G nova", "tom": "G"})
        musica.reload()
        assert musica.cifra_louvor == "G nova" and len(musica.versoes_cifra) == 2


def test_remover_versao_de_tom(logged_in_client, app, db):
    with app.app_context():
        _, ministerio, _ = _montar(logged_in_client)
        musica = _nova_musica(logged_in_client, ministerio.id)
        _preencher(logged_in_client, musica)
        logged_in_client.post(f"/ministerio/repertorio/{musica.id}/louvor", data={"cifra_louvor": "D", "tom": "D"})
        logged_in_client.post(f"/ministerio/repertorio/{musica.id}/louvor/excluir-versao", data={"tom": "D"})
        musica.reload()
        assert list(musica.versoes_cifra) == [] and musica.cifra_louvor == CIFRA


def test_editar_louvor_nao_altera_a_projecao(logged_in_client, app, db):
    with app.app_context():
        _, ministerio, _ = _montar(logged_in_client)
        musica = _nova_musica(logged_in_client, ministerio.id)
        projecao = "[VERSO 1]\nGRANDE E O SENHOR\n\n[REFRAO]\nSANTO, SANTO\nAJUSTE MANUAL"
        logged_in_client.post(f"/ministerio/repertorio/{musica.id}/projecao", data={"letra_projecao": projecao})

        logged_in_client.post(f"/ministerio/repertorio/{musica.id}/louvor", data={"cifra_louvor": CIFRA, "tom": "G"})
        logged_in_client.post(f"/ministerio/repertorio/{musica.id}/louvor",
                              data={"cifra_louvor": "C        G\nOutra letra", "tom": "C"})
        logged_in_client.post(f"/ministerio/repertorio/{musica.id}/rascunho-projecao", data={})

        musica.reload()
        assert musica.letra_projecao == projecao


def test_rascunho_da_projecao_tira_acordes_sem_gravar(logged_in_client, app, db):
    with app.app_context():
        _, ministerio, _ = _montar(logged_in_client)
        musica = _nova_musica(logged_in_client, ministerio.id)
        _preencher(logged_in_client, musica)
        url = f"/ministerio/repertorio/{musica.id}/rascunho-projecao"

        da_cifra = logged_in_client.post(url, data={}).get_json()["texto"]
        assert da_cifra == "GRANDE E O SENHOR\nDIGNO DE LOUVOR"

        colado = "Intro: G D\n\nVerso 1:\nG      D\nGrande e o   Senhor\n\n[Refrão]\n[C]Santo, [G]santo\nSolo: Em C"
        limpo = logged_in_client.post(url, data={"texto": colado}).get_json()["texto"]
        assert limpo == "[VERSO 1]\nGRANDE E O SENHOR\n\n[REFRÃO]\nSANTO, SANTO"

        musica.reload()
        assert musica.letra_projecao == LETRA  # nada foi gravado


def test_aviso_quando_a_projecao_tem_acordes(logged_in_client, app, db):
    with app.app_context():
        _, ministerio, _ = _montar(logged_in_client)
        musica = _nova_musica(logged_in_client, ministerio.id)
        logged_in_client.post(f"/ministerio/repertorio/{musica.id}/projecao", data={"letra_projecao": CIFRA})
        html = logged_in_client.get(f"/ministerio/repertorio/{musica.id}").data.decode("utf-8")
        assert "data-aviso-acordes" in html


def test_folha_usa_a_versao_salva_no_tom_do_dia(logged_in_client, app, db):
    with app.app_context():
        _, ministerio, escala = _montar(logged_in_client)
        musica = _nova_musica(logged_in_client, ministerio.id)
        _preencher(logged_in_client, musica)
        logged_in_client.post(f"/ministerio/repertorio/{musica.id}/louvor",
                              data={"cifra_louvor": "A9       E\nVersao ajustada em A", "tom": "A"})
        logged_in_client.post(f"/escala/{escala.id}/repertorio/banco",
                              data={"banco-musica_id": musica.id, "banco-momento": "", "banco-tom": "A"})
        cifras = logged_in_client.get(f"/escala/{escala.id}/repertorio/cifras").data.decode("utf-8")
        assert "Versao ajustada em A" in cifras
        assert "transposta do original" not in cifras


def test_folha_de_cifras_sai_no_tom_do_dia(logged_in_client, app, db):
    with app.app_context():
        _, ministerio, escala = _montar(logged_in_client)
        musica = _nova_musica(logged_in_client, ministerio.id)  # tom G
        _preencher(logged_in_client, musica)
        logged_in_client.post(f"/escala/{escala.id}/repertorio/banco",
                              data={"banco-musica_id": musica.id, "banco-momento": "", "banco-tom": "A"})
        cifras = logged_in_client.get(f"/escala/{escala.id}/repertorio/cifras").data.decode("utf-8")
        assert "A        E\nGrande e o Senhor" in re.sub(r"<[^>]+>", "", cifras)  # sem as tags dos acordes coloridos
        assert "transposta do original em G" in cifras
        musica.reload()
        assert musica.cifra_louvor == CIFRA  # o banco continua no tom original


def test_formularios_da_musica_guardam_rascunho_por_tom(logged_in_client, app, db):
    with app.app_context():
        _, ministerio, _ = _montar(logged_in_client)
        musica = _nova_musica(logged_in_client, ministerio.id)
        logged_in_client.post(f"/ministerio/repertorio/{musica.id}/louvor", data={"cifra_louvor": "D", "tom": "D"})
        html = logged_in_client.get(f"/ministerio/repertorio/{musica.id}").data.decode("utf-8")
        for chave in ("projecao", "louvor-original", "info"):
            assert f'data-guardar-rascunho="musica-{musica.id}-{chave}"' in html
        assert "js/rascunho.js" in html and "data-rascunho-descartar" in html
        html = logged_in_client.get(f"/ministerio/repertorio/{musica.id}?tom=D").data.decode("utf-8")
        assert f'data-guardar-rascunho="musica-{musica.id}-louvor-D"' in html
