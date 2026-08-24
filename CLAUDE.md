# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Visão geral do projeto

Sistema de gestão para comunidades religiosas (igrejas), em português do Brasil, back-end em **Flask** (Application Factory + Blueprints + MVC). Um usuário cadastra uma ou mais **Comunidades**, cada comunidade organiza **Ministérios** (Louvor, Mídia, Kids, Coreografia...), e todo evento escalado num Ministério é uma **Escala** (`app/escala`), com uma ou mais **funções** atribuídas a um **Membro** do diretório da comunidade. Uma `Escala` pode ter duas origens:

- **Manual ("Escala Rápida")** — criada com funções pré-definidas por departamento (template), atribuição sempre por escolha manual.
- **Gerada por rodízio** (`app/plantao`) — um `TurnoPlantao` (fila de **equipes**, cada uma com 1+ pessoas que atuam juntas + offset + recorrência) é a *regra*; o motor de sincronização de `app/plantao` materializa essa regra em `Escala`/`Funcao` reais numa janela rolante de 180 dias (~6 meses), com 1 função por integrante da equipe sorteada. Uma vez materializada, a ocorrência é uma `Escala` como qualquer outra — mesma cor no calendário, mesmo relatório, mesma notificação. Quando o turno nasce a partir de uma escala existente ("Criar turno de rodízio com esta equipe"), o vínculo é permanente (`Escala.turno_plantao_origem_id`) e a escala de origem vira o único ponto de entrada pro rodízio na listagem do Ministério (não gera uma capa separada). **Não existe mais uma tela separada de "Plantão"** — só uma tela de configuração da regra (fila/offset/recorrência); ver [app/plantao/CLAUDE.md](app/plantao/CLAUDE.md).

Funcionalidades transversais:
- **Notificações automáticas** 24h/16h antes do evento (e-mail + SMS + sino in-app), via um único job APScheduler (`app/escala/agendador.py`) — cobre escalas manuais e geradas por rodízio igualmente.
- **Chatbot** (`/chat`) — atualmente **mockado** por regex (`_REGRAS_CHAT` em `app/main/routes.py`), cobrindo login/cadastro/perfil e também a estrutura do site (Comunidade, Ministério, Escala, Rodízio, convites, notificações, tutorial guiado); sem integração real de IA (é um TODO explícito no código).
- **Login** tradicional (e-mail/senha) e via **Google OAuth** (Authlib), com mock de OAuth para testes locais sem credenciais reais.
- **Relatório "Escalados"** por comunidade — quem está escalado em qualquer ministério, com filtros de data/departamento/função.
- **Tutorial guiado (spotlight)** na primeira vez que a conta abre uma Comunidade — motor genérico reaproveitável em `app/static/js/main.js::iniciarTutorialSpotlight`, ver [app/comunidade/CLAUDE.md](app/comunidade/CLAUDE.md).
- **PWA instalável** — `app/static/manifest.webmanifest` + `app/static/js/service-worker.js` (servido na raiz via `main.service_worker`, não em `/static/js/`, pro escopo cobrir o site inteiro). O service worker só cacheia assets estáticos (`/static/*`, GET) de propósito — nunca páginas HTML/rotas dinâmicas, pra não arriscar servir dado de uma conta pra outra num aparelho compartilhado. Ícones em `app/static/img/icon-*.png` (normal + versão `maskable` com mais respiro pro Android) e `apple-touch-icon.png` (iOS, sem transparência).

Não existe sistema de papéis (não há admin/regular user). Autorização é toda por **posse do recurso** — ver seção "Autenticação/Autorização".

## Stack

- **Backend:** Flask (Application Factory em [app/\_\_init\_\_.py](app/__init__.py)), Flask-SQLAlchemy, Flask-Migrate (Alembic), Flask-Login, Flask-WTF, Flask-Limiter (rate limiting, ver [app/auth/CLAUDE.md](app/auth/CLAUDE.md)), Authlib (OAuth), APScheduler, Twilio (SMS), API HTTP da Resend via `app/emailing.py` (não SMTP — ver o próprio arquivo pra saber por quê).
- **Banco:** SQLite (`dev.db` em dev, `:memory:` em teste). `DATABASE_URL` troca para outro banco em produção.
- **Frontend:** Server-side rendering com Jinja2 + Tailwind CSS v4 (compilado via `@tailwindcss/cli`, sem framework JS — só `app/static/js/main.js`, mínimo).
- **Testes:** pytest, com fixtures que sobem um app Flask completo em SQLite in-memory (`tests/conftest.py`).

