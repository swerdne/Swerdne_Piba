"""Fixtures compartilhadas do Pytest."""
import contextlib
import pytest
from app import create_app
from app.extensions import db as _db


@contextlib.contextmanager
def sessao_isolada(app):
    """Empurra um app_context novo e descartavel.

    Necessario ao simular DUAS contas diferentes no mesmo teste: Flask-Login
    cacheia o usuario logado em `flask.g`, que fica preso ao app_context. O
    fixture `app` mantem um app_context aberto por todo o teste -- sem isso,
    a segunda "sessao" simulada herdaria o cache de login da primeira (um
    artefato so do teste; no servidor real cada requisicao tem seu proprio
    contexto e nao existe esse problema).
    """
    ctx = app.app_context()
    ctx.push()
    try:
        yield
    finally:
        ctx.pop()


@pytest.fixture
def app():
    app = create_app("testing")
    with app.app_context():
        _db.create_all()
        yield app
        _db.session.remove()
        _db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db(app):
    return _db


@pytest.fixture
def logged_in_client(client):
    client.post(
        "/auth/register",
        data={
            "username": "ana",
            "email": "ana@example.com",
            "password": "senha123",
            "confirm": "senha123",
        },
        follow_redirects=True,
    )
    return client


@pytest.fixture
def outro_logged_in_client(app):
    """Um segundo 'navegador' (cookies proprios) logado numa conta diferente."""
    cliente = app.test_client()
    with sessao_isolada(app):
        cliente.post(
            "/auth/register",
            data={
                "username": "bruno",
                "email": "bruno@example.com",
                "password": "senha123",
                "confirm": "senha123",
            },
            follow_redirects=True,
        )
    return cliente
