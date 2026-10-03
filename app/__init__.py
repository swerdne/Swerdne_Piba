"""Application Factory."""
import os
import click
from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix
from .config import config
from .extensions import db, migrate, login_manager, oauth, limiter


def create_app(config_name="default"):
    app = Flask(__name__)
    app.config.from_object(config[config_name])

    # Atras de um proxy reverso (Azure App Service, e qualquer PaaS que nao
    # normalize isso sozinho) a requisicao chega no processo Flask como HTTP
    # puro, mesmo quando o visitante usou HTTPS por fora -- o proxy so avisa
    # isso via cabecalho X-Forwarded-Proto. Sem confiar nesse cabecalho,
    # url_for(..., _external=True) gera "http://" em vez de "https://", o que
    # quebra o callback do Google OAuth (redirect_uri_mismatch, ja que so o
    # "https://" fica cadastrado no Google Cloud Console). x_proto=1/x_host=1
    # confia em exatamente 1 proxy na frente (a variavel padrao de qualquer
    # PaaS de camada unica como este).
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

    # Inicializa extensoes
    db.init_app(app)
    migrate.init_app(app, db)

    # Mongo (migracao em andamento, ver app/db_utils.py) -- convive com o
    # Postgres/SQLAlchemy acima enquanto os modulos vao sendo portados um a
    # um; nao faz nada em producao/dev ate MONGODB_URI ser configurada.
    from .db_utils import conectar_mongo
    conectar_mongo(app)

    # Notificacao (MongoEngine) nao pertence a nenhum blueprint especifico --
    # garante que a classe seja importada/registrada cedo.
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

    # Estaticos versionados (?v=hash, cache de 1 ano) + gzip -- ver app/desempenho.py.
    from .desempenho import registrar_desempenho
    registrar_desempenho(app)

    # Headers de seguranca em toda resposta -- reforcam o que o navegador ja
    # faz por padrao, mas contra ataques comuns que nao dependem de bug no
    # nosso codigo (ex.: um site malicioso te embutindo num <iframe> pra
    # clickjacking, ou o navegador "adivinhando" o tipo de um upload como
    # HTML executavel). Nao depende de config nenhuma, entao vale pra
    # dev/producao igual -- so o HSTS (que instrui o navegador a nunca mais
    # tentar HTTP nesse dominio) fica so em producao, onde HTTPS e garantido;
    # em dev, com http://localhost, isso travaria o acesso local.
    @app.after_request
    def aplicar_headers_seguranca(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if app.config.get("SESSION_COOKIE_SECURE"):
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    # Bootstrap do primeiro Super Admin -- proposital que so exista via
    # comando de terminal (nunca uma rota HTTP): ver app/convites/CLAUDE.md,
    # papel reservado ao dono/equipe tecnica, nunca atribuivel por convite.
    @app.cli.command("criar-super-admin")
    @click.argument("email")
    def criar_super_admin(email):
        from .auth.models import User

        usuario = User.objects(email=email).first()
        if usuario is None:
            click.echo(f"Nenhuma conta encontrada com o e-mail {email}. Peca pra pessoa se cadastrar primeiro.")
            return
        usuario.eh_super_admin = True
        usuario.save()
        click.echo(f"{email} agora e Super Admin.")

    # Corte de producao da migracao pra Mongo (Fase 8, ver plano da
    # migracao) -- so faz sentido rodar contra um app com DATABASE_URL
    # (Postgres de origem) E MONGODB_URI (Mongo de destino) configurados ao
    # mesmo tempo, uma combinacao que nao existe fora desse comando. Ver
    # app/migracao_dados.py pra detalhes de ordem/idempotencia/seed de counters.
    @app.cli.command("migrar-dados-mongo")
    @click.option("--dry-run", is_flag=True, help="Le e valida tudo, mas nao escreve nada no Mongo.")
    @click.option("--force", is_flag=True, help="Ignora a checagem de collection ja povoada -- sobrescreve por id (Document.save() substitui, nao duplica), cuidado se o app ja escreveu dados novos la depois da 1a migracao.")
    def migrar_dados_mongo(dry_run, force):
        from .migracao_dados import executar_migracao, ErroDeMigracao

        try:
            executar_migracao(dry_run=dry_run, force=force, log=click.echo)
        except ErroDeMigracao as erro:
            click.echo(f"ERRO: {erro}", err=True)
            raise SystemExit(1)

    # Disponibiliza `tema`/`temas` em TODOS os templates automaticamente (nao
    # so no dashboard) -- assim comunidade/escala/ministerio tambem respeitam
    # a preferencia de tema do usuario sem cada rota precisar passar isso.
    # Fotos antigas (app/static/uploads) apagadas por deploys viram "sem
    # imagem" ao carregar o documento -- icone padrao em vez de <img> quebrado.
    from .imagens import registrar_limpeza_de_legado
    registrar_limpeza_de_legado()

    @app.context_processor
    def injetar_tema():
        from flask_login import current_user
        from .main.themes import obter_tema, THEMES, TEMA_PADRAO

        chave = current_user.theme if current_user.is_authenticated else TEMA_PADRAO

        def avisos_nao_lidos():
            # Callable (nao valor) pra so consultar o banco nas telas que
            # realmente desenham a barra de navegacao inferior.
            if not current_user.is_authenticated:
                return 0
            from .notificacoes import Notificacao
            return Notificacao.objects(usuario_id=current_user.id, lida=False).count()

        def dados_tutorial(chave_tutorial):
            from .tutoriais import dados_do_tutorial
            return dados_do_tutorial(chave_tutorial, current_user)

        return {"tema": obter_tema(chave), "temas": THEMES, "avisos_nao_lidos": avisos_nao_lidos,
                "dados_tutorial": dados_tutorial}

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