Não é um repositório git (`git init` ainda não foi rodado neste diretório).

## Como rodar localmente

Ambiente já tem um venv em `meu_projeto/venv` (Windows). Comandos (PowerShell, a partir de `meu_projeto/`):

```powershell
# instalar dependências
./venv/Scripts/python.exe -m pip install -r requirements.txt

# variáveis de ambiente: copiar .env.example para .env e preencher
# (SECRET_KEY, GOOGLE_CLIENT_ID/SECRET, MAIL_*, TWILIO_* — todas opcionais
# em dev; sem elas, e-mail/SMS/Google real ficam desativados/mockados)
copy .env.example .env

# banco (Alembic/Flask-Migrate)
./venv/Scripts/python.exe -m flask --app run db upgrade

# rodar o servidor
./venv/Scripts/python.exe -m flask --app run run
# ou, com auto-reload:
$env:FLASK_DEBUG="1"; ./venv/Scripts/python.exe -m flask --app run run
```

**Banco Postgres externo (Neon, Supabase etc.) em vez do SQLite local:** basta preencher `DATABASE_URL` no `.env` com a connection string do provedor (`postgresql://usuario:senha@host/banco?sslmode=require`) — `DevelopmentConfig` já lê `DATABASE_URL` do ambiente e só cai no SQLite (`sqlite:///dev.db`) quando a variável **não está definida**; não é preciso mudar `FLASK_CONFIG` para isso (`FLASK_CONFIG=development` continua certo, é só sobre qual banco, não qual conjunto de configurações). O driver (`psycopg2-binary`) já está no `requirements.txt`. Prefixo antigo `postgres://` (Heroku/Render) é normalizado para `postgresql://` automaticamente em `ProductionConfig` — se for usar um Postgres externo com `FLASK_CONFIG=development` (comum em dev), confira se a URL já vem com `postgresql://`, já que `DevelopmentConfig` não faz essa normalização.

**Cold start em produção (planos gratuitos):** Render free hiberna o servidor após ~15 min sem tráfego (~30-60s pra religar na próxima requisição); Neon free hiberna o Postgres separadamente após alguns minutos de inatividade (~1-3s pra acordar na próxima query). Não é bug de código nem algo que otimização de query resolve. `GET /healthz` (`app/main/routes.py`) é um endpoint público e leve pensado justamente pra isso: faz uma consulta real no banco (`SELECT 1`) de propósito, pra um ping externo (cron-job.org, UptimeRobot etc.) manter os dois serviços acordados — pingar só `/` ou `/auth/login` não seria suficiente, porque não tocam no banco.

CSS (Tailwind, só necessário se mexer em classes/estilo):

```powershell
npm install
npm run watch:css   # dev, recompila em watch
npm run build:css   # build minificado
```

### Testes

```powershell
./venv/Scripts/python.exe -m pytest -q
# um arquivo:
./venv/Scripts/python.exe -m pytest -q tests/test_plantao.py
# um teste específico:
./venv/Scripts/python.exe -m pytest -q tests/test_plantao.py::test_equipe_do_periodo_rotaciona_grupos_inteiros
```

`TestingConfig` usa SQLite `:memory:`, desativa CSRF, força e-mail/SMS/OAuth real desligados e nunca inicia os schedulers APScheduler (`create_app("testing")` pula o bloco de agendadores em [app/\_\_init\_\_.py](app/__init__.py)).

### Migrations

```powershell
./venv/Scripts/python.exe -m flask --app run db migrate -m "descrição em português, snake_case-like"
./venv/Scripts/python.exe -m flask --app run db upgrade
```

Sempre revisar a migration autogerada antes de aplicar — o histórico em `migrations/versions/` mostra o padrão usado ao adicionar uma FK obrigatória em tabela já populada: **coluna nullable → migration de backfill → migration tornando NOT NULL** (3 migrations separadas), nunca um único `alter column not null` direto.

