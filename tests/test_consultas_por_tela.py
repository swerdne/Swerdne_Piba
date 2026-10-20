"""Quantas idas ao banco cada tela do dia a dia faz (com dados de tamanho
real). Em producao cada consulta custa ~60 ms (o site esta no Chile, o
MongoDB em Sao Paulo) -- 30 consultas = ~2 s so esperando o banco. Estes
testes travam um ORCAMENTO por tela: se uma mudanca voltar a fazer consulta
em loop, o teste quebra. Pra ver os numeros: pytest -s este arquivo.
"""
import contextlib
import random
from datetime import date, time, timedelta

import mongomock
import pytest

from app.auth.models import User
from tests.conftest import sessao_isolada
from app.comunidade.models import Comunidade
from app.escala.models import Escala, Funcao, ItemRepertorio, Membro, Musica
from app.ministerio.models import Ministerio
from app.notificacoes import Notificacao

_OPERACOES = (
    "find", "find_one", "insert_one", "insert_many", "update_one", "update_many", "replace_one",
    "delete_one", "delete_many", "count_documents", "estimated_document_count", "aggregate",
    "find_one_and_update", "find_one_and_replace", "find_one_and_delete", "bulk_write", "distinct",
)


@contextlib.contextmanager
def contar_consultas():
    """Conta as chamadas ao banco (cada uma e uma volta de rede em producao)."""
    contagem = {"n": 0, "dentro": 0}
    originais = {}
    for nome in _OPERACOES:
        original = getattr(mongomock.collection.Collection, nome)
        originais[nome] = original

        def embrulho(self, *args, _original=original, **kwargs):
            # So a chamada de fora conta: o mongomock implementa umas
            # operacoes chamando outras (find_one_and_update -> find...),
            # o que no Mongo de verdade e UMA ida ao banco.
            if not contagem["dentro"]:
                contagem["n"] += 1
            contagem["dentro"] += 1
            try:
                return _original(self, *args, **kwargs)
            finally:
                contagem["dentro"] -= 1

        setattr(mongomock.collection.Collection, nome, embrulho)
    try:
        yield contagem
    finally:
        for nome, original in originais.items():
            setattr(mongomock.collection.Collection, nome, original)


@pytest.fixture
def igreja(logged_in_client, app, db):
    """Comunidade com 2 ministerios, 40 pessoas, 12 escalas futuras (8
    funcoes cada, a conta logada escalada em varias), repertorio, 300
    musicas e notificacoes -- tamanho de uma igreja real em uso."""
    random.seed(7)
    with app.app_context():
        logged_in_client.post("/comunidade/nova", data={"nome": "Igreja", "descricao": ""})
        comunidade = Comunidade.objects(nome="Igreja").first()
        for nome in ("Louvor", "Midia"):
            logged_in_client.post(f"/ministerio/comunidade/{comunidade.id}/nova", data={"nome": nome, "descricao": ""})
        louvor = Ministerio.objects(nome="Louvor").first()
        usuario = User.objects(username="ana").first()
        eu = Membro(comunidade_id=comunidade.id, nome="Ana", email=usuario.email, telefone="(11) 98765-4321").save()
        pessoas = [eu] + [Membro(comunidade_id=comunidade.id, nome=f"Pessoa {i}", telefone=f"(11) 9{i:04d}-0000",
                                 email=f"p{i}@example.com").save() for i in range(39)]
        musicas = [Musica(comunidade_id=comunidade.id, oficial=True, nome=f"Musica {i}", tom="G", tags=["amor", "fe"],
                          cifra_louvor="G D\nletra", letra_projecao="letra", palavras_chave_verificadas=True).save()
                   for i in range(300)]
        escalas = []
        for d in range(12):
            escala = Escala(ministerio_id=louvor.id, nome=f"Culto {d}", departamento="Louvor",
                            data=date.today() + timedelta(days=d + 1), horario=time(19, 0)).save()
            for ordem, membro in enumerate([eu] + random.sample(pessoas[1:], 7)):
                Funcao(escala_id=escala.id, nome=f"Funcao {ordem}", ordem=ordem, membro_id=membro.id,
                       status="nao_notificado").save()
            for ordem, musica in enumerate(random.sample(musicas, 5)):
                ItemRepertorio(escala_id=escala.id, nome_musica=musica.nome, musica_id=musica.id, tom="G", ordem=ordem).save()
            escalas.append(escala)
        for i in range(20):
            Notificacao(usuario_id=usuario.id, titulo=f"Aviso {i}", mensagem="x", escala_id=escalas[i % 12].id,
                        tipo="escalado").save()
        funcao_minha = Funcao.objects(escala_id=escalas[0].id, membro_id=eu.id).first()
        return {"comunidade": comunidade, "ministerio": louvor, "escala": escalas[0], "musica": musicas[0],
                "funcao": funcao_minha, "pessoa": pessoas[5]}


