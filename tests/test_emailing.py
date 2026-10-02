"""Formato dos e-mails enviados pela Resend (app/emailing.py)."""
from app.emailing import enviar_email, montar_html


class _RespostaOk:
    status_code = 200
    text = "{}"


def test_email_sai_em_html_com_a_logo_e_tambem_em_texto(app, monkeypatch):
    enviado = {}

    def post_falso(url, headers, json, timeout):
        enviado.update(json)
        return _RespostaOk()

    monkeypatch.setattr("app.emailing.requests.post", post_falso)
    app.config.update(RESEND_API_KEY="chave", RESEND_FROM_EMAIL="TyBenson <notificacoes@pibaswerdne.me>",
                      URL_PUBLICA="https://pibaswerdne.me")

    with app.app_context():
        enviar_email("ana@example.com", "Escala cancelada: Culto", "Linha 1\nVeja https://pibaswerdne.me/escala/1")

    assert enviado["text"] == "Linha 1\nVeja https://pibaswerdne.me/escala/1"
    html = enviado["html"]
    assert 'src="https://pibaswerdne.me/static/img/logo-icone.png"' in html
    assert "Escala cancelada: Culto" in html
    assert "Linha 1<br>" in html
    assert '<a href="https://pibaswerdne.me/escala/1"' in html


def test_html_do_email_escapa_o_conteudo(app):
    app.config.update(URL_PUBLICA="https://pibaswerdne.me")
    with app.app_context():
        html = montar_html("<b>assunto</b>", "<script>alert(1)</script>")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "&lt;b&gt;assunto&lt;/b&gt;" in html
