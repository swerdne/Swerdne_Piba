"""Materiais (anexos) por escala/funcao e a aba pessoal "Minha escala"."""
import io
from datetime import date, timedelta

from app.escala.models import Anexo, Escala, Funcao
from tests.conftest import sessao_isolada
from tests.test_escala import (
    _criar_comunidade,
    _criar_ministerio,
    _criar_escala,
    _criar_membro,
    _escalar,
    _funcao_por_nome,
)

PDF = b"%PDF-1.4 cifra de teste"


def _anexar(cliente, escala_id, nome="cifra.pdf", conteudo=PDF, funcao_id=0):
    return cliente.post(
        f"/escala/{escala_id}/anexos",
        data={"anexo-arquivo": (io.BytesIO(conteudo), nome), "anexo-funcao_id": str(funcao_id)},
        content_type="multipart/form-data",
        follow_redirects=True,
    )


def _montar(cliente, email="ana@example.com", dias=3):
    comunidade = _criar_comunidade(cliente)
    ministerio = _criar_ministerio(cliente, comunidade.id)
    escala = _criar_escala(cliente, ministerio.id, "Culto de Domingo",
                           data=(date.today() + timedelta(days=dias)).isoformat(), horario="18:00")
    membro = _criar_membro(cliente, comunidade.id, "Ana", email=email)
    _escalar(cliente, _funcao_por_nome(escala, "Baixo").id, membro.id)
    return comunidade, ministerio, escala


# --- Materiais ---------------------------------------------------------------

def test_lider_anexa_arquivo_e_ele_abre_no_navegador(logged_in_client, app, db):
    with app.app_context():
        _, _, escala = _montar(logged_in_client)
        resposta = _anexar(logged_in_client, escala.id)
        assert "cifra.pdf&#34; anexado" in resposta.data.decode("utf-8")

        anexo = Anexo.objects(escala_id=escala.id).first()
        assert anexo.funcao_id is None and anexo.tamanho == len(PDF)

        arquivo = logged_in_client.get(f"/escala/anexo/{anexo.id}")
        assert arquivo.status_code == 200
        assert arquivo.mimetype == "application/pdf"
        assert arquivo.data == PDF
        assert "attachment" not in arquivo.headers.get("Content-Disposition", "")


def test_formato_nao_aceito_e_recusado(logged_in_client, app, db):
    with app.app_context():
        _, _, escala = _montar(logged_in_client)
        resposta = _anexar(logged_in_client, escala.id, nome="virus.exe", conteudo=b"MZ")
        assert "Formatos aceitos" in resposta.data.decode("utf-8")
        assert Anexo.objects(escala_id=escala.id).count() == 0


def test_arquivo_acima_de_10mb_volta_com_aviso(logged_in_client, app, db):
    with app.app_context():
        _, _, escala = _montar(logged_in_client)
        grande = b"%PDF" + b"0" * (11 * 1024 * 1024)
        resposta = logged_in_client.post(
            f"/escala/{escala.id}/anexos",
            data={"anexo-arquivo": (io.BytesIO(grande), "grande.pdf"), "anexo-funcao_id": "0"},
            content_type="multipart/form-data",
            headers={"Referer": f"http://localhost/escala/{escala.id}"},
        )
        assert resposta.status_code == 302
        html = logged_in_client.get(f"/escala/{escala.id}").data.decode("utf-8")
        assert "O arquivo deve ter no maximo 10 MB." in html
        assert Anexo.objects(escala_id=escala.id).count() == 0


def test_foto_de_2mb_continua_limitada_fora_dos_anexos(logged_in_client, app, db):
    """O limite maior vale so pra rota de anexos."""
    with app.app_context():
        resposta = logged_in_client.post(
            "/comunidade/nova",
            data={"nome": "Igreja X", "imagem": (io.BytesIO(b"\xff\xd8" + b"0" * (3 * 1024 * 1024)), "foto.jpg")},
            content_type="multipart/form-data",
        )
        assert resposta.status_code == 302


def test_quem_nao_lidera_nao_anexa(logged_in_client, outro_logged_in_client, app, db):
    with sessao_isolada(app):
        _, _, escala = _montar(logged_in_client)
    with sessao_isolada(app):
        assert _anexar(outro_logged_in_client, escala.id).status_code == 404
        assert Anexo.objects(escala_id=escala.id).count() == 0