# Orcamento de consultas por tela (folga pequena sobre o medido): mudar
# um numero destes pra CIMA e decisao consciente, nao efeito colateral.
TELAS = [
    ("inicio", lambda d: "/dashboard", 30),
    ("minha escala", lambda d: "/minha-escala", 30),
    ("escala", lambda d: f"/escala/{d['escala'].id}", 30),
    ("ministerio", lambda d: f"/ministerio/{d['ministerio'].id}", 30),
    ("comunidade", lambda d: f"/comunidade/{d['comunidade'].id}", 30),
    ("banco de musicas", lambda d: f"/ministerio/musicas/{d['comunidade'].id}", 30),
    ("musica", lambda d: f"/ministerio/repertorio/{d['musica'].id}", 30),
]


@pytest.mark.parametrize("nome,url,orcamento", TELAS, ids=[t[0] for t in TELAS])
def test_consultas_por_tela(logged_in_client, app, igreja, nome, url, orcamento):
    caminho = url(igreja)
    with sessao_isolada(app):
        logged_in_client.get(caminho)  # 1a visita: preenchimentos unicos (tags, unificar banco...)
    # Contexto novo = requisicao limpa como no servidor (sem o cache de
    # login/por_requisicao que o teste deixaria preso de uma pra outra).
    with sessao_isolada(app), contar_consultas() as contagem:
        resposta = logged_in_client.get(caminho)
    assert resposta.status_code == 200
    print(f"\n[consultas] {nome}: {contagem['n']}")
    assert contagem["n"] <= orcamento, f"{nome} fez {contagem['n']} consultas (orcamento {orcamento})"


def test_salvar_status_rapido_responde_json_sem_recarregar(logged_in_client, app, igreja):
    """O select de status salva por fetch (X-Requested-With: fetch) e recebe
    JSON; sem o cabecalho continua redirecionando como sempre."""
    url = f"/escala/funcao/{igreja['funcao'].id}/status"
    resposta = logged_in_client.post(url, data={"status": "confirmado"}, headers={"X-Requested-With": "fetch"})
    dados = resposta.get_json()
    assert resposta.status_code == 200 and dados["ok"] and dados["status"] == "confirmado"
    assert dados["rotulo"] and dados["cor"].startswith("bg-")
    assert Funcao.objects(id=igreja["funcao"].id).first().status == "confirmado"

    invalido = logged_in_client.post(url, data={"status": "inventado"}, headers={"X-Requested-With": "fetch"})
    assert invalido.status_code == 400 and invalido.get_json()["ok"] is False

    normal = logged_in_client.post(url, data={"status": "nao_notificado"})
    assert normal.status_code == 302


def test_opcoes_de_envio_carregam_sob_demanda(logged_in_client, outro_logged_in_client, app, igreja):
    """A escala e o banco nao montam mais a lista de envio (5 consultas) --
    so o lugar "Carregando..."; a lista vem desta rota quando aparece."""
    escala = logged_in_client.get(f"/escala/{igreja['escala'].id}").data.decode()
    assert "data-envio-carregar=" in escala and "Todo o ministerio" not in escala
    pedaco = logged_in_client.get(f"/ministerio/envio/{igreja['comunidade'].id}/opcoes?padrao={igreja['ministerio'].id}")
    assert pedaco.status_code == 200 and "Todo o ministerio" in pedaco.data.decode() and "Louvor" in pedaco.data.decode()
    with sessao_isolada(app):
        assert outro_logged_in_client.get(f"/ministerio/envio/{igreja['comunidade'].id}/opcoes").status_code == 404


def test_consultas_ao_confirmar_presenca(logged_in_client, app, igreja):
    """Salvar o status (o toque mais comum do dia a dia) -- so o POST."""
    with sessao_isolada(app), contar_consultas() as contagem:
        logged_in_client.post(f"/escala/funcao/{igreja['funcao'].id}/status", data={"status": "confirmado"})
    print(f"\n[consultas] confirmar presenca (POST): {contagem['n']}")
    assert contagem["n"] <= 40


def test_consultas_ao_escalar_em_lote(logged_in_client, app, igreja):
    """Escalar 1 pessoa pelo lote da tela da escala: resposta JSON curta e o
    aviso (WhatsApp/e-mail/SMS) em segundo plano. Antes o fetch seguia o
    redirect e montava a tela da escala inteira a cada pessoa."""
    funcao = Funcao.objects(escala_id=igreja["escala"].id, membro_id__ne=igreja["funcao"].membro_id).first()
    url = f"/escala/funcao/{funcao.id}/adicionar"
    with sessao_isolada(app), contar_consultas() as antes:
        logged_in_client.post(url, data={"membro_id": igreja["pessoa"].id}, follow_redirects=True)
    with sessao_isolada(app), contar_consultas() as agora:
        resposta = logged_in_client.post(url, data={"membro_id": igreja["pessoa"].id},
                                         headers={"X-Requested-With": "fetch"})
    print(f"\nescalar 1 pessoa: {antes['n']} consultas com o redirect (jeito antigo), {agora['n']} so o JSON (lote)")
    assert resposta.get_json() == {"ok": True}
    assert agora["n"] <= 25 and agora["n"] < antes["n"]
