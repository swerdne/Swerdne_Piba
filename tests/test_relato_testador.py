"""Fase 1 do relato do testador: um teste (ou mais) por bug corrigido."""
import io
import os
import re
import subprocess
import sys
from datetime import date, timedelta

from app.comunidade.models import Evento
from app.escala.models import Funcao
from app.main.routes import _responder_mock
from app.plantao.models import TurnoPlantao
from tests.conftest import sessao_isolada
from tests.test_checkin import PERTO, _checkin, _montar
from tests.test_checkin_culto import _checkin_culto, _hoje_e_culto
from tests.test_plantao import _criar_escala_com_dois_escalados, _payload_turno
from tests.test_escala import _criar_comunidade, _criar_ministerio

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# --- 1. Android antigo (Chrome 80-87) --------------------------------------------

def _css():
    return io.open(os.path.join(RAIZ, "app", "static", "css", "style.css"), encoding="utf-8").read()


def test_css_sem_layer_e_com_reservas_para_navegador_antigo():
    css = _css()
    # @layer (Chrome 99+) fazia o Chrome 83 descartar o CSS inteiro.
    assert "@layer" not in css
    # Valores iniciais das variaveis do Tailwind (no lugar do @property).
    assert re.search(r"@supports not selector\(:where\(a\)\)\{\s*\*[^{]*\{[^}]*--tw-shadow:0 0 #0000", css)
    # gap em flexbox (Chrome 84+): margens quando o navegador nao tem.
    assert ".sem-gap-flex .flex.gap-2:not(.flex-col)>*+*" in css
    # translate solto (Chrome 104+): transform equivalente.
    assert "@supports not (translate:0)" in css
    # Cores oklch com rgb de reserva antes.
    assert css.count("oklch(") <= css.count("rgb(")


def test_base_detecta_falta_de_gap_em_flex(client):
    html = client.get("/auth/login").get_data(as_text=True)
    assert "sem-gap-flex" in html and 'CSS.supports("aspect-ratio", "1")' in html


def test_icones_svg_tem_tamanho_em_atributo():
    """Sem CSS, um <svg> sem width/height ocupa a largura toda da tela."""
    sem_tamanho = []
    for pasta, _, arquivos in os.walk(os.path.join(RAIZ, "app", "templates")):
        for nome in arquivos:
            if not nome.endswith(".html"):
                continue
            texto = io.open(os.path.join(pasta, nome), encoding="utf-8").read()
            for tag in re.findall(r"<svg\b[^>]*>", texto):
                if not re.search(r"(?<![-\w])width=", tag) and "w-full" not in tag:
                    sem_tamanho.append(f"{nome}: {tag[:80]}")
    assert sem_tamanho == []


def test_icone_svg_do_menu_sai_com_tamanho(logged_in_client):
    html = logged_in_client.get("/dashboard").get_data(as_text=True)
    assert re.search(r'<svg width="20" height="20" class="w-5 h-5 shrink-0"', html)


# --- 2. Rodizio ativo aparecia como "Nenhum turno de rodizio criado" ---------------

