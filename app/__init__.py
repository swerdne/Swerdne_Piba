"""Application Factory."""
import os
import click
from flask import Flask
from .config import config
from .extensions import db, migrate, login_manager, oauth, limiter


def create_app(config_name="default"):
    app = Flask(__name__)
    app.config.from_object(config[config_name])

    # Inicializa extensoes
    db.init_app(app)
    migrate.init_app(app, db)

    # Notificacao nao pertence a nenhum blueprint especifico -- garante que o
    # model seja registrado no metadata do SQLAlchemy (para migrations).
    from . import notificacoes  # noqa: F401
    login_manager.init_app(app)
    limiter.init_app(app)
    oauth.init_app(app)
    oauth.register(
        name="google",
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )

    # Registra Blueprints
    from .auth import bp as auth_bp
    app.register_blueprint(auth_bp, url_prefix="/auth")

    from .main import bp as main_bp
    app.register_blueprint(main_bp)

    from .comunidade import bp as comunidade_bp
    app.register_blueprint(comunidade_bp, url_prefix="/comunidade")

    from .ministerio import bp as ministerio_bp
    app.register_blueprint(ministerio_bp, url_prefix="/ministerio")

    from .escala import bp as escala_bp
    app.register_blueprint(escala_bp, url_prefix="/escala")

    from .plantao import bp as plantao_bp
    app.register_blueprint(plantao_bp, url_prefix="/plantao")

    from .convites import bp as convites_bp
    app.register_blueprint(convites_bp, url_prefix="/convite")

    from .errors import registrar_error_handlers
    registrar_error_handlers(app)

    # Bootstrap do primeiro Super Admin -- proposital que so exista via
    # comando de terminal (nunca uma rota HTTP): ver app/convites/CLAUDE.md,
    # papel reservado ao dono/equipe tecnica, nunca atribuivel por convite.
    @app.cli.command("criar-super-admin")
    @click.argument("email")
    def criar_super_admin(email):
        from .auth.models import User

        usuario = User.query.filter_by(email=email).first()
        if usuario is None:
            click.echo(f"Nenhuma conta encontrada com o e-mail {email}. Peca pra pessoa se cadastrar primeiro.")
            return
        usuario.eh_super_admin = True
        db.session.commit()
        click.echo(f"{email} agora e Super Admin.")

    # Disponibiliza `tema`/`temas` em TODOS os templates automaticamente (nao
    # so no dashboard) -- assim comunidade/escala/ministerio tambem respeitam
    # a preferencia de tema do usuario sem cada rota precisar passar isso.
    @app.context_processor
    def injetar_tema():
        from flask_login import current_user
        from .main.themes import obter_tema, THEMES, TEMA_PADRAO

        chave = current_user.theme if current_user.is_authenticated else TEMA_PADRAO
        return {"tema": obter_tema(chave), "temas": THEMES}

    # Agendador de notificacoes automaticas (24h/16h antes do evento) -- unico
    # no projeto: cada tick tambem sincroniza os Turnos de Rodizio (materializa
    # as proximas ocorrencias em Escala/Funcao reais) antes de notificar, ver
    # app/escala/agendador.py. Nunca roda em testes. O reloader do Flask (ativo
    # quando FLASK_DEBUG=1 ou `flask run --debug`) sobe um processo pai
    # (observador) + um filho (worker) -- so o filho tem WERKZEUG_RUN_MAIN=true,
    # entao so ele inicia o agendador. Sem reloader (nosso `flask run` normal),
    # roda direto.
    # OBS: num deploy com varios workers (gunicorn etc.), cada worker vai
    # rodar o proprio agendador -- multiplicando os envios. Ainda nao ha
    # protecao pra isso porque o projeto so roda em processo unico por enquanto.
    if config_name != "testing":
        reloader_ativo = os.environ.get("FLASK_DEBUG", "").lower() in ("1", "true", "on")
        if not reloader_ativo or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
            from .escala.agendador import iniciar_agendador
            iniciar_agendador(app)

    return app
