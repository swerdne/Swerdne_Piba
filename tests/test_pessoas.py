"""Tela "Pessoas" (comunidade.membros + ministerio.papeis): diretorio, contas
com papel, convites e link numa tela so -- ver app/comunidade/pessoas.py."""
from app.auth.models import User
from app.comunidade.models import UsuarioComunidade
from app.convites.models import Convite, STATUS_PENDENTE
from app.escala.models import Membro
from app.ministerio.models import UsuarioMinisterio
from tests.conftest import sessao_isolada
from tests.test_escala import _criar_comunidade, _criar_ministerio


def test_papeis_antigo_redireciona_e_detalhe_tem_um_item_so(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client, "Igreja")
        resposta = logged_in_client.get(f"/comunidade/{comunidade.id}/papeis")
        assert resposta.status_code == 302 and resposta.location.endswith(f"/comunidade/{comunidade.id}/membros")
        detalhe = logged_in_client.get(f"/comunidade/{comunidade.id}").data.decode()
        assert ">Pessoas<" in detalhe and f"/comunidade/{comunidade.id}/papeis" not in detalhe


def test_lista_junta_diretorio_e_contas_sem_duplicar(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade = _criar_comunidade(logged_in_client, "Igreja")
        cid = comunidade.id
        # Bruno: no diretorio E com conta na comunidade -> 1 linha so
        Membro(comunidade_id=cid, nome="Bruno Lima", email="Bruno@Example.com").save()
        UsuarioComunidade(usuario_id=User.objects(email="bruno@example.com").first().id,
                          comunidade_id=cid, papel="membro").save()
        Membro(comunidade_id=cid, nome="Carla Sem Conta").save()
        Convite(escopo_tipo="comunidade", escopo_id=cid, email="dani@example.com", papel="membro",
                convidado_por_id=1, token="tok-dani").save()
        Membro(comunidade_id=cid, nome="Dani", email="dani@example.com").save()

        html = logged_in_client.get(f"/comunidade/{cid}/membros").data.decode()
        assert html.count('data-busca-item="Bruno Lima') == 1
        assert "bruno@example.com" not in html.split('data-busca-item="Bruno Lima')[0].split("data-busca-lista")[-1]
        # a dona (ana) e admin e nao esta no diretorio: aparece com os dois selos
        linha_ana = html.split('data-busca-item="ana ')[1].split("data-menu-acoes")[0]
        assert "admin" in linha_ana and "fora-diretorio" in linha_ana and ">Admin<" in linha_ana
        linha_carla = html.split('data-busca-item="Carla Sem Conta')[1].split("data-menu-acoes")[0]
        assert "sem-acesso" in linha_carla and "Sem acesso ao app" in linha_carla
        linha_dani = html.split('data-busca-item="Dani')[1].split("data-menu-acoes")[0]
        assert "Convite enviado" in linha_dani
        assert "Aguardando (1)" in html  # o convite pendente
        assert "Convidar por link" in html and 'data-busca-filtro="sem-acesso"' in html


def test_adicionar_com_acesso_da_papel_ou_convite(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade = _criar_comunidade(logged_in_client, "Igreja")
        cid = comunidade.id
        url = f"/comunidade/{cid}/membros"
        # conta existente + caixa "Dar acesso" -> entra na hora e vai pro diretorio
        logged_in_client.post(url, data={"nome": "Bruno", "email": "bruno@example.com", "acesso": "sim"})
        bruno = User.objects(email="bruno@example.com").first()
        assert UsuarioComunidade.objects(usuario_id=bruno.id, comunidade_id=cid, papel="membro").count() == 1
        assert Membro.objects(comunidade_id=cid, email="bruno@example.com").count() == 1
        # sem conta -> convite
        logged_in_client.post(url, data={"nome": "Eva", "email": "eva@example.com", "acesso": "sim"})
        assert Convite.objects(escopo_id=cid, email="eva@example.com", status=STATUS_PENDENTE).count() == 1
        # sem a caixa (ex: vindo da Escala) -> so diretorio
        logged_in_client.post(url, data={"nome": "Fabi", "email": "fabi@example.com"})
        assert Membro.objects(comunidade_id=cid, nome="Fabi").count() == 1
        assert Convite.objects(email="fabi@example.com").count() == 0
        # mesmo e-mail de novo nao duplica no diretorio
        logged_in_client.post(url, data={"nome": "Bruno 2", "email": "BRUNO@example.com", "acesso": "sim"})
        assert Membro.objects(comunidade_id=cid, email__iexact="bruno@example.com").count() == 1


def test_adicionar_admin_e_nao_rebaixa_quem_ja_e_admin(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade = _criar_comunidade(logged_in_client, "Igreja")
        cid = comunidade.id
        url = f"/comunidade/{cid}/membros"
        logged_in_client.post(url, data={"nome": "Bruno", "email": "bruno@example.com", "acesso": "sim", "admin": "sim"})
        bruno = User.objects(email="bruno@example.com").first()
        assert UsuarioComunidade.objects(usuario_id=bruno.id, comunidade_id=cid).first().papel == "admin"
        # a propria ana (admin) cadastrada no diretorio com "Dar acesso": nada de convite pra rebaixar
        logged_in_client.post(url, data={"nome": "Ana", "email": "ana@example.com", "acesso": "sim"})
        assert Convite.objects(escopo_id=cid, email="ana@example.com").count() == 0


def test_ministerio_adiciona_do_diretorio_e_por_email_entra_no_diretorio(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade = _criar_comunidade(logged_in_client, "Igreja")
        louvor = _criar_ministerio(logged_in_client, comunidade.id, nome="Louvor")
        url = f"/ministerio/{louvor.id}/papeis"
        bruno_membro = Membro(comunidade_id=comunidade.id, nome="Bruno", email="bruno@example.com").save()
        Membro(comunidade_id=comunidade.id, nome="Sem Email").save()

        html = logged_in_client.get(url).data.decode()
        assert "Pessoas do ministério" in html and f'value="{bruno_membro.id}"' in html
        assert ">Sem Email<" not in html  # sem e-mail nao da pra dar papel

        # escolhendo do diretorio (sem digitar e-mail)
        logged_in_client.post(url, data={"membro_id": str(bruno_membro.id), "email": ""})
        bruno = User.objects(email="bruno@example.com").first()
        assert UsuarioMinisterio.objects(usuario_id=bruno.id, ministerio_id=louvor.id).count() == 1
        assert f'value="{bruno_membro.id}"' not in logged_in_client.get(url).data.decode()  # ja esta no ministerio

        # por e-mail de quem nao esta no diretorio -> entra no diretorio tambem
        logged_in_client.post(url, data={"email": "nova@example.com"})
        assert Membro.objects(comunidade_id=comunidade.id, email="nova@example.com").count() == 1
        assert Convite.objects(escopo_tipo="ministerio", escopo_id=louvor.id, email="nova@example.com").count() == 1