**SQLite vs. Postgres em migrations com `op.execute(...)` de SQL cru:** o projeto rodou anos só contra SQLite (dev/CI), que é extremamente tolerante (tipo de coluna é só "afinidade" — aceita `DATETIME` como nome de tipo mesmo não existindo de verdade — e FK não é enforced por padrão, ver `app/plantao/CLAUDE.md`). Postgres é estrito nos dois pontos: `DATETIME` não existe (`type "datetime" does not exist` — use `TIMESTAMP`, que funciona idêntico nos dois bancos) e `DROP TABLE` falha se outra tabela ainda tem FK apontando pra ela (`DependentObjectsStillExist` — precisa `CASCADE`, só aceito no Postgres, não no SQLite). Também não faça cast implícito de literal inteiro pra `BOOLEAN` em `DEFAULT` (`DEFAULT 0` funciona no SQLite, quebra no Postgres com `DatatypeMismatch`; use `DEFAULT false`/`true`). Migrations que usam SQL cru dependente de dialeto devem checar `op.get_bind().dialect.name` e ramificar quando o comportamento precisa diferir entre os dois bancos (ver `c7e3674500d1` e `90778b537d1f` para o padrão) — **teste toda migration nova rodando `db upgrade` contra um Postgres real pelo menos uma vez antes de considerar pronta**, não só contra o `dev.db` SQLite.

## Estrutura de pastas

```
app/
  __init__.py        # Application Factory: registra extensões, blueprints, context processor de tema, schedulers
  config.py           # Config por ambiente (development/testing/production) via FLASK_CONFIG
  extensions.py        # db, migrate, login_manager, oauth — instâncias soltas (evita import circular)
  notificacoes.py      # Model Notificacao (sino in-app) — fora de qualquer blueprint, ver seção "Regras de negócio" abaixo
  emailing.py          # Envio de e-mail (API HTTP da Resend, não SMTP) para notificações
  sms.py                # Envio de SMS (Twilio) para notificações
  auth/                 # Login/registro/Google OAuth — models.py (User), routes.py, forms.py
  comunidade/            # Comunidade + Membro (diretório de pessoas) + UsuarioComunidade (papel) — ver app/comunidade/CLAUDE.md
  ministerio/             # Ministério (organizacional) + calendário mensal + UsuarioMinisterio (papel)
  escala/                  # Escala (manual ou gerada por rodízio) — ver app/escala/CLAUDE.md. Único módulo com agendador.py (o scheduler é único no projeto).
  plantao/                  # Motor de rodízio: TurnoPlantao + sincronizacao.py, materializa em Escala real — ver app/plantao/CLAUDE.md
  convites/                 # Papel por convite de e-mail (aceitar/recusar) — ver app/convites/CLAUDE.md
  main/                      # Dashboard, chatbot mock, upload de avatar, temas — ver app/main/themes.py
  templates/<módulo>/<ação>.html   # nome do template espelha o nome da view (nova.html, detalhe.html, editar.html)
  static/{css,js,img,uploads}
migrations/versions/    # Alembic, arquivos hash_slug.py
tests/                   # um test_<módulo>.py por blueprint + test_agendador.py (scheduler único, cobre escala manual e gerada por rodízio)
```

Cada blueprint segue o mesmo layout interno: `models.py`, `routes.py`, `forms.py`, `__init__.py` (define `bp = Blueprint(...)` e importa `routes` no final, com `# noqa: E402`); `plantao` também tem `sincronizacao.py` (motor de materialização, chamado pelo agendador único em `app/escala/agendador.py`).

## Convenções de nomenclatura

