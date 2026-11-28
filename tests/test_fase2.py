"""Fase 2 do relato do testador: excluir conta, confirmacao antes dos avisos
e pagina completa do evento."""
from datetime import date, datetime, timedelta, timezone
from unittest import mock

from app.auth.exclusao import NOME_ANONIMO, concluir_exclusoes_vencidas
from app.auth.models import User
from app.comunidade.models import Evento, UsuarioComunidade
from app.escala.models import Escala, Funcao, Membro
from app.ministerio.models import Ministerio
from app.notificacoes import Notificacao
from tests.conftest import sessao_isolada
from tests.test_escala import (
    _criar_comunidade, _criar_escala, _criar_membro, _criar_ministerio, _escalar, _funcao_por_nome,
)


def _hoje():
    return (datetime.now(timezone.utc) - timedelta(hours=3)).date()


def _montar_escala(cliente, email="carla@example.com", dias=3):
    comunidade = _criar_comunidade(cliente)
    ministerio = _criar_ministerio(cliente, comunidade.id)
    escala = _criar_escala(cliente, ministerio.id, "Culto", data=(_hoje() + timedelta(days=dias)).isoformat(), horario="19:00")
    membro = _criar_membro(cliente, comunidade.id, "Carla", email=email, telefone="(28) 99999-0000")
    funcao = _funcao_por_nome(escala, "Baixo")
    return comunidade, ministerio, escala, membro, funcao


# --- 1. Excluir conta -----------------------------------------------------------

def test_pagina_de_excluir_explica_e_pede_excluir(logged_in_client, app, db):
    with app.app_context():
        html = logged_in_client.get("/auth/conta/excluir").get_data(as_text=True)
        assert "desativada agora" in html and "15 dias" in html and "digite EXCLUIR" in html
        resposta = logged_in_client.post("/auth/conta/excluir", data={"confirmacao": "sim"})
        assert "Digite EXCLUIR (com todas as letras)" in resposta.get_data(as_text=True)
        assert User.objects(email="ana@example.com").first().exclusao_pedida_em is None


def test_perfil_tem_botao_excluir_conta(logged_in_client, app, db):
    with app.app_context():
        assert "/auth/conta/excluir" in logged_in_client.get("/dashboard").get_data(as_text=True)


