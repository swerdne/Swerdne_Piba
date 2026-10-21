"""Calendario com "Ver dias de...": escolher uma pessoa destaca os dias em
que ela esta escalada (ministerio e comunidade), com resumo embaixo."""
from datetime import date

from app.auth.models import User
from app.escala.models import Escala, Funcao, Membro
from tests.conftest import sessao_isolada
from tests.test_escala import _criar_comunidade, _criar_ministerio


def _mes_com_escalas(cliente):
    comunidade = _criar_comunidade(cliente, "Igreja")
    louvor = _criar_ministerio(cliente, comunidade.id, nome="Louvor")
    midia = _criar_ministerio(cliente, comunidade.id, nome="Midia")
    ana = Membro(comunidade_id=comunidade.id, nome="Ana Souza").save()
    bia = Membro(comunidade_id=comunidade.id, nome="Bia").save()
    davi = Membro(comunidade_id=comunidade.id, nome="Davi").save()  # sem escala no mes
    ano, mes = 2026, 11
    e1 = Escala(ministerio_id=louvor.id, nome="Culto Manha", departamento="Louvor", data=date(ano, mes, 8)).save()
    e2 = Escala(ministerio_id=louvor.id, nome="Culto Noite", departamento="Louvor", data=date(ano, mes, 15)).save()
    e3 = Escala(ministerio_id=midia.id, nome="Transmissao", departamento="Midia", data=date(ano, mes, 22)).save()
    Funcao(escala_id=e1.id, nome="Vocal", ordem=0, membro_id=ana.id, status="confirmado").save()
    Funcao(escala_id=e2.id, nome="Violao", ordem=0, membro_id=ana.id).save()
    Funcao(escala_id=e2.id, nome="Bateria", ordem=1, membro_id=bia.id).save()
    Funcao(escala_id=e3.id, nome="Camera", ordem=0, membro_id=ana.id).save()
    return comunidade, louvor, (ana, bia, davi), (e1, e2, e3)


def test_calendario_do_ministerio_destaca_os_dias_da_pessoa(logged_in_client, app, db):
    with app.app_context():
        _, louvor, (ana, bia, davi), _ = _mes_com_escalas(logged_in_client)
        url = f"/ministerio/{louvor.id}/calendario?ano=2026&mes=11"

        sem_filtro = logged_in_client.get(url).data.decode()
        assert "Ver dias de" in sem_filtro and "data-dia-da-pessoa" not in sem_filtro
        # quem esta escalado no mes vem primeiro; o resto em "Outras pessoas"
        assert sem_filtro.index("Escaladas neste mês") < sem_filtro.index("Ana Souza") < sem_filtro.index("Outras pessoas")
        assert sem_filtro.index("Outras pessoas") < sem_filtro.index(">Davi<")

        html = logged_in_client.get(url + f"&pessoa={ana.id}").data.decode()
        assert html.count("data-dia-da-pessoa") == 2  # dias 8 e 15 no Louvor (a Transmissao e da Midia)
        assert "tem escala em <span class=\"font-semibold\">2 dias</span>" in html
        assert "Culto Manha" in html and "Vocal" in html and "Confirmado" in html
        assert f"pessoa={ana.id}" in html.split("Mes anterior")[0].rsplit("href", 1)[1]  # seta leva a pessoa junto

        nada = logged_in_client.get(url + f"&pessoa={davi.id}").data.decode()
        assert "não tem escala em nenhum dia deste mês" in nada and "data-dia-da-pessoa" not in nada


def test_calendario_da_comunidade_junta_os_ministerios_e_tem_atalho_eu(logged_in_client, app, db):
    with app.app_context():
        comunidade, _, (ana, _, _), _ = _mes_com_escalas(logged_in_client)
        url = f"/comunidade/{comunidade.id}/calendario?ano=2026&mes=11"
        html = logged_in_client.get(url + f"&pessoa={ana.id}").data.decode()
        assert html.count("data-dia-da-pessoa") == 3 and "3 dias" in html  # Louvor + Midia

        assert 'name="pessoa" value=' not in logged_in_client.get(url).data.decode()  # sem cadastro com meu e-mail
        ana_conta = User.objects(username="ana").first()
        eu = Membro(comunidade_id=comunidade.id, nome="Ana Conta", email=ana_conta.email).save()
        assert f'name="pessoa" value="{eu.id}"' in logged_in_client.get(url).data.decode()


def test_pessoa_de_outra_comunidade_e_ignorada(logged_in_client, outro_logged_in_client, app, db):
    with app.app_context():
        _, louvor, _, _ = _mes_com_escalas(logged_in_client)
        with sessao_isolada(app):
            outra = _criar_comunidade(outro_logged_in_client, "Outra")
            estranho = Membro(comunidade_id=outra.id, nome="Estranho").save()
        html = logged_in_client.get(f"/ministerio/{louvor.id}/calendario?ano=2026&mes=11&pessoa={estranho.id}").data.decode()
        assert "Estranho" not in html and "data-dia-da-pessoa" not in html