- Todo o código (identificadores, docstrings, comentários, mensagens flash, templates) é em **português**; só termos estruturais do Flask ficam em inglês (`routes`, `models`, `forms`, `bp`).
- Blueprint sempre chamado literalmente `bp` em todo módulo.
- Rotas de criação são sempre `nova` (nunca `criar`/`novo`) — concordância de gênero é seguida à risca (Comunidade, Escala → "nova"; não existe "novo" em lugar nenhum).
- Verbos de rota em snake_case português: `nova`, `detalhe`, `editar`, `excluir_*`, `adicionar_*`, `remover_*`.
- Helpers privados de autorização seguem o padrão `_<recurso>_do_usuario_ou_404(id)`: `_comunidade_do_usuario_ou_404`, `_ministerio_do_usuario_ou_404` (estrito, só CRUD do Ministério), `_escala_do_usuario_ou_404`, `_funcao_do_usuario_ou_404`, `_turno_do_usuario_ou_404` — todos, por baixo, delegam pra `_eh_admin_da_comunidade`/`_eh_lider_do_ministerio` (ver [app/convites/CLAUDE.md](app/convites/CLAUDE.md)). Ao adicionar um recurso novo com dono, crie o helper equivalente em vez de inline-checar em cada rota. Quando o recurso também tem um caminho de acesso somente-leitura (não só pra escrita), o padrão é `_<recurso>_visivel_ou_404(id)`, retornando `(recurso, pode_gerenciar)` (`comunidade._comunidade_visivel_ou_404`, `ministerio._ministerio_visivel_ou_404`, `escala._escala_visivel_ou_404`) — nunca embuta a checagem de leitura dentro do helper `_do_usuario_ou_404`/`_gerenciavel_ou_404` estrito, que continua exclusivo pra rotas de escrita. `_ministerio_gerenciavel_ou_404` (admin OU líder) é o helper usado por conteúdo do ministério (escalas, turnos) — diferente do `_ministerio_do_usuario_ou_404` estrito (só admin), que é exclusivo pro CRUD do Ministério em si.
- Forms terminam em `Form` (`EscalaForm`, `StatusForm`); `AcaoForm` é um form vazio (só CSRF) reimplementado em cada blueprint para ações simples de POST (excluir, remover, notificar) — não existe uma classe compartilhada.
- Models em PascalCase português; `__tablename__` em snake_case, às vezes prefixado pelo módulo dono para evitar colisão (`escala_membros`, `escala_funcoes`, `turnos_plantao`).
- Templates em `app/templates/<módulo>/<ação>.html`, nome espelhando a view.
- Classes Tailwind nos temas (`app/main/themes.py`) **sempre como string literal completa**, nunca concatenada/f-string — o scanner estático do Tailwind precisa achar a classe no source.

## Autenticação / Autorização

- Flask-Login (`@login_required`) em toda rota que exige usuário logado; `login_manager.login_view = "auth.login"` redireciona não-autenticados.
- **Sistema de papéis contextual** (Super Admin → Admin da Comunidade → Líder de Ministério → Membro → Convidado), concedido sempre via convite por e-mail aceito (`app/convites`) — ver [app/convites/CLAUDE.md](app/convites/CLAUDE.md) pro fluxo completo. Cada blueprint sobe a cadeia de FKs e consulta o papel via helpers centralizados (`comunidade.routes._eh_admin_da_comunidade`, `ministerio.routes._eh_lider_do_ministerio`/`_eh_membro_do_ministerio`), retornando **404 (não 403)** em caso de descompasso — propositalmente, para não revelar a existência do recurso a quem está adivinhando IDs pela URL. Siga o mesmo padrão (404, não 403) ao adicionar novas rotas de recurso.
- Além das duas exceções somente-leitura por match de `email` já existentes (`comunidade._comunidade_visivel_ou_404`, diretório de `Membro`; `escala._escala_visivel_ou_404`, `Funcao.eh_convidado=True`, ver [app/escala/CLAUDE.md](app/escala/CLAUDE.md)), papel=membro (`UsuarioComunidade`/`UsuarioMinisterio`) agora também concede leitura pelo mesmo mecanismo de helpers — nenhuma das duas formas dá acesso de escrita por si só.
- `User` acumula login tradicional e Google OAuth na mesma tabela (`password_hash` nullable para contas só-Google; `check_password` retorna `False` se não houver hash). Vínculo de conta Google a uma conta existente é por e-mail (`auth/routes.py`). `User.eh_super_admin` (bool) só é atribuível via `flask criar-super-admin <email>` (comando de terminal, nunca uma rota HTTP).
- **Cadastro tradicional não exige confirmação de e-mail** — loga direto, igual Google. Já existiu um fluxo de confirmação por link; foi removido a pedido do usuário (gerava fricção) — ver [app/auth/CLAUDE.md](app/auth/CLAUDE.md) antes de reintroduzir algo parecido.
- `MOCK_GOOGLE_OAUTH` permite testar o fluxo Google sem credenciais reais (renderiza `auth/google_mock.html`, simula sucesso/negação/timeout via `?cenario=`); `ProductionConfig` trava esse mock como sempre `False` independentemente da env var — não remova essa trava.
- **Segurança de autenticação** (rate limiting, `SECRET_KEY` obrigatória em produção, cookies `SECURE`/`SAMESITE`, senha mínima) — ver [app/auth/CLAUDE.md](app/auth/CLAUDE.md).

## Regras de negócio importantes