def test_unico_admin_nao_exclui_sem_passar_a_administracao(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        html = logged_in_client.get("/auth/conta/excluir").get_data(as_text=True)
        assert "data-exclusao-bloqueada" in html and comunidade.nome in html
        logged_in_client.post("/auth/conta/excluir", data={"confirmacao": "EXCLUIR"})
        assert User.objects(email="ana@example.com").first().exclusao_pedida_em is None


def test_excluir_desativa_tira_das_escalas_futuras_e_avisa_lider(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        _, _, escala, membro, funcao = _montar_escala(logged_in_client, email="bruno@example.com")
        _escalar(logged_in_client, funcao.id, membro.id)
    with sessao_isolada(app):
        resposta = outro_logged_in_client.post("/auth/conta/excluir", data={"confirmacao": "excluir"}, follow_redirects=True)
        assert "Conta desativada" in resposta.get_data(as_text=True)
        bruno = User.objects(email="bruno@example.com").first()
        assert bruno.exclusao_pedida_em is not None and bruno.token_cancelar_exclusao
        assert Funcao.objects(id=funcao.id).first().membro_id is None
        ana = User.objects(email="ana@example.com").first()
        assert Notificacao.objects(usuario_id=ana.id, titulo__contains="saiu da escala").count() == 1
        # Saiu da conta: o Inicio pede login de novo.
        assert outro_logged_in_client.get("/dashboard").status_code == 302


def test_conta_em_exclusao_so_ve_a_tela_de_cancelar_e_pode_cancelar(logged_in_client, app, db):
    with app.app_context():
        User.objects(email="ana@example.com").update(set__exclusao_pedida_em=datetime.now(timezone.utc))
        resposta = logged_in_client.get("/dashboard")
        assert resposta.status_code == 302 and "/auth/conta/em-exclusao" in resposta.headers["Location"]
        assert "Conta marcada para exclusão" in logged_in_client.get("/auth/conta/em-exclusao").get_data(as_text=True)
        logged_in_client.post("/auth/conta/cancelar-exclusao")
        assert User.objects(email="ana@example.com").first().exclusao_pedida_em is None
        assert logged_in_client.get("/dashboard").status_code == 200


def test_link_do_email_cancela_sem_entrar(client, app, db):
    with app.app_context():
        User(email="eva@example.com", name="Eva", exclusao_pedida_em=datetime.now(timezone.utc),
             token_cancelar_exclusao="tok123").save()
        # Abrir o link nao cancela (leitor de e-mail abre links sozinho).
        assert "manter minha conta" in client.get("/auth/conta/cancelar-exclusao/tok123").get_data(as_text=True)
        assert User.objects(email="eva@example.com").first().exclusao_pedida_em is not None
        client.post("/auth/conta/cancelar-exclusao/tok123")
        eva = User.objects(email="eva@example.com").first()
        assert eva.exclusao_pedida_em is None and eva.token_cancelar_exclusao is None


def test_depois_de_15_dias_apaga_e_anonimiza_historico(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade, _, escala, membro, funcao = _montar_escala(logged_in_client, email="bruno@example.com", dias=-2)
        Funcao.objects(id=funcao.id).update(set__membro_id=membro.id)  # escala passada com o Bruno
        bruno = User.objects(email="bruno@example.com").first()
        UsuarioComunidade(usuario_id=bruno.id, comunidade_id=comunidade.id, papel="membro").save()
        Notificacao(usuario_id=bruno.id, titulo="x", mensagem="y").save()
        User.objects(id=bruno.id).update(set__exclusao_pedida_em=datetime.now(timezone.utc) - timedelta(days=14))
        assert concluir_exclusoes_vencidas() == 0  # ainda no prazo
        User.objects(id=bruno.id).update(set__exclusao_pedida_em=datetime.now(timezone.utc) - timedelta(days=16))
        assert concluir_exclusoes_vencidas() == 1

        assert User.objects(id=bruno.id).first() is None
        assert UsuarioComunidade.objects(usuario_id=bruno.id).count() == 0
        assert Notificacao.objects(usuario_id=bruno.id).count() == 0
        anonimo = Membro.objects(id=membro.id).first()
        assert anonimo.nome == NOME_ANONIMO and anonimo.email is None and anonimo.telefone is None
        assert Funcao.objects(id=funcao.id).first().membro_id == membro.id  # historico continua contando


# --- 2. Confirmacao antes de avisar -------------------------------------------------

def test_escalar_nao_avisa_sozinho_por_padrao(logged_in_client, app, db):
    with app.app_context():
        _, _, escala, membro, funcao = _montar_escala(logged_in_client)
        with mock.patch("app.escala.routes.enviar_notificacoes_da_escala") as enviar:
            html = _escalar(logged_in_client, funcao.id, membro.id).get_data(as_text=True)
        enviar.assert_not_called()
        assert "Aviso pendente" in html
        assert Funcao.objects(id=funcao.id).first().notificado_em is None


def test_ministerio_com_aviso_automatico_avisa_ao_escalar(logged_in_client, app, db):
    with app.app_context():
        _, ministerio, escala, membro, funcao = _montar_escala(logged_in_client)
        Ministerio.objects(id=ministerio.id).update(set__avisar_ao_escalar=True)
        with mock.patch("app.escala.routes.enviar_notificacoes_da_escala") as enviar:
            enviar.return_value = {"escalados": 1, "notificacoes_app": 0, "email_enviados": 1, "email_falhas": 0,
                                   "sms_enviados": 0, "sms_falhas": 0, "whatsapp_enviados": 0,
                                   "whatsapp_falhas": 0, "sem_contato": 0}
            _escalar(logged_in_client, funcao.id, membro.id)
        enviar.assert_called_once()


def test_opcao_avisar_automaticamente_no_ministerio(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        ministerio = _criar_ministerio(logged_in_client, comunidade.id)
        html = logged_in_client.get(f"/ministerio/{ministerio.id}/lembrete").get_data(as_text=True)
        assert "Avisar automaticamente ao escalar" in html
        assert not Ministerio.objects(id=ministerio.id).first().avisar_ao_escalar
        logged_in_client.post(f"/ministerio/{ministerio.id}/lembrete",
                              data={"dias_antes": "1", "horario": "", "avisar_ao_escalar": "y"})
        assert Ministerio.objects(id=ministerio.id).first().avisar_ao_escalar is True


def test_modal_mostra_quem_recebe_canal_e_previa(logged_in_client, app, db):
    with app.app_context():
        _, _, escala, membro, funcao = _montar_escala(logged_in_client)
        _escalar(logged_in_client, funcao.id, membro.id)
        html = logged_in_client.get(f"/escala/{escala.id}").get_data(as_text=True)
        assert "Enviar avisos (1 pendente)" in html and "data-aviso-pendente" in html
        modal = html[html.index('id="avisos-modal"'):][:4000]
        assert "Carla" in modal and "WhatsApp, SMS, e-mail" in modal and "Culto" in modal


def test_desfazer_cancela_o_envio(logged_in_client, app, db):
    with app.app_context():
        _, _, escala, membro, funcao = _montar_escala(logged_in_client)
        _escalar(logged_in_client, funcao.id, membro.id)
        app.config["AVISOS_DESFAZER_SEGUNDOS"] = 5
        tarefas = []
        with mock.patch("app.segundo_plano.em_segundo_plano", side_effect=lambda f, *a, **k: tarefas.append((f, a))):
            resposta = logged_in_client.post(f"/escala/{escala.id}/notificar")
        token = Escala.objects(id=escala.id).first().avisos_agendados_token
        assert token and f"desfazer={token}" in resposta.headers["Location"]
        html = logged_in_client.get(resposta.headers["Location"]).get_data(as_text=True)
        assert "data-desfazer-aviso" in html and "Desfazer" in html

        logged_in_client.post(f"/escala/{escala.id}/notificar/desfazer", data={"token": token})
        assert Escala.objects(id=escala.id).first().avisos_agendados_token is None
        funcao_envio, args = tarefas[0]
        with mock.patch("app.escala.routes.enviar_notificacoes_da_escala") as enviar, mock.patch("time.sleep"):
            funcao_envio(*args)
        enviar.assert_not_called()


def test_sem_desfazer_o_envio_sai_e_avisa_no_sino(logged_in_client, app, db):
    with app.app_context():
        _, _, escala, membro, funcao = _montar_escala(logged_in_client)
        _escalar(logged_in_client, funcao.id, membro.id)
        app.config["AVISOS_DESFAZER_SEGUNDOS"] = 5
        tarefas = []
        with mock.patch("app.segundo_plano.em_segundo_plano", side_effect=lambda f, *a, **k: tarefas.append((f, a))):
            logged_in_client.post(f"/escala/{escala.id}/notificar")
        funcao_envio, args = tarefas[0]
        with mock.patch("time.sleep"):
            funcao_envio(*args)
        assert Escala.objects(id=escala.id).first().avisos_agendados_token is None
        ana = User.objects(email="ana@example.com").first()
        assert Notificacao.objects(usuario_id=ana.id, titulo__startswith="Avisos").count() == 1


# --- 3. Pagina do evento -----------------------------------------------------------------

def _criar_evento(cliente, comunidade_id, **extra):
    dados = {"nome": "Congresso", "data": _hoje().isoformat(), "data_fim": "", "horario": "19:30",
             "local": "Rua A, 10 - Centro", "descricao": "Louvor e palavra"}
    dados.update(extra)
    cliente.post(f"/comunidade/{comunidade_id}/eventos", data=dados)
    return Evento.objects(comunidade_id=comunidade_id).order_by("-id").first()


def test_pagina_do_evento_completa(logged_in_client, app, db):
    with app.app_context():
        comunidade, _, escala, membro, funcao = _montar_escala(logged_in_client, dias=0)
        _escalar(logged_in_client, funcao.id, membro.id)
        evento = _criar_evento(logged_in_client, comunidade.id)
        html = logged_in_client.get(f"/comunidade/{comunidade.id}/eventos/{evento.id}").get_data(as_text=True)
        assert "Criado por ana" in html
        assert "https://www.google.com/maps/search/?api=1&amp;query=Rua%20A%2C%2010%20-%20Centro" in html
        assert "Adicionar ao calendário" in html and "Editar" in html and "Excluir" in html
        quem_vai = html[html.index("data-quem-vai"):]
        assert "Culto" in quem_vai and "Carla" in quem_vai


def test_evento_ics(logged_in_client, app, db):
    with app.app_context():
        comunidade = _criar_comunidade(logged_in_client)
        evento = _criar_evento(logged_in_client, comunidade.id, nome="Retiro, 2026", data_fim=(_hoje() + timedelta(days=2)).isoformat())
        resposta = logged_in_client.get(f"/comunidade/{comunidade.id}/eventos/{evento.id}/calendario.ics")
        texto = resposta.get_data(as_text=True)
        assert resposta.mimetype == "text/calendar"
        assert "BEGIN:VEVENT" in texto and "SUMMARY:Retiro\\, 2026" in texto
        assert f"DTSTART;TZID=America/Sao_Paulo:{_hoje():%Y%m%d}T193000" in texto
        assert "LOCATION:Rua A\\, 10 - Centro" in texto


def test_evento_novo_avisa_a_comunidade_com_link(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        comunidade = _criar_comunidade(logged_in_client)
        bruno = User.objects(email="bruno@example.com").first()
        UsuarioComunidade(usuario_id=bruno.id, comunidade_id=comunidade.id, papel="membro").save()
        evento = _criar_evento(logged_in_client, comunidade.id)
        aviso = Notificacao.objects(usuario_id=bruno.id, tipo="evento").first()
        assert aviso and aviso.link == f"/comunidade/{comunidade.id}/eventos/{evento.id}"
        ana = User.objects(email="ana@example.com").first()
        assert Notificacao.objects(usuario_id=ana.id, tipo="evento").count() == 0
    with sessao_isolada(app):
        html = outro_logged_in_client.get("/dashboard").get_data(as_text=True)
        assert f'href="/comunidade/{comunidade.id}/eventos/{evento.id}"' in html
