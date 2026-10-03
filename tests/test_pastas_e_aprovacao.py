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


# --- Visualizacao Lista / Pastas e criacao de pasta --------------------------------

def _criar_pasta(cliente, comunidade_id, nome, musicas):
    return cliente.post(
        f"/ministerio/musicas/{comunidade_id}/pastas/nova",
        data={"nome": nome, "musica_id": [str(m.id) for m in musicas]},
    )


def test_banco_tem_alternancia_lista_e_pastas(logged_in_client, app, db):
    with app.app_context():
        comunidade, _, _ = _igreja(logged_in_client)
        html = logged_in_client.get(f"/ministerio/musicas/{comunidade.id}").data.decode("utf-8")
        assert 'data-modo="lista"' in html and 'data-modo="pastas"' in html
        assert 'data-modo-conteudo="pastas"' in html and "Repertorios dos cultos" in html


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


def test_lider_compartilha_mas_so_dono_ou_admin_edita_a_pasta(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade, louvor, _ = _igreja(logged_in_client)
        logged_in_client.post(f"/ministerio/musicas/{comunidade.id}/nova", data={"nome": "Oceanos"})
        _criar_pasta(logged_in_client, comunidade.id, "Da Ana", [Musica.objects(nome="Oceanos").first()])
        pasta_id = PastaMusicas.objects(nome="Da Ana").first().id
        _bruno_lider(louvor.id)
        ana_id = User.objects(email="ana@example.com").first().id

    with sessao_isolada(app):
        html = outro_logged_in_client.get(f"/ministerio/pastas/{pasta_id}").data.decode("utf-8")
        assert 'id="compartilhar"' in html and "Renomear ou excluir" not in html
        assert outro_logged_in_client.post(f"/ministerio/pastas/{pasta_id}/excluir", data={}).status_code == 404
        outro_logged_in_client.post(f"/ministerio/pastas/{pasta_id}/compartilhar", data={"usuario_id": ana_id})
        assert PastaMusicas.objects(id=pasta_id).first().compartilhamento_de(ana_id) is not None


def test_excluir_comunidade_apaga_as_pastas(logged_in_client, app, db):
    with app.app_context():
        comunidade, _, _ = _igreja(logged_in_client)
        logged_in_client.post(f"/ministerio/musicas/{comunidade.id}/nova", data={"nome": "Oceanos"})
        _criar_pasta(logged_in_client, comunidade.id, "P", [Musica.objects(nome="Oceanos").first()])
        logged_in_client.post(f"/comunidade/{comunidade.id}/excluir", data={}, follow_redirects=True)
        assert PastaMusicas.objects().count() == 0