def test_rodizio_criado_da_escala_aparece_na_secao_do_ministerio(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        escala, _, _ = _criar_escala_com_dois_escalados(logged_in_client, ministerio.id, "Culto Domingo")
        logged_in_client.post(
            f"/plantao/ministerio/{ministerio.id}/nova?escala_id={escala.id}",
            data=_payload_turno(nome="Culto Domingo", departamento="Louvor",
                                data_inicio=(date.today() + timedelta(days=1)).isoformat()),
            follow_redirects=True,
        )
        turno = TurnoPlantao.objects(nome="Culto Domingo", ministerio_id=ministerio.id).first()
        html = logged_in_client.get(f"/ministerio/{ministerio.id}").get_data(as_text=True)
        assert "Nenhum turno de rodízio criado" not in html
        assert f'data-turno-vinculado="{turno.id}"' in html
        assert "rodízio da escala Culto Domingo" in html
        # Continua sem link solto pro turno (a entrada e a propria escala).
        assert f'href="/plantao/{turno.id}"' not in html


def test_ministerio_sem_rodizio_mostra_aviso(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        html = logged_in_client.get(f"/ministerio/{ministerio.id}").get_data(as_text=True)
        assert "Nenhum turno de rodízio criado ainda neste ministério." in html


# --- 3. Check-in confirmado e funcao em "Nao notificado" ------------------------------

def test_checkin_da_escala_devolve_o_status_novo_para_a_tela(logged_in_client, app, db):
    with app.app_context():
        _, _, escala, funcao = _montar(logged_in_client)
        dados = _checkin(logged_in_client, escala, PERTO).get_json()
        assert dados["ok"] is True
        assert dados["funcoes"] == [{"id": funcao.id, "status": "presente", "rotulo": "Presente",
                                     "cor": dados["funcoes"][0]["cor"]}]


def test_checkin_ja_feito_conserta_status_atrasado(logged_in_client, app, db):
    with app.app_context():
        _, _, escala, funcao = _montar(logged_in_client)
        _checkin(logged_in_client, escala, PERTO)
        Funcao.objects(id=funcao.id).update(set__status="nao_notificado")
        dados = _checkin(logged_in_client, escala, PERTO).get_json()
        assert dados["ja_feito"] is True and dados["funcoes"][0]["status"] == "presente"
        assert Funcao.objects(id=funcao.id).first().status == "presente"


def test_checkin_no_culto_marca_presente_na_escala_do_dia(logged_in_client, app, db):
    with app.app_context():
        _, ministerio, _, funcao = _montar(logged_in_client)
        _hoje_e_culto(logged_in_client, ministerio)
        dados = _checkin_culto(logged_in_client, ministerio, PERTO).get_json()
        assert dados["ok"] is True and "também ficou como Presente" in dados["mensagem"]
        funcao = Funcao.objects(id=funcao.id).first()
        assert funcao.status == "presente" and funcao.checkin_em is not None


def test_tela_atualiza_status_sem_recarregar():
    js = io.open(os.path.join(RAIZ, "app", "static", "js", "checkin.js"), encoding="utf-8").read()
    assert "atualizarStatusNaTela(dados.funcoes)" in js


# --- 4. Assistente: "Escalas e rodizio" respondia o tutorial ---------------------------

def test_assistente_escalas_e_rodizio_nao_cai_no_tutorial():
    for pergunta in ("Escalas e rodízio", "Como funcionam escalas e rodizio?", "escalas e RODÍZIO"):
        resposta = _responder_mock(pergunta, [])
        assert "Rodízio" in resposta and "tutorial" not in resposta.lower()


def test_assistente_perguntas_reais():
    assert "fila de equipes" in _responder_mock("como funciona o rodizio", [])
    assert "fila de equipes" in _responder_mock("como funciona o rodízio?", [])
    assert "Nova escala" in _responder_mock("criar escala", [])
    assert "tutorial guiado" in _responder_mock("tutorial", [])
    assert "tutorial guiado" in _responder_mock("Como funciona?", [])
    assert "segurança" in _responder_mock("Meus dados estao seguros?", [])


# --- 5. Eventos: editar e ver no calendario ------------------------------------------

def _criar_evento(cliente, comunidade_id, **extra):
    dados = {"nome": "Congresso", "data": date.today().isoformat(), "data_fim": "", "horario": "19:30",
             "local": "Templo", "descricao": "Três dias"}
    dados.update(extra)
    cliente.post(f"/comunidade/{comunidade_id}/eventos", data=dados)
    return Evento.objects(comunidade_id=comunidade_id).order_by("-id").first()


def test_admin_edita_evento_com_formulario_preenchido(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        evento = _criar_evento(logged_in_client, comunidade.id)
        tela = logged_in_client.get(f"/comunidade/{comunidade.id}/eventos/{evento.id}/editar").get_data(as_text=True)
        assert 'value="Congresso"' in tela and "Salvar" in tela

        logged_in_client.post(f"/comunidade/{comunidade.id}/eventos/{evento.id}/editar", data={
            "nome": "Congresso de Louvor", "data": evento.data.isoformat(), "data_fim": "",
            "horario": "20:00", "local": "Ginásio", "descricao": "",
        })
        evento = Evento.objects(id=evento.id).first()
        assert (evento.nome, evento.local, evento.horario.strftime("%H:%M")) == ("Congresso de Louvor", "Ginásio", "20:00")


def test_evento_editar_valida_datas(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        evento = _criar_evento(logged_in_client, comunidade.id)
        resposta = logged_in_client.post(f"/comunidade/{comunidade.id}/eventos/{evento.id}/editar", data={
            "nome": "Congresso", "data": "2026-12-10", "data_fim": "2026-12-01", "horario": "", "local": "", "descricao": "",
        })
        assert "A data de término não pode ser antes da data de início." in resposta.get_data(as_text=True)
        assert Evento.objects(id=evento.id).first().data == evento.data


def test_membro_comum_nao_edita_evento(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade = _criar_comunidade(logged_in_client)
        evento = _criar_evento(logged_in_client, comunidade.id)
    with sessao_isolada(app):
        assert outro_logged_in_client.get(f"/comunidade/{comunidade.id}/eventos/{evento.id}/editar").status_code == 404


def test_evento_aparece_no_calendario_da_comunidade_e_do_ministerio(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        evento = _criar_evento(logged_in_client, comunidade.id)
        link = f"/comunidade/{comunidade.id}/eventos/{evento.id}"
        for url in (f"/comunidade/{comunidade.id}/calendario", f"/ministerio/{ministerio.id}/calendario"):
            html = logged_in_client.get(url).get_data(as_text=True)
            assert link in html and "Evento: Congresso" in html
        mini = logged_in_client.get(f"/ministerio/{ministerio.id}").get_data(as_text=True)
        assert "Evento: Congresso" in mini


def test_evento_de_varios_dias_aparece_em_cada_dia(app):
    from app.comunidade.models import eventos_por_dia

    hoje = date.today()
    Evento(comunidade_id=99, nome="Retiro", data=hoje, data_fim=hoje + timedelta(days=2)).save()
    dias = eventos_por_dia(99, hoje - timedelta(days=1), hoje + timedelta(days=5))
    assert sorted(dias) == [hoje, hoje + timedelta(days=1), hoje + timedelta(days=2)]


def test_pagina_do_evento(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        evento = _criar_evento(logged_in_client, comunidade.id)
        html = logged_in_client.get(f"/comunidade/{comunidade.id}/eventos/{evento.id}").get_data(as_text=True)
        assert "Congresso" in html and "Templo" in html and "Editar" in html and "Excluir" in html


# --- 6. Textos em ingles e sem acento ----------------------------------------------------

def test_erros_de_formulario_em_portugues(client):
    html = client.post("/auth/login", data={"email": "nao-e-email", "password": ""}).get_data(as_text=True)
    assert "This field is required" not in html and "Invalid email" not in html
    assert "Campo obrigatório." in html


def test_mensagens_do_navegador_em_portugues():
    js = io.open(os.path.join(RAIZ, "app", "static", "js", "main.js"), encoding="utf-8").read()
    assert "setCustomValidity" in js and "Preencha este campo." in js


def test_nenhum_texto_conhecido_sem_acento():
    """scripts/acentuar_textos.py --checar: falha se aparecer de novo texto
    visivel com palavra comum sem acento (ex.: "rodizio", "funcao")."""
    resultado = subprocess.run([sys.executable, os.path.join(RAIZ, "scripts", "acentuar_textos.py"), "--checar"],
                               capture_output=True, text=True, encoding="utf-8")
    assert resultado.returncode == 0, resultado.stdout


def test_status_com_acento():
    from app.escala.models import STATUS_LABELS

    assert STATUS_LABELS["nao_notificado"] == "Não notificado"


# --- 7. Mapa do check-in ------------------------------------------------------------------

def test_mapa_do_checkin_limita_zoom_e_tem_reserva_em_texto(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        html = logged_in_client.get(f"/ministerio/{ministerio.id}/local-checkin").get_data(as_text=True)
        assert "https://tile.openstreetmap.org/{z}/{x}/{y}.png" in html and "{s}.tile" not in html
        assert "maxZoom: 19" in html and "maxNativeZoom: 19" in html
        assert "L.Icon.Default.imagePath" in html
        assert "data-mapa-falhou" in html and "tileerror" in html
        assert "colaboradores do OpenStreetMap" in html
