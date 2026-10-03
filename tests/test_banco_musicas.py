"""Banco de musicas da COMUNIDADE (um so, pra todos os ministerios) -- ver
app/escala/banco_musicas.py. Ver: qualquer pessoa da comunidade. Editar:
so admin da comunidade."""
from app.escala.models import ItemRepertorio, Musica, VersaoCifra
from app.comunidade.models import UsuarioComunidade
from app.ministerio.models import UsuarioMinisterio
from app.auth.models import User
from tests.conftest import sessao_isolada
from tests.test_escala import _criar_comunidade, _criar_ministerio, _criar_escala


def _comunidade_com_dois_ministerios(cliente):
    comunidade = _criar_comunidade(cliente, "Igreja")
    louvor = _criar_ministerio(cliente, comunidade.id, nome="Louvor")
    kids = _criar_ministerio(cliente, comunidade.id, nome="Kids")
    return comunidade, louvor, kids


def test_bancos_antigos_por_ministerio_sao_juntados_sem_perder_nada(logged_in_client, app, db):
    with app.app_context():
        comunidade, louvor, kids = _comunidade_com_dois_ministerios(logged_in_client)
        # Escala antes das musicas: abrir a escala ja junta o banco (de proposito).
        escala = _criar_escala(logged_in_client, kids.id, "Culto Kids")
        # Musicas "antigas": so com ministerio_id (de antes do banco ser da comunidade).
        rica = Musica(ministerio_id=louvor.id, nome="Grande é o Senhor", tom="G",
                      cifra_louvor="G D\nGrande", tags=["louvor"],
                      versoes_cifra=[VersaoCifra(tom="A", cifra="A E\nGrande")])
        rica.save()
        pobre = Musica(ministerio_id=kids.id, nome="grande e o senhor ", artista="Adhemar",
                       letra_projecao="GRANDE", tags=["kids"], versoes_cifra=[VersaoCifra(tom="C", cifra="C G")])
        pobre.save()
        unica = Musica(ministerio_id=kids.id, nome="Só no Kids")
        unica.save()
        ItemRepertorio(escala_id=escala.id, musica_id=pobre.id, nome_musica=pobre.nome, ordem=0).save()

        html = logged_in_client.get(f"/ministerio/musicas/{comunidade.id}").data.decode("utf-8")
        assert "Só no Kids" in html

        musicas = list(Musica.objects(comunidade_id=comunidade.id))
        assert sorted(m.nome for m in musicas) == ["Grande é o Senhor", "Só no Kids"]
        ficou = Musica.objects(id=rica.id).first()  # a com mais conteudo fica
        assert ficou.artista == "Adhemar" and ficou.letra_projecao == "GRANDE"  # vazios preenchidos
        assert ficou.cifra_louvor == "G D\nGrande"  # o que ja tinha nao muda
        assert ficou.tags == ["louvor", "kids"]
        assert sorted(v.tom for v in ficou.versoes_cifra) == ["A", "C"]
        # A escala que usava a repetida aponta pra que ficou.
        assert ItemRepertorio.objects(escala_id=escala.id).first().musica_id == rica.id

        # Idempotente: rodar de novo nao muda nada.
        logged_in_client.get(f"/ministerio/musicas/{comunidade.id}")
        assert Musica.objects(comunidade_id=comunidade.id).count() == 2


def test_link_antigo_de_musica_juntada_abre_a_que_ficou(logged_in_client, app, db):
    with app.app_context():
        comunidade, louvor, kids = _comunidade_com_dois_ministerios(logged_in_client)
        fica = Musica(ministerio_id=louvor.id, nome="Oceanos", cifra_louvor="D A")
        fica.save()
        sai = Musica(ministerio_id=kids.id, nome="Oceanos")
        sai.save()
        resposta = logged_in_client.get(f"/ministerio/repertorio/{sai.id}")
        assert resposta.status_code == 302
        assert resposta.headers["Location"].endswith(f"/ministerio/repertorio/{fica.id}")


def test_kids_usa_musica_cadastrada_pelo_louvor(logged_in_client, app, db):
    with app.app_context():
        comunidade, louvor, kids = _comunidade_com_dois_ministerios(logged_in_client)
        logged_in_client.post(f"/ministerio/musicas/{comunidade.id}/nova", data={"nome": "Oceanos", "tom": "D"})
        musica = Musica.objects(comunidade_id=comunidade.id, nome="Oceanos").first()
        escala = _criar_escala(logged_in_client, kids.id, "Culto Kids", departamento="Louvor")
        html = logged_in_client.get(f"/escala/{escala.id}").data.decode("utf-8")
        assert f'<option value="{musica.id}">Oceanos</option>' in html


def _bruno_na_comunidade(comunidade_id, papel_comunidade=None, ministerio_lider_id=None):
    bruno = User.objects(email="bruno@example.com").first()
    if papel_comunidade:
        UsuarioComunidade(usuario_id=bruno.id, comunidade_id=comunidade_id, papel=papel_comunidade).save()
    if ministerio_lider_id:
        UsuarioMinisterio(usuario_id=bruno.id, ministerio_id=ministerio_lider_id, papel="lider").save()


