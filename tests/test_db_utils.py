"""Testes dos utilitarios da migracao pra MongoDB (app/db_utils.py)."""
from datetime import date, time

import mongoengine
import pytest

from app.db_utils import PureDateField, PureTimeField, SequentialIdDocument, atomic, delete_cascade, next_id


def test_next_id_incrementa_e_e_isolado_por_sequencia(app):
    with app.app_context():
        assert next_id("coisas") == 1
        assert next_id("coisas") == 2
        # sequencia diferente comeca do zero, independente da anterior
        assert next_id("outras_coisas") == 1
        assert next_id("coisas") == 3


class _Pai(SequentialIdDocument):
    _nome_sequencia = "pais_teste"
    nome = mongoengine.StringField(required=True)


class _Filho(SequentialIdDocument):
    _nome_sequencia = "filhos_teste"
    pai_id = mongoengine.IntField(required=True)
    nome = mongoengine.StringField(required=True)

    def cascade_children(self):
        return [_Neto.objects(filho_id=self.id)]


class _Neto(SequentialIdDocument):
    _nome_sequencia = "netos_teste"
    filho_id = mongoengine.IntField(required=True)


def test_sequential_id_document_preenche_id_automatico_no_save(app):
    with app.app_context():
        pai = _Pai(nome="Ana")
        assert pai.id is None
        pai.save()
        assert pai.id == 1

        outro = _Pai(nome="Bruno")
        outro.save()
        assert outro.id == 2


def test_sequential_id_document_respeita_id_explicito(app):
    """Necessario pro script de migracao de dados: precisa poder gravar o
    MESMO id inteiro que a linha tinha no Postgres, sem passar pelo
    contador (ver plano da migracao, passo 8)."""
    with app.app_context():
        pai = _Pai(id=57, nome="Importado")
        pai.save()
        assert pai.id == 57
        # o contador so eh usado quando id vem None -- nao avanca sozinho aqui
        novo = _Pai(nome="Novo")
        novo.save()
        assert novo.id == 1  # contador de "pais_teste" nunca foi usado antes


def test_delete_cascade_remove_arvore_multi_nivel(app):
    """Funcao > Escala > Ministerio > Comunidade e o caso real mais fundo;
    aqui simulamos com um pai/filho/neto generico so pra provar que
    delete_cascade desce mais de 1 nivel (o que reverse_delete_rule nativo
    do MongoEngine nao faz)."""
    with app.app_context():
        pai = _Pai(nome="Ana").save()
        filho = _Filho(pai_id=pai.id, nome="Bruno").save()
        neto = _Neto(filho_id=filho.id).save()

        delete_cascade(filho)

        assert _Filho.objects(id=filho.id).first() is None
        assert _Neto.objects(id=neto.id).first() is None
        # o pai nao foi tocado -- delete_cascade so desce, nunca sobe
        assert _Pai.objects(id=pai.id).first() is not None


def test_atomic_vira_no_op_quando_transacao_desligada(app):
    """TestingConfig desliga MONGO_TRANSACTIONS_ENABLED porque o mongomock
    nao suporta sessao/transacao nenhuma (NotImplementedError) -- atomic()
    precisa degradar pra "sem transacao" nesse caso, sem quebrar."""
    with app.app_context():
        with atomic() as sessao:
            assert sessao is None
            _Pai(nome="Sem transacao").save(session=sessao)

        assert _Pai.objects(nome="Sem transacao").first() is not None


def test_atomic_levanta_quando_transacao_ligada_mas_backend_nao_suporta(app):
    """Confirma que, se algum dia MONGO_TRANSACTIONS_ENABLED for ligado
    contra um backend sem suporte a sessao (como o mongomock), o erro
    aparece de forma clara em vez de silenciosamente nao fazer nada."""
    app.config["MONGO_TRANSACTIONS_ENABLED"] = True
    with app.app_context():
        with pytest.raises(NotImplementedError):
            with atomic():
                pass


class _ComData(SequentialIdDocument):
    _nome_sequencia = "com_data_teste"
    d = PureDateField()
    h = PureTimeField()


def test_pure_date_field_guarda_e_devolve_date_puro(app):
    """Sem a conversao, isso viraria datetime na leitura -- e date/datetime
    nunca sao == nem comparaveis entre si em Python, mesmo no mesmo dia."""
    with app.app_context():
        doc = _ComData(d=date(2026, 9, 30)).save()
        recarregado = _ComData.objects(id=doc.id).first()
        assert type(recarregado.d) is date
        assert recarregado.d == date(2026, 9, 30)


def test_pure_time_field_guarda_e_devolve_time_puro(app):
    with app.app_context():
        doc = _ComData(h=time(14, 30)).save()
        recarregado = _ComData.objects(id=doc.id).first()
        assert type(recarregado.h) is time
        assert recarregado.h == time(14, 30)


def test_pure_date_field_permite_query_por_data(app):
    with app.app_context():
        _ComData(d=date(2026, 9, 30)).save()
        assert _ComData.objects(d=date(2026, 9, 30)).count() == 1
        assert _ComData.objects(d__gte=date(2026, 9, 1)).count() == 1
        assert _ComData.objects(d=date(2026, 9, 29)).count() == 0
