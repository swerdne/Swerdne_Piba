"""Banco oficial x banco local (aprovacao pelo admin), pastas de musicas e
compartilhamento de repertorio -- ver app/escala/banco_musicas.py e a secao
"Pastas" de app/ministerio/routes.py."""
from app.auth.models import User
from app.escala.models import ItemRepertorio, Musica, PastaMusicas
from app.ministerio.models import UsuarioMinisterio
from app.notificacoes import Notificacao
from tests.conftest import sessao_isolada
from tests.test_escala import _criar_comunidade, _criar_ministerio, _criar_escala


def _igreja(cliente):
    comunidade = _criar_comunidade(cliente, "Igreja")
    louvor = _criar_ministerio(cliente, comunidade.id, nome="Louvor")
    kids = _criar_ministerio(cliente, comunidade.id, nome="Kids")
    return comunidade, louvor, kids


def _bruno():
    return User.objects(email="bruno@example.com").first()


def _bruno_lider(ministerio_id):
    UsuarioMinisterio(usuario_id=_bruno().id, ministerio_id=ministerio_id, papel="lider").save()


# --- Hierarquia: lider no banco local, admin aprova pro oficial ----------------

def test_lider_cadastra_no_banco_local_mas_nao_mexe_no_oficial(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade, louvor, _ = _igreja(logged_in_client)
        cid, lid = comunidade.id, louvor.id
        logged_in_client.post(f"/ministerio/musicas/{cid}/nova", data={"nome": "Oficial"})
        oficial_id = Musica.objects(nome="Oficial").first().id
        _bruno_lider(lid)

    with sessao_isolada(app):
        # Local: pode tudo.
        outro_logged_in_client.post(f"/ministerio/{lid}/repertorio/nova", data={"nome": "Do lider"})
        local = Musica.objects(nome="Do lider").first()
        assert local.oficial is False and local.ministerio_id == lid and local.comunidade_id == cid
        assert outro_logged_in_client.get(f"/ministerio/{lid}/repertorio/importar").status_code == 200
        # Oficial: nada direto.
        assert outro_logged_in_client.post(f"/ministerio/musicas/{cid}/nova", data={"nome": "X"}).status_code == 404
        assert outro_logged_in_client.get(f"/ministerio/musicas/{cid}/importar").status_code == 404
        assert outro_logged_in_client.post(f"/ministerio/repertorio/{oficial_id}/info", data={"nome": "Mudou"}).status_code == 404
        assert outro_logged_in_client.post(f"/ministerio/repertorio/{oficial_id}/excluir", data={}).status_code == 404
        assert Musica.objects(nome="X").count() == 0
        # Nem aprovar a propria musica.
        assert outro_logged_in_client.post(f"/ministerio/musicas/sugestao/{local.id}/aprovar", data={}).status_code == 404
        assert Musica.objects(id=local.id).first().oficial is False


def test_lider_nao_edita_banco_local_de_outro_ministerio(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        _, louvor, kids = _igreja(logged_in_client)
        lid, kid = louvor.id, kids.id
        _bruno_lider(lid)
    with sessao_isolada(app):
        assert outro_logged_in_client.post(f"/ministerio/{kid}/repertorio/nova", data={"nome": "X"}).status_code == 404
        assert outro_logged_in_client.get(f"/ministerio/{kid}/repertorio").status_code == 200  # ver pode


def test_admin_ve_sugestoes_e_aprova_pro_banco_oficial(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade, louvor, kids = _igreja(logged_in_client)
        cid, lid, kid = comunidade.id, louvor.id, kids.id
        _bruno_lider(lid)
    with sessao_isolada(app):
        outro_logged_in_client.post(f"/ministerio/{lid}/repertorio/nova", data={"nome": "Sugerida", "tom": "D"})
        musica_id = Musica.objects(nome="Sugerida").first().id

    with sessao_isolada(app):
        banco = logged_in_client.get(f"/ministerio/musicas/{cid}").data.decode("utf-8")
        assert "Sugestoes dos ministerios (1)" in banco and "Sugerida" in banco
        # Antes de aprovar, o Kids nao usa (e local do Louvor).
        escala_kids = _criar_escala(logged_in_client, kid, "Culto Kids")
        logged_in_client.post(f"/escala/{escala_kids.id}/repertorio/banco",
                              data={"banco-musica_id": musica_id, "banco-momento": "", "banco-tom": ""})
        assert ItemRepertorio.objects(escala_id=escala_kids.id).count() == 0

        logged_in_client.post(f"/ministerio/musicas/sugestao/{musica_id}/aprovar", data={})
        aprovada = Musica.objects(id=musica_id).first()
        assert aprovada.oficial is True and aprovada.ministerio_id == lid  # origem fica no historico
        assert "Sugestoes dos ministerios" not in logged_in_client.get(f"/ministerio/musicas/{cid}").data.decode("utf-8")
        # Agora e oficial: o Kids usa.
        logged_in_client.post(f"/escala/{escala_kids.id}/repertorio/banco",
                              data={"banco-musica_id": musica_id, "banco-momento": "", "banco-tom": ""})
        assert ItemRepertorio.objects(escala_id=escala_kids.id).count() == 1
        # O lider do Louvor e avisado.
        assert Notificacao.objects(usuario_id=_bruno().id, tipo="musica_aprovada").count() == 1


def test_admin_dispensa_sugestao_sem_tirar_do_banco_local(logged_in_client, app, db):
    with app.app_context():
        comunidade, louvor, _ = _igreja(logged_in_client)
        logged_in_client.post(f"/ministerio/{louvor.id}/repertorio/nova", data={"nome": "Nao agora"})
        musica = Musica.objects(nome="Nao agora").first()
        logged_in_client.post(f"/ministerio/musicas/sugestao/{musica.id}/dispensar", data={})
        assert "Sugestoes dos ministerios" not in logged_in_client.get(f"/ministerio/musicas/{comunidade.id}").data.decode("utf-8")
        assert "Nao agora" in logged_in_client.get(f"/ministerio/{louvor.id}/repertorio").data.decode("utf-8")
        assert Musica.objects(id=musica.id).first().oficial is False


def test_excluir_ministerio_leva_so_o_banco_local_dele(logged_in_client, app, db):
    with app.app_context():
        comunidade, louvor, _ = _igreja(logged_in_client)
        logged_in_client.post(f"/ministerio/{louvor.id}/repertorio/nova", data={"nome": "Local"})
        logged_in_client.post(f"/ministerio/musicas/{comunidade.id}/nova", data={"nome": "Oficial"})
        logged_in_client.post(f"/ministerio/{louvor.id}/excluir", data={}, follow_redirects=True)
        assert [m.nome for m in Musica.objects(comunidade_id=comunidade.id)] == ["Oficial"]


# --- Visualizacao Lista / Repertorios e criacao de repertorio ----------------------

def _criar_pasta(cliente, comunidade_id, nome, musicas, ministerio_id=None):
    """Cria um repertorio (PastaMusicas) -- por padrao no 1o ministerio (Louvor)."""
    from app.ministerio.models import Ministerio

    if ministerio_id is None:
        ministerio_id = Ministerio.objects(comunidade_id=comunidade_id).order_by("id").first().id
    return cliente.post(
        f"/ministerio/musicas/{comunidade_id}/pastas/nova",
        data={"nome": nome, "ministerio_id": ministerio_id, "musica_id": [str(m.id) for m in musicas]},
    )


def test_banco_tem_alternancia_lista_e_pastas(logged_in_client, app, db):
    with app.app_context():
        comunidade, _, _ = _igreja(logged_in_client)
        html = logged_in_client.get(f"/ministerio/musicas/{comunidade.id}").data.decode("utf-8")
        assert 'data-modo="lista"' in html and 'data-modo="repertorios"' in html
        assert 'data-modo-conteudo="repertorios"' in html and "Repertorios das escalas" in html


def test_cria_pasta_com_as_musicas_marcadas_na_ordem(logged_in_client, app, db):
    with app.app_context():
        comunidade, _, _ = _igreja(logged_in_client)
        for nome in ("A", "B", "C"):
            logged_in_client.post(f"/ministerio/musicas/{comunidade.id}/nova", data={"nome": nome, "tom": "G"})
        a, b, c = (Musica.objects(nome=n).first() for n in "ABC")
        resposta = _criar_pasta(logged_in_client, comunidade.id, "Culto 12/10", [c, a])
        pasta = PastaMusicas.objects(nome="Culto 12/10").first()
        assert resposta.headers["Location"].endswith(f"/ministerio/pastas/{pasta.id}")
        assert [i.nome for i in pasta.itens] == ["C", "A"] and pasta.itens[0].tom == "G"
        banco = logged_in_client.get(f"/ministerio/musicas/{comunidade.id}").data.decode("utf-8")
        assert f"/ministerio/pastas/{pasta.id}" in banco


def test_repertorio_dos_cultos_aparece_como_pasta_automatica(logged_in_client, app, db):
    with app.app_context():
        from datetime import date, timedelta
        comunidade, louvor, _ = _igreja(logged_in_client)
        escala = _criar_escala(logged_in_client, louvor.id, "Culto de Domingo",
                               data=(date.today() + timedelta(days=3)).isoformat())
        ItemRepertorio(escala_id=escala.id, nome_musica="Oceanos", tom="D", ordem=0).save()
        html = logged_in_client.get(f"/ministerio/musicas/{comunidade.id}").data.decode("utf-8")
        assert "Culto de Domingo" in html and "Oceanos" in html


def test_repertorio_da_escala_vira_pasta_com_tom_do_dia(logged_in_client, app, db):
    with app.app_context():
        comunidade, louvor, _ = _igreja(logged_in_client)
        logged_in_client.post(f"/ministerio/musicas/{comunidade.id}/nova", data={"nome": "Oceanos", "tom": "D"})
        musica = Musica.objects(nome="Oceanos").first()
        escala = _criar_escala(logged_in_client, louvor.id, "Culto")
        logged_in_client.post(f"/escala/{escala.id}/repertorio/banco",
                              data={"banco-musica_id": musica.id, "banco-momento": "Abertura", "banco-tom": "E"})
        resposta = logged_in_client.post(f"/escala/{escala.id}/repertorio/pasta", data={})
        pasta = PastaMusicas.objects(escala_id=escala.id).first()
        assert resposta.headers["Location"].endswith(f"/ministerio/pastas/{pasta.id}#compartilhar")
        item = pasta.itens[0]
        assert (item.musica_id, item.tom, item.momento) == (musica.id, "E", "Abertura")
        assert pasta.ministerio_id == louvor.id


def test_folha_da_pasta_sai_no_tom_guardado(logged_in_client, app, db):
    with app.app_context():
        comunidade, _, _ = _igreja(logged_in_client)
        logged_in_client.post(f"/ministerio/musicas/{comunidade.id}/nova", data={"nome": "Grande", "tom": "G"})
        musica = Musica.objects(nome="Grande").first()
        logged_in_client.post(f"/ministerio/repertorio/{musica.id}/louvor", data={"cifra_louvor": "G  D\nGrande e o Senhor", "tom": ""})
        _criar_pasta(logged_in_client, comunidade.id, "Domingo", [musica])
        pasta = PastaMusicas.objects(nome="Domingo").first()
        logged_in_client.post(f"/ministerio/pastas/{pasta.id}/remover/0", data={})
        logged_in_client.post(f"/ministerio/pastas/{pasta.id}/adicionar", data={"musica_id": musica.id, "tom": "A"})
        folha = logged_in_client.get(f"/ministerio/pastas/{pasta.id}/cifras").data.decode("utf-8")
        assert "A  E\nGrande e o Senhor" in folha and "Imprimir / PDF" in folha


# --- Compartilhamento com qualquer conta ---------------------------------------------

def test_compartilhar_com_pessoa_de_outra_comunidade(logged_in_client, outro_logged_in_client, app, db):
    """Bruno nao e de nenhuma comunidade da Ana: recebe a pasta, ve na tela
    inicial (como nova), abre, baixa -- mas nao edita nem ve o banco."""
    with sessao_isolada(app):
        comunidade, _, _ = _igreja(logged_in_client)
        cid = comunidade.id
        logged_in_client.post(f"/ministerio/musicas/{cid}/nova", data={"nome": "Oceanos", "tom": "D"})
        musica = Musica.objects(nome="Oceanos").first()
        _criar_pasta(logged_in_client, cid, "Culto Jovem", [musica])
        pasta_id = PastaMusicas.objects(nome="Culto Jovem").first().id

    with sessao_isolada(app):
        # Antes de receber: nada.
        assert outro_logged_in_client.get(f"/ministerio/pastas/{pasta_id}").status_code == 404

    with sessao_isolada(app):
        busca = logged_in_client.get(f"/ministerio/pastas/{pasta_id}/buscar-usuario?q=bru").get_json()
        assert busca == [{"id": _bruno().id, "label": "bruno (bruno@example.com)"}] or busca[0]["id"] == _bruno().id
        logged_in_client.post(f"/ministerio/pastas/{pasta_id}/compartilhar", data={"usuario_id": _bruno().id})

    with sessao_isolada(app):
        inicio = outro_logged_in_client.get("/dashboard").data.decode("utf-8")
        assert "Repertorios para voce" in inicio and "Culto Jovem" in inicio and "Novo" in inicio
        assert Notificacao.objects(usuario_id=_bruno().id, tipo="repertorio_compartilhado").count() == 1

        tela = outro_logged_in_client.get(f"/ministerio/pastas/{pasta_id}")
        assert tela.status_code == 200 and "Oceanos" in tela.data.decode("utf-8")
        assert outro_logged_in_client.get(f"/ministerio/pastas/{pasta_id}/cifras").status_code == 200
        assert outro_logged_in_client.get(f"/ministerio/pastas/{pasta_id}/projecao").status_code == 200
        # Abriu: deixa de ser "novo".
        assert PastaMusicas.objects(id=pasta_id).first().compartilhamento_de(_bruno().id).visto_em is not None
        assert ">Novo<" not in outro_logged_in_client.get("/dashboard").data.decode("utf-8")
        # So leitura: nao edita a pasta, nao compartilha adiante, nao ve o banco.
        assert outro_logged_in_client.post(f"/ministerio/pastas/{pasta_id}/renomear", data={"nome": "X"}).status_code == 404
        assert outro_logged_in_client.post(f"/ministerio/pastas/{pasta_id}/compartilhar", data={"usuario_id": 1}).status_code == 404
        assert outro_logged_in_client.get(f"/ministerio/musicas/{cid}").status_code == 404


def test_lider_do_ministerio_dono_edita_e_envia_lider_de_outro_so_ve(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade, louvor, kids = _igreja(logged_in_client)
        cid, lid, kid = comunidade.id, louvor.id, kids.id
        logged_in_client.post(f"/ministerio/musicas/{cid}/nova", data={"nome": "Oceanos"})
        _criar_pasta(logged_in_client, cid, "Manha", [Musica.objects(nome="Oceanos").first()], ministerio_id=lid)
        pasta_id = PastaMusicas.objects(nome="Manha").first().id
        _bruno_lider(kid)  # lider do Kids, nao do Louvor
        ana_id = User.objects(email="ana@example.com").first().id

    with sessao_isolada(app):
        html = outro_logged_in_client.get(f"/ministerio/pastas/{pasta_id}").data.decode("utf-8")
        assert "Manha" in html and 'id="compartilhar"' not in html
        assert outro_logged_in_client.post(f"/ministerio/pastas/{pasta_id}/compartilhar", data={"usuario_id": ana_id}).status_code == 404
        assert outro_logged_in_client.post(f"/ministerio/pastas/{pasta_id}/excluir", data={}).status_code == 404
        # Nao cria repertorio em ministerio que nao lidera.
        outro_logged_in_client.post(f"/ministerio/musicas/{cid}/pastas/nova",
                                    data={"nome": "Intruso", "ministerio_id": lid, "musica_id": [str(Musica.objects(nome="Oceanos").first().id)]})
        assert PastaMusicas.objects(nome="Intruso").count() == 0

    with sessao_isolada(app):
        _bruno_lider(lid)  # agora tambem lidera o Louvor
    with sessao_isolada(app):
        html = outro_logged_in_client.get(f"/ministerio/pastas/{pasta_id}").data.decode("utf-8")
        assert 'id="compartilhar"' in html and "Renomear, mudar de ministerio ou excluir" in html
        outro_logged_in_client.post(f"/ministerio/pastas/{pasta_id}/compartilhar", data={"usuario_id": ana_id})
        assert PastaMusicas.objects(id=pasta_id).first().compartilhamento_de(ana_id) is not None


def test_repertorios_da_manha_e_da_noite_agrupados_por_ministerio(logged_in_client, app, db):
    with app.app_context():
        comunidade, louvor, kids = _igreja(logged_in_client)
        logged_in_client.post(f"/ministerio/musicas/{comunidade.id}/nova", data={"nome": "Oceanos"})
        musica = Musica.objects(nome="Oceanos").first()
        _criar_pasta(logged_in_client, comunidade.id, "Manha", [musica], ministerio_id=louvor.id)
        _criar_pasta(logged_in_client, comunidade.id, "Noite", [musica], ministerio_id=louvor.id)
        _criar_pasta(logged_in_client, comunidade.id, "Kids domingo", [musica], ministerio_id=kids.id)
        assert {p.nome: p.ministerio_id for p in PastaMusicas.objects()} == {
            "Manha": louvor.id, "Noite": louvor.id, "Kids domingo": kids.id,
        }
        html = logged_in_client.get(f"/ministerio/musicas/{comunidade.id}").data.decode("utf-8")
        # Quadro de envio lista os repertorios por ministerio.
        assert "Enviar um repertorio" in html
        assert '<optgroup label="Louvor">' in html and '<optgroup label="Kids">' in html
        assert "Kids domingo" in html[html.index('<optgroup label="Kids">'):]


def test_enviar_pelo_quadro_do_banco_volta_pro_banco(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade, louvor, _ = _igreja(logged_in_client)
        cid = comunidade.id
        logged_in_client.post(f"/ministerio/musicas/{cid}/nova", data={"nome": "Oceanos"})
        _criar_pasta(logged_in_client, cid, "Noite", [Musica.objects(nome="Oceanos").first()], ministerio_id=louvor.id)
        pasta_id = PastaMusicas.objects(nome="Noite").first().id
        pessoas = logged_in_client.get(f"/ministerio/musicas/{cid}/buscar-pessoa?q=bruno").get_json()
        assert [p["id"] for p in pessoas] == [_bruno().id]
        resposta = logged_in_client.post(f"/ministerio/pastas/{pasta_id}/compartilhar",
                                         data={"usuario_id": _bruno().id, "voltar": f"/ministerio/musicas/{cid}#repertorios"})
        assert resposta.headers["Location"].endswith(f"/ministerio/musicas/{cid}#repertorios")
    with sessao_isolada(app):
        assert "Noite" in outro_logged_in_client.get("/dashboard").data.decode("utf-8")
        # Quem nao lidera nada na comunidade nao usa a busca.
        assert outro_logged_in_client.get(f"/ministerio/musicas/{cid}/buscar-pessoa?q=ana").status_code == 404


def test_selecao_guardada_e_quadradinho_com_area_de_clique(logged_in_client, app, db):
    with app.app_context():
        comunidade, _, _ = _igreja(logged_in_client)
        logged_in_client.post(f"/ministerio/musicas/{comunidade.id}/nova", data={"nome": "Oceanos"})
        html = logged_in_client.get(f"/ministerio/musicas/{comunidade.id}").data.decode("utf-8")
        assert "sessionStorage" in html and "selecao-banco:" in html
        assert '<label class="self-stretch flex items-center pl-4 pr-3 cursor-pointer shrink-0">' in html


def test_excluir_comunidade_apaga_as_pastas(logged_in_client, app, db):
    with app.app_context():
        comunidade, _, _ = _igreja(logged_in_client)
        logged_in_client.post(f"/ministerio/musicas/{comunidade.id}/nova", data={"nome": "Oceanos"})
        _criar_pasta(logged_in_client, comunidade.id, "P", [Musica.objects(nome="Oceanos").first()])
        logged_in_client.post(f"/comunidade/{comunidade.id}/excluir", data={}, follow_redirects=True)
        assert PastaMusicas.objects().count() == 0


# --- Repertorio pronto do banco aplicado na escala ---------------------------------

def test_escala_usa_repertorio_pronto_somando_ou_substituindo(logged_in_client, app, db):
    with app.app_context():
        comunidade, louvor, kids = _igreja(logged_in_client)
        for nome, tom in (("Oceanos", "D"), ("Grande", "G"), ("Avulsa antes", "C")):
            logged_in_client.post(f"/ministerio/musicas/{comunidade.id}/nova", data={"nome": nome, "tom": tom})
        oceanos, grande, antes = (Musica.objects(nome=n).first() for n in ("Oceanos", "Grande", "Avulsa antes"))
        _criar_pasta(logged_in_client, comunidade.id, "Manha", [oceanos, grande], ministerio_id=louvor.id)
        _criar_pasta(logged_in_client, comunidade.id, "Kids", [antes], ministerio_id=kids.id)
        manha = PastaMusicas.objects(nome="Manha").first()
        manha.itens[0].tom = "E"
        manha.itens[0].momento = "Abertura"
        manha.save()

        escala = _criar_escala(logged_in_client, louvor.id, "Culto da manha")
        html = logged_in_client.get(f"/escala/{escala.id}").data.decode("utf-8")
        assert "Usar um repertorio pronto" in html
        # Repertorios do proprio ministerio primeiro.
        assert html.index('<optgroup label="Louvor">') < html.index('<optgroup label="Kids">')

        logged_in_client.post(f"/escala/{escala.id}/repertorio/banco",
                              data={"banco-musica_id": antes.id, "banco-momento": "", "banco-tom": ""})
        logged_in_client.post(f"/escala/{escala.id}/repertorio/usar-repertorio", data={"repertorio_id": manha.id})
        itens = list(ItemRepertorio.objects(escala_id=escala.id).order_by("ordem"))
        assert [i.nome_musica for i in itens] == ["Avulsa antes", "Oceanos", "Grande"]  # somou no fim
        assert (itens[1].tom, itens[1].momento, itens[1].musica_id) == ("E", "Abertura", oceanos.id)

        logged_in_client.post(f"/escala/{escala.id}/repertorio/usar-repertorio",
                              data={"repertorio_id": manha.id, "substituir": "1"})
        assert [i.nome_musica for i in ItemRepertorio.objects(escala_id=escala.id).order_by("ordem")] == ["Oceanos", "Grande"]


def test_so_quem_gerencia_a_escala_usa_repertorio_pronto(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade, louvor, _ = _igreja(logged_in_client)
        logged_in_client.post(f"/ministerio/musicas/{comunidade.id}/nova", data={"nome": "Oceanos"})
        _criar_pasta(logged_in_client, comunidade.id, "Manha", [Musica.objects(nome="Oceanos").first()], ministerio_id=louvor.id)
        pasta_id = PastaMusicas.objects(nome="Manha").first().id
        escala_id = _criar_escala(logged_in_client, louvor.id, "Culto").id
    with sessao_isolada(app):
        resposta = outro_logged_in_client.post(f"/escala/{escala_id}/repertorio/usar-repertorio", data={"repertorio_id": pasta_id})
        assert resposta.status_code == 404
        assert ItemRepertorio.objects(escala_id=escala_id).count() == 0


# --- Apagar todas as musicas de um banco (duas confirmacoes) ------------------------

def test_apagar_todas_exige_a_frase_e_apaga_so_aquele_banco(logged_in_client, app, db):
    with app.app_context():
        comunidade, louvor, _ = _igreja(logged_in_client)
        cid = comunidade.id
        for nome in ("Oceanos", "Grande"):
            logged_in_client.post(f"/ministerio/musicas/{cid}/nova", data={"nome": nome, "tom": "D"})
        logged_in_client.post(f"/ministerio/{louvor.id}/repertorio/nova", data={"nome": "Local do Louvor"})
        oceanos = Musica.objects(nome="Oceanos").first()

        html = logged_in_client.get(f"/ministerio/musicas/{cid}").data.decode("utf-8")
        assert "Apagar todas as musicas" in html and "APAGAR TODAS" in html

        # Sem a frase (ou com ela errada): nada acontece.
        for frase in ("", "apagar", "APAGAR TUDO"):
            logged_in_client.post(f"/ministerio/musicas/{cid}/apagar-todas", data={"confirmacao": frase})
        assert Musica.objects(comunidade_id=cid).count() == 3

        # Uma escala e um repertorio usando a musica nao quebram.
        escala = _criar_escala(logged_in_client, louvor.id, "Culto")
        logged_in_client.post(f"/escala/{escala.id}/repertorio/banco",
                              data={"banco-musica_id": oceanos.id, "banco-momento": "", "banco-tom": "E"})
        _criar_pasta(logged_in_client, cid, "Manha", [oceanos], ministerio_id=louvor.id)

        logged_in_client.post(f"/ministerio/musicas/{cid}/apagar-todas", data={"confirmacao": "  apagar   todas "})
        assert [m.nome for m in Musica.objects(comunidade_id=cid)] == ["Local do Louvor"]  # banco local intacto
        item = ItemRepertorio.objects(escala_id=escala.id).first()
        assert (item.nome_musica, item.tom, item.musica_id) == ("Oceanos", "E", None)
        pasta = PastaMusicas.objects(nome="Manha").first()
        assert (pasta.itens[0].nome, pasta.itens[0].musica_id) == ("Oceanos", None)
        assert logged_in_client.get(f"/ministerio/pastas/{pasta.id}/cifras").status_code == 200


def test_apagar_todas_do_banco_local_nao_mexe_no_oficial(logged_in_client, app, db):
    with app.app_context():
        comunidade, louvor, kids = _igreja(logged_in_client)
        logged_in_client.post(f"/ministerio/musicas/{comunidade.id}/nova", data={"nome": "Oficial"})
        logged_in_client.post(f"/ministerio/{louvor.id}/repertorio/nova", data={"nome": "Do Louvor"})
        logged_in_client.post(f"/ministerio/{kids.id}/repertorio/nova", data={"nome": "Do Kids"})
        logged_in_client.post(f"/ministerio/{louvor.id}/repertorio/apagar-todas", data={"confirmacao": "APAGAR TODAS"})
        assert sorted(m.nome for m in Musica.objects()) == ["Do Kids", "Oficial"]


def test_so_quem_edita_o_banco_apaga_todas(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade, louvor, _ = _igreja(logged_in_client)
        cid, lid = comunidade.id, louvor.id
        logged_in_client.post(f"/ministerio/musicas/{cid}/nova", data={"nome": "Oficial"})
        _bruno_lider(lid)
    with sessao_isolada(app):
        # Lider ve o banco oficial mas nao tem o botao nem consegue apagar.
        assert "Apagar todas as musicas" not in outro_logged_in_client.get(f"/ministerio/musicas/{cid}").data.decode("utf-8")
        resposta = outro_logged_in_client.post(f"/ministerio/musicas/{cid}/apagar-todas", data={"confirmacao": "APAGAR TODAS"})
        assert resposta.status_code == 404
        assert Musica.objects(nome="Oficial").count() == 1