def test_membro_ve_o_banco_mas_nao_edita(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade_id = _comunidade_com_dois_ministerios(logged_in_client)[0].id
        logged_in_client.post(f"/ministerio/musicas/{comunidade_id}/nova", data={"nome": "Oceanos"})
        musica_id = Musica.objects(nome="Oceanos").first().id
        _bruno_na_comunidade(comunidade_id, papel_comunidade="membro")

    with sessao_isolada(app):
        html = outro_logged_in_client.get(f"/ministerio/musicas/{comunidade_id}").data.decode("utf-8")
        assert "Oceanos" in html
        assert "Nova musica" not in html and "Importar varias cifras" not in html
        assert outro_logged_in_client.get(f"/ministerio/repertorio/{musica_id}").status_code == 200
        assert outro_logged_in_client.post(f"/ministerio/musicas/{comunidade_id}/nova", data={"nome": "X"}).status_code == 404
        assert outro_logged_in_client.post(f"/ministerio/repertorio/{musica_id}/excluir", data={}).status_code == 404
        assert outro_logged_in_client.get(f"/ministerio/musicas/{comunidade_id}/importar").status_code == 404


def test_lider_de_ministerio_usa_o_banco_mas_so_admin_edita(logged_in_client, outro_logged_in_client, app, db):
    """Lider (convidado so no ministerio, sem papel na comunidade) ve o banco
    e poe musica na escala dele, mas nao cadastra nem edita musica."""
    with sessao_isolada(app):
        comunidade, louvor, _ = _comunidade_com_dois_ministerios(logged_in_client)
        comunidade_id = comunidade.id
        logged_in_client.post(f"/ministerio/musicas/{comunidade_id}/nova", data={"nome": "Oceanos"})
        musica_id = Musica.objects(nome="Oceanos").first().id
        escala_id = _criar_escala(logged_in_client, louvor.id, "Culto").id
        _bruno_na_comunidade(comunidade_id, ministerio_lider_id=louvor.id)

    with sessao_isolada(app):
        assert outro_logged_in_client.get(f"/ministerio/musicas/{comunidade_id}").status_code == 200
        outro_logged_in_client.post(f"/escala/{escala_id}/repertorio/banco",
                                    data={"banco-musica_id": musica_id, "banco-momento": "", "banco-tom": ""})
        assert ItemRepertorio.objects(escala_id=escala_id, musica_id=musica_id).count() == 1
        assert outro_logged_in_client.post(f"/ministerio/repertorio/{musica_id}/info", data={"nome": "Mudou"}).status_code == 404
        assert Musica.objects(id=musica_id).first().nome == "Oceanos"


def test_quem_nao_e_da_comunidade_nao_ve_o_banco(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade_id = _comunidade_com_dois_ministerios(logged_in_client)[0].id
    with sessao_isolada(app):
        assert outro_logged_in_client.get(f"/ministerio/musicas/{comunidade_id}").status_code == 404


def test_telas_da_comunidade_tem_atalho_pro_banco(logged_in_client, app, db):
    with app.app_context():
        comunidade = _comunidade_com_dois_ministerios(logged_in_client)[0]
        url = f"/ministerio/musicas/{comunidade.id}"
        assert url in logged_in_client.get(f"/comunidade/{comunidade.id}").data.decode("utf-8")
        assert url in logged_in_client.get(f"/comunidade/{comunidade.id}/escalados").data.decode("utf-8")


def test_excluir_ministerio_nao_apaga_musicas_do_banco(logged_in_client, app, db):
    """O banco e da comunidade: musica cadastrada a partir do Louvor (ate a
    antiga, ainda nao juntada) continua la quando o Louvor e excluido."""
    with app.app_context():
        comunidade, louvor, kids = _comunidade_com_dois_ministerios(logged_in_client)
        nova = Musica(comunidade_id=comunidade.id, ministerio_id=louvor.id, nome="Nova")
        nova.save()
        antiga = Musica(ministerio_id=louvor.id, nome="Antiga")  # ainda sem comunidade_id
        antiga.save()

        logged_in_client.post(f"/ministerio/{louvor.id}/excluir", data={}, follow_redirects=True)

        restantes = {m.nome: m for m in Musica.objects(comunidade_id=comunidade.id)}
        assert set(restantes) == {"Nova", "Antiga"}


def test_excluir_comunidade_apaga_o_banco_dela(logged_in_client, app, db):
    with app.app_context():
        comunidade, louvor, _ = _comunidade_com_dois_ministerios(logged_in_client)
        Musica(comunidade_id=comunidade.id, nome="Nova").save()
        Musica(ministerio_id=louvor.id, nome="Antiga").save()
        outra = _criar_comunidade(logged_in_client, "Outra")
        Musica(comunidade_id=outra.id, nome="De outra comunidade").save()

        logged_in_client.post(f"/comunidade/{comunidade.id}/excluir", data={}, follow_redirects=True)

        assert [m.nome for m in Musica.objects()] == ["De outra comunidade"]