- **Escala manual ("Escala Rápida")** é baseada em template fixo por departamento (`DEPARTAMENTOS` em `app/escala/models.py`), sem rotação automática — atribuição de pessoa a função é sempre manual. Cada `Escala` pode ter uma cor própria (`cor_selecionada`, opcional — cai na cor do departamento se não escolhida), refletida tanto na lista quanto no calendário do Ministério. Ver [app/escala/CLAUDE.md](app/escala/CLAUDE.md).
- **Convidado** — além de escolher um `Membro` do diretório, o dono pode buscar e vincular uma conta (`User`) já cadastrada na plataforma a uma `Funcao`, como participação pontual (`Funcao.eh_convidado=True`), sem duplicar cadastro (find-or-create de `Membro` por e-mail) e sem entrar no rodízio automático. Reaproveita 100% do pipeline de notificação e o padrão de visibilidade por e-mail já existente. Ver [app/escala/CLAUDE.md](app/escala/CLAUDE.md).
- **Rodízio (`app/plantao`)** — regra: `equipe = fila[(offset + período) % len(fila)]`. Cada posição da fila é uma **equipe** (grupo de 1+ pessoas que atuam juntas, na mesma ocorrência — rotação individual é só o caso de equipes com 1 integrante). "Período" é a N-ésima ocorrência gerada pela recorrência do turno, que segue a mesma lógica do Google Agenda: intervalo livre ("a cada N dias/semanas/meses/anos"), dias da semana específicos quando semanal, 3 modos quando mensal (dia fixo / último dia-da-semana / enésimo dia-da-semana, todos derivados de `data_inicio`) e término por nunca/data/número de ocorrências (`TurnoPlantao`, `app/plantao/models.py`). A regra em si nunca guarda quem está escalado em cada data; quem guarda é o motor de sincronização (`app/plantao/sincronizacao.py::sincronizar_turno`), que **materializa** a regra em `Escala`/`Funcao` reais (1 `Funcao` por integrante da equipe) numa janela rolante de 180 dias (~6 meses) — essas linhas aparecem no calendário/relatório como qualquer escala manual. `Escala.plantao_fixado` trava uma ocorrência que divergiu da fórmula (alguém removido/reatribuído manualmente, ou edição de nome/data) para o sync não sobrescrevê-la; o histórico (ocorrências já passadas) nunca é tocado pelo sync. Não há remanejamento automático por ausência. Quando o turno nasce de uma escala existente, `Escala.turno_plantao_origem_id` vincula os dois permanentemente. Ver [app/plantao/CLAUDE.md](app/plantao/CLAUDE.md) para os detalhes (idempotência obrigatória, `periodo_da_data` é uma estimativa/floor — não um mapeamento exato —, renumeração ao mudar qualquer campo de recorrência, exclusão de turno).
- **Notificações automáticas 24h/16h antes** rodam num **único** job APScheduler (`app/escala/agendador.py`), a cada 15 min com janela de tolerância de ±15 min — cobre escalas manuais e geradas por rodízio da mesma forma, já que ambas são `Escala` reais. O mesmo tick também sincroniza todo `TurnoPlantao` ativo antes de checar notificações. Não introduza um scheduler separado para rodízio — a materialização e a notificação são deliberadamente uma coisa só agora.
- O scheduler só sobe fora do modo `testing`, e há proteção contra o reloader do Flask iniciar o job duas vezes (checagem de `WERKZEUG_RUN_MAIN`). **Não há proteção contra múltiplos workers** (gunicorn etc.) duplicando notificações — comentário explícito no código sinalizando isso como problema conhecido caso o deploy mude de processo único para multi-worker.
- E-mail/SMS falhando nunca derruba a request (exceptions `EmailNaoEnviadoError`/`SmsNaoEnviadoError` são capturadas e contabilizadas) — mantenha esse comportamento ao mexer em `emailing.py`/`sms.py`.
- Notificação in-app (`Notificacao`) só é criada quando o `email` do `Membro` escalado bate com o `email` de um `User` cadastrado — é um canal extra, não substitui e-mail/SMS.
- Editar data/horário de uma `Escala` (manual ou via edição do `TurnoPlantao` que a gerou) reseta os timestamps `notificado_24h_em`/`notificado_16h_em` (para o scheduler reenviar) e dispara notificação proativa de alteração para quem já estava escalado — mas o reset só acontece se o valor **realmente mudou** (comparação explícita), nunca incondicionalmente, para não causar reenvio em loop no sync que roda a cada 15 min.
- Tema de aparência (`app/main/themes.py`) hoje só tem **2** temas implementados (`indigo`, `escuro`) apesar de textos do chatbot mockado mencionarem 4 ("Indigo, Escuro, Verde ou Laranja") — é uma inconsistência conhecida, não um bug a "corrigir" silenciosamente sem confirmar com o usuário qual é a intenção real.
- Chatbot (`/chat`) é mock por regras (`MOCK_CHATBOT=true` por padrão); não há integração real de IA — é um TODO explícito no código, não implemente uma sem alinhar antes.
- Banco de dados via `DATABASE_URL` — `DevelopmentConfig` e `ProductionConfig` (`app/config.py`) leem a mesma env var; só `TestingConfig` é hardcoded pra SQLite `:memory:` (nunca lê `DATABASE_URL`, propositalmente, pra suíte nunca encostar num banco real). `ProductionConfig` normaliza o prefixo antigo `postgres://` pra `postgresql://` (alguns provedores ainda entregam assim) e, quando a URL é Postgres, adiciona `SQLALCHEMY_ENGINE_OPTIONS` com `pool_recycle=600` e `connect_args={"sslmode": "require"}` — `DevelopmentConfig` **não** faz nenhuma dessas duas coisas (usa a URL como veio do `.env` sem normalizar/enriquecer), então um Postgres externo usado em desenvolvimento (`FLASK_CONFIG=development`) precisa já vir com `postgresql://` e `?sslmode=require` na própria string.

