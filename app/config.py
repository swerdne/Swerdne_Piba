"""Classes de configuracao por ambiente."""
import os
import tempfile
from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "troque-esta-chave")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")

    # Mock do login Google para testes locais de UI/fluxo (ver app/auth/routes.py).
    # Cada classe de ambiente decide se honra essa env var ou nao.
    MOCK_GOOGLE_OAUTH = os.environ.get("MOCK_GOOGLE_OAUTH", "false").lower() == "true"

    # Upload de foto de perfil (ver app/main/routes.py)
    UPLOAD_FOLDER = os.path.join("app", "static", "uploads", "avatars")
    ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png"}
    MAX_CONTENT_LENGTH = 2 * 1024 * 1024  # 2 MB, aplicado pelo Flask a toda requisicao

    # Upload de logo de comunidade (ver app/comunidade/routes.py)
    COMUNIDADE_UPLOAD_FOLDER = os.path.join("app", "static", "uploads", "comunidades")

    # Upload de logo de ministerio (ver app/ministerio/routes.py)
    MINISTERIO_UPLOAD_FOLDER = os.path.join("app", "static", "uploads", "ministerios")

    # Mock do chatbot com IA (ver app/main/routes.py). Enquanto nao ligamos uma
    # API real (Anthropic/OpenAI), as respostas sao simuladas por regras simples.
    MOCK_CHATBOT = os.environ.get("MOCK_CHATBOT", "true").lower() == "true"

    # Envio de e-mail via API HTTP da Resend (notificacoes da Escala Rapida,
    # ver app/emailing.py). Nao usa SMTP: a rede de saida do Render (e da
    # maioria dos PaaS gratuitos) bloqueia as portas 25/465/587 por padrao
    # antiabuso, entao qualquer envio por SMTP falha com "Network is
    # unreachable" antes mesmo de chegar no servidor de e-mail. A API HTTPS
    # (porta 443) nao tem essa restricao.
    RESEND_API_KEY = os.environ.get("RESEND_API_KEY")
    RESEND_FROM_EMAIL = os.environ.get("RESEND_FROM_EMAIL")

    # Envio de SMS via Twilio (notificacoes da Escala Rapida, ver app/sms.py).
    TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
    TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
    TWILIO_FROM_NUMBER = os.environ.get("TWILIO_FROM_NUMBER")

    # Cadastro tradicional: confere se o dominio do e-mail tem registro MX (ou
    # A) antes de aceitar o cadastro (ver app/auth/dominio_email.py). Flag pra
    # poder desligar sem mexer em codigo (ex.: se a checagem de DNS comecar a
    # dar problema em producao).
    VALIDAR_DOMINIO_EMAIL = os.environ.get("VALIDAR_DOMINIO_EMAIL", "true").lower() == "true"


class DevelopmentConfig(Config):
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "sqlite:///dev.db")


class TestingConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False

    # Nao gravar avatares de teste na pasta real de uploads do projeto.
    UPLOAD_FOLDER = os.path.join(tempfile.gettempdir(), "meu_projeto_test_uploads")
    COMUNIDADE_UPLOAD_FOLDER = os.path.join(tempfile.gettempdir(), "meu_projeto_test_uploads_comunidades")
    MINISTERIO_UPLOAD_FOLDER = os.path.join(tempfile.gettempdir(), "meu_projeto_test_uploads_ministerios")

    # Isola os testes das credenciais reais do .env: sem isso, a suite de testes
    # enviaria e-mails/SMS de verdade usando a conta configurada no ambiente local.
    RESEND_API_KEY = None
    RESEND_FROM_EMAIL = None
    TWILIO_ACCOUNT_SID = None
    TWILIO_AUTH_TOKEN = None
    TWILIO_FROM_NUMBER = None

    # Testes nao devem depender de DNS real (lento, instavel, e trava CI sem rede).
    VALIDAR_DOMINIO_EMAIL = False

    # Desliga o rate limiting (app/extensions.py::limiter) nos testes -- a
    # suite registra/loga dezenas de contas via _registrar_e_confirmar
    # (tests/conftest.py) e estouraria qualquer limite pensado pra uso real.
    RATELIMIT_ENABLED = False


class ProductionConfig(Config):
    # Trava de seguranca: em producao exige SECRET_KEY real (nao aceita o
    # fallback fraco e publico da classe base, que so existe pra nao travar
    # o dev local sem .env configurado). Sem isso, sessao/CSRF/"lembrar de
    # mim" seriam assinados com uma chave conhecida (esta no codigo-fonte
    # publico), permitindo forjar cookies. Falha alto (nao sobe o app) em vez
    # de rodar inseguro silenciosamente.
    _secret_key = os.environ.get("SECRET_KEY")
    if not _secret_key:
        raise RuntimeError(
            "SECRET_KEY precisa estar definida como variavel de ambiente em producao "
            "(nao pode usar o fallback de desenvolvimento)."
        )
    SECRET_KEY = _secret_key

    # Cookie de sessao (Flask-Login) e de "lembrar de mim" so trafegam por
    # HTTPS, e SameSite=Lax da uma camada extra contra CSRF (alem do token do
    # Flask-WTF, que ja cobre os forms). Sem risco de quebrar nada aqui --
    # Render serve o app so por HTTPS.
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SECURE = True
    REMEMBER_COOKIE_SAMESITE = "Lax"

    _database_url = os.environ.get("DATABASE_URL")
    # Alguns provedores (Heroku, Render) ainda entregam a URL com o prefixo
    # antigo "postgres://" -- o SQLAlchemy 1.4+ so reconhece "postgresql://".
    if _database_url and _database_url.startswith("postgres://"):
        _database_url = _database_url.replace("postgres://", "postgresql://", 1)
    SQLALCHEMY_DATABASE_URI = _database_url

    # Reciclagem de conexao (equivalente ao conn_max_age do Django) e SSL
    # obrigatorio -- so fazem sentido pra Postgres, nao pra SQLite.
    if _database_url and _database_url.startswith("postgresql://"):
        SQLALCHEMY_ENGINE_OPTIONS = {
            "pool_recycle": 600,
            "connect_args": {"sslmode": "require"},
        }

    # Trava de seguranca: em producao o mock fica sempre desligado,
    # nao importa o que estiver escrito na env var MOCK_GOOGLE_OAUTH.
    MOCK_GOOGLE_OAUTH = False


config = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
    "default": DevelopmentConfig,
}
