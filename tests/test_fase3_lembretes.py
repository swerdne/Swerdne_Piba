"""Fase 3, item 2: lembretes 1 dia e 1 hora antes, pelos canais que cada
pessoa escolhe no Perfil (o de 16h virou o de 1 hora)."""
from datetime import timedelta

import pytest

from app.auth.models import User
from app.escala.agendador import _verificar_e_notificar
from app.escala.models import Escala, Membro, criar_escala_com_funcoes_padrao
from app.escala.routes import enviar_notificacoes_da_escala
from app.fuso import agora_brasilia
from app.notificacoes import Notificacao
from tests.test_agendador import _criar_ministerio_teste, _escalar_membro


@pytest.fixture
def envios(monkeypatch):
    """Registra o que sairia por canal, sem mandar nada."""
    feitos = {"whatsapp": [], "sms": [], "email": []}
    monkeypatch.setattr("app.escala.routes.enviar_whatsapp_template",
                        lambda destinatario, nome_template, parametros, **k: feitos["whatsapp"].append(destinatario))
    monkeypatch.setattr("app.escala.routes.enviar_sms", lambda destinatario, corpo: feitos["sms"].append(destinatario))
    monkeypatch.setattr("app.escala.routes.enviar_email",
                        lambda destinatario, assunto, corpo: feitos["email"].append((destinatario, assunto, corpo)))
    return feitos


def _escala_com_ana(horas=24, **preferencias):
    """Ana (conta logada do teste) escalada, com telefone e e-mail."""
    ana = User.objects(username="ana").first()
    for campo, valor in preferencias.items():
        setattr(ana, campo, valor)
    ana.save()
    ministerio = _criar_ministerio_teste(ana.id)
    quando = (agora_brasilia() + timedelta(hours=horas, minutes=2)).replace(microsecond=0)
    escala = criar_escala_com_funcoes_padrao(ministerio_id=ministerio.id, nome="Culto", departamento="Louvor",
                                             data=quando.date(), horario=quando.time())
    funcao = _escalar_membro(escala, "Baixo", nome_membro="Ana", email="ana@example.com")
    Membro.objects(id=funcao.membro_id).update(set__telefone="(11) 98765-4321")
    return Escala.objects(id=escala.id).first(), ana


def test_padrao_principal_por_tudo_e_1h_sem_whatsapp(logged_in_client, app, db, envios):
    escala, ana = _escala_com_ana()
    enviar_notificacoes_da_escala(escala, lembrete="principal")
    assert len(envios["whatsapp"]) == 1 and len(envios["sms"]) == 1 and len(envios["email"]) == 1

    enviar_notificacoes_da_escala(escala, lembrete="1h")
    assert len(envios["whatsapp"]) == 1 and len(envios["sms"]) == 1  # nada novo nos pagos
    assert len(envios["email"]) == 2
    _, assunto, corpo = envios["email"][-1]
    assert assunto.startswith("Começa em 1 hora: Culto") and corpo.startswith("Lembrete: começa em 1 hora")
    assert Notificacao.objects(usuario_id=ana.id, titulo="Começa em 1 hora: Culto").count() == 1


def test_sem_whatsapp_no_perfil(logged_in_client, app, db, envios):
    escala, _ = _escala_com_ana(lembrete_whatsapp=False)
    enviar_notificacoes_da_escala(escala, lembrete="principal")
    assert envios["whatsapp"] == [] and envios["sms"] == [] and len(envios["email"]) == 1


def test_whatsapp_tambem_no_de_1_hora(logged_in_client, app, db, envios):
    escala, _ = _escala_com_ana(lembrete_1h_whatsapp=True)
    enviar_notificacoes_da_escala(escala, lembrete="1h")
    assert len(envios["whatsapp"]) == 1


def test_sem_email_no_perfil_mas_sino_continua(logged_in_client, app, db, envios):
    escala, ana = _escala_com_ana(lembrete_email=False)
    resultado = enviar_notificacoes_da_escala(escala, lembrete="principal")
    assert envios["email"] == [] and resultado["email_falhas"] == 0
    assert Notificacao.objects(usuario_id=ana.id, titulo__startswith="Lembrete:").count() == 1


def test_aviso_manual_nao_depende_das_preferencias(logged_in_client, app, db, envios):
    escala, _ = _escala_com_ana(lembrete_whatsapp=False, lembrete_email=False)
    enviar_notificacoes_da_escala(escala)  # "Enviar avisos" do lider
    assert len(envios["whatsapp"]) == 1 and len(envios["email"]) == 1


def test_agendador_manda_o_de_1_hora_uma_vez(logged_in_client, app, db, envios):
    escala, ana = _escala_com_ana(horas=1)
    _verificar_e_notificar(app)
    marcado = Escala.objects(id=escala.id).first().notificado_1h_em
    assert marcado is not None and len(envios["email"]) == 1 and envios["whatsapp"] == []
    _verificar_e_notificar(app)
    assert Escala.objects(id=escala.id).first().notificado_1h_em == marcado and len(envios["email"]) == 1


def test_perfil_salva_lembretes(logged_in_client, app, db):
    with app.app_context():
        html = logged_in_client.get("/dashboard").get_data(as_text=True)
        assert "Lembretes das escalas" in html and "data-form-lembretes" in html
        logged_in_client.post("/perfil/lembretes", data={"lembrete_email": "y", "lembrete_1h_whatsapp": "y"})
        ana = User.objects(username="ana").first()
        # Sem WhatsApp ligado, o "tambem no de 1 hora" nao fica ligado sozinho.
        assert (ana.lembrete_whatsapp, ana.lembrete_email, ana.lembrete_1h_whatsapp) == (False, True, False)
        logged_in_client.post("/perfil/lembretes", data={"lembrete_whatsapp": "y", "lembrete_1h_whatsapp": "y"})
        ana = User.objects(username="ana").first()
        assert (ana.lembrete_whatsapp, ana.lembrete_email, ana.lembrete_1h_whatsapp) == (True, False, True)