## Diretrizes para a IA trabalhando neste código

- Explore o módulo relevante (e o `CLAUDE.md` local, se existir) antes de codar — a maior parte da lógica de negócio não óbvia já está documentada em comentários no próprio código-fonte (em português); leia-os.
- Siga os padrões já existentes (helpers `_..._ou_404`, `bp`, layout `models/routes/forms`, nomenclatura em português) em vez de introduzir um estilo novo.
- Não introduza bibliotecas novas sem necessidade — a stack já cobre auth (Flask-Login/Authlib), formulários (Flask-WTF), e-mail/SMS (Resend via `requests`/Twilio), agendamento (APScheduler).
- `escala` e `plantao` são acoplados de propósito (`app/plantao/sincronizacao.py` importa de `app/escala/models.py`/`routes.py`) — ao mexer no swap de membro (`trocar_atribuicao`) ou no fluxo de notificação (`enviar_notificacoes_da_escala`/`enviar_notificacao_de_alteracao`), lembre que `plantao` reaproveita essas mesmas funções; não duplique.
- Rode `pytest` ao final de qualquer mudança (veja comandos acima); há cobertura de isolamento entre contas (cross-account 404) em quase todo módulo — não quebre esse comportamento. Ao escrever teste envolvendo `TurnoPlantao`/`Escala` "futura", não use `date.today()` sem horário — o fallback de `Escala.data_hora` pra meia-noite faz uma ocorrência "de hoje" já contar como passada a qualquer hora do dia; use `date.today() + timedelta(days=1)`.
- Ao adicionar coluna obrigatória em tabela já populada com dado derivável por linha, siga o padrão de 3 migrations (nullable → backfill → not null) visto no histórico de `migrations/versions/`; se não há dado correlato pra derivar (valor é sempre uma constante arbitrária), um `ADD COLUMN ... DEFAULT` direto é aceitável (ver `889df47f5510`).
- Ao adicionar/alterar regra de negócio relevante, **atualize este CLAUDE.md** (e o `CLAUDE.md` do submódulo afetado) na mesma mudança — este arquivo é a fonte de verdade para futuras sessões de IA neste projeto.

## Diretrizes de contexto por diretório

- [app/auth/CLAUDE.md](app/auth/CLAUDE.md) — login/cadastro tradicional e Google OAuth, confirmação de e-mail por token, validação de domínio (MX).
- [app/escala/CLAUDE.md](app/escala/CLAUDE.md) — Escala (manual e gerada por rodízio): models, geração por template, restrições de UI para escalas geradas, notificações, scheduler único.
- [app/plantao/CLAUDE.md](app/plantao/CLAUDE.md) — motor de rodízio: regra (`TurnoPlantao`), sincronização/materialização em `Escala` real, `plantao_fixado`, ausências.
- [app/comunidade/CLAUDE.md](app/comunidade/CLAUDE.md) — Comunidade, diretório de Membros, autorização de leitura vinculada por e-mail.
- [app/convites/CLAUDE.md](app/convites/CLAUDE.md) — sistema de papéis (Super Admin/Admin da Comunidade/Líder de Ministério/Membro/Convidado), convite por e-mail, hierarquia de quem pode conceder qual papel.