def test_excluir_funcao_e_escala_levam_os_anexos(logged_in_client, app, db):
    with app.app_context():
        _, _, escala = _montar(logged_in_client)
        baixo = _funcao_por_nome(escala, "Baixo")
        _anexar(logged_in_client, escala.id, nome="baixo.pdf", funcao_id=baixo.id)
        _anexar(logged_in_client, escala.id, nome="geral.pdf")

        logged_in_client.post(f"/escala/funcao/{baixo.id}/excluir")
        assert [a.nome_arquivo for a in Anexo.objects(escala_id=escala.id)] == ["geral.pdf"]

        logged_in_client.post(f"/escala/{escala.id}/excluir")
        assert Anexo.objects(escala_id=escala.id).count() == 0


# --- Minha escala ------------------------------------------------------------

def test_minha_escala_mostra_so_os_materiais_da_minha_funcao(logged_in_client, app, db):
    with app.app_context():
        _, _, escala = _montar(logged_in_client)
        baixo = _funcao_por_nome(escala, "Baixo")
        bateria = _funcao_por_nome(escala, "Bateria")
        _anexar(logged_in_client, escala.id, nome="roteiro-geral.pdf")
        _anexar(logged_in_client, escala.id, nome="cifra-baixo.pdf", funcao_id=baixo.id)
        _anexar(logged_in_client, escala.id, nome="levada-bateria.pdf", funcao_id=bateria.id)

        html = logged_in_client.get("/minha-escala").data.decode("utf-8")

    assert "Culto de Domingo" in html
    assert ">Baixo<" in html
    assert "roteiro-geral.pdf" in html and "Toda a equipe" in html
    assert "cifra-baixo.pdf" in html and "Pra voce &middot; Baixo" in html
    assert "levada-bateria.pdf" not in html


def test_minha_escala_navega_entre_os_dias(logged_in_client, app, db):
    with app.app_context():
        comunidade, ministerio, primeira = _montar(logged_in_client, dias=2)
        segunda = _criar_escala(logged_in_client, ministerio.id, "Culto de Quarta",
                                data=(date.today() + timedelta(days=5)).isoformat())
        ana = _funcao_por_nome(primeira, "Baixo").membro
        _escalar(logged_in_client, _funcao_por_nome(segunda, "Bateria").id, ana.id)

        padrao = logged_in_client.get("/minha-escala").data.decode("utf-8")
        assert "Culto de Domingo</h2>" in padrao

        outra = logged_in_client.get(f"/minha-escala?escala={segunda.id}").data.decode("utf-8")
        assert "Culto de Quarta</h2>" in outra and ">Bateria<" in outra


def test_minha_escala_sem_escalacao(logged_in_client, app, db):
    with app.app_context():
        html = logged_in_client.get("/minha-escala").data.decode("utf-8")
    assert "ainda nao esta escalado" in html


def test_status_pela_minha_escala_volta_pra_ela(logged_in_client, app, db):
    with app.app_context():
        _, _, escala = _montar(logged_in_client)
        baixo = _funcao_por_nome(escala, "Baixo")
        voltar = f"/minha-escala?escala={escala.id}"
        resposta = logged_in_client.post(
            f"/escala/funcao/{baixo.id}/status",
            data={"status": "confirmado", "troca_sugestao_membro_id": "0", "voltar": voltar},
        )
        assert resposta.status_code == 302
        assert resposta.headers["Location"].endswith(voltar)
        assert Funcao.objects(id=baixo.id).first().status == "confirmado"

        externo = logged_in_client.post(
            f"/escala/funcao/{baixo.id}/status",
            data={"status": "presente", "troca_sugestao_membro_id": "0", "voltar": "//evil.com/minha-escala"},
        )
        assert externo.headers["Location"].endswith(f"/escala/{escala.id}")


def test_navegacao_tem_minha_escala_e_inicio_aponta_pra_ela(logged_in_client, app, db):
    with app.app_context():
        _, _, escala = _montar(logged_in_client)
        html = logged_in_client.get("/dashboard").data.decode("utf-8")
    assert 'href="/minha-escala"' in html
    assert f'href="/minha-escala?escala={escala.id}"' in html
