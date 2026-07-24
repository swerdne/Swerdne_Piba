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

    # Envio de e-mail (notificacoes da Escala Rapida, ver app/emailing.py).
    MAIL_SERVER = os.environ.get("MAIL_SERVER")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", "587"))
    MAIL_USE_TLS = os.environ.get("MAIL_USE_TLS", "true").lower() == "true"
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD")
    MAIL_DEFAULT_SENDER = os.environ.get("MAIL_DEFAULT_SENDER")

    # Envio de SMS via Twilio (notificacoes da Escala Rapida, ver app/sms.py).
    TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
    TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
    TWILIO_FROM_NUMBER = os.environ.get("TWILIO_FROM_NUMBER")


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
    MAIL_SERVER = None
    MAIL_USERNAME = None
    MAIL_PASSWORD = None
    MAIL_DEFAULT_SENDER = None
    TWILIO_ACCOUNT_SID = None
    TWILIO_AUTH_TOKEN = None
    TWILIO_FROM_NUMBER = None


class ProductionConfig(Config):
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
