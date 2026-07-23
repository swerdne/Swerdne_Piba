# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Visão geral do projeto

Sistema de gestão para comunidades religiosas (igrejas), em português do Brasil, back-end em **Flask** (Application Factory + Blueprints + MVC). Um usuário cadastra uma ou mais **Comunidades**, cada comunidade organiza **Ministérios** (Louvor, Mídia, Kids, Coreografia...), e todo evento escalado num Ministério é uma **Escala** (`app/escala`), com uma ou mais **funções** atribuídas a um **Membro** do diretório da comunidade. Uma `Escala` pode ter duas origens:

- **Manual ("Escala Rápida")** — criada com funções pré-definidas por departamento (template), atribuição sempre por escolha manual.
- **Gerada por rodízio** (`app/plantao`) — um `TurnoPlantao` (fila de pessoas + offset + recorrência) é a *regra*; o motor de sincronização de `app/plantao` materializa essa regra em `Escala`/`Funcao` reais numa janela rolante de 90 dias, sempre com 1 única função. Uma vez materializada, a ocorrência é uma `Escala` como qualquer outra — mesma cor no calendário, mesmo relatório, mesma notificação. **Não existe mais uma tela separada de "Plantão"** — só uma tela de configuração da regra (fila/offset/recorrência); ver [app/plantao/CLAUDE.md](app/plantao/CLAUDE.md).

Funcionalidades transversais:
- **Notificações automáticas** 24h/16h antes do evento (e-mail + SMS + sino in-app), via um único job APScheduler (`app/escala/agendador.py`) — cobre escalas manuais e geradas por rodízio igualmente.
- **Chatbot** (`/chat`) — atualmente **mockado** por regex (`app/main/routes.py`), sem integração real de IA (é um TODO explícito no código).
- **Login** tradicional (e-mail/senha) e via **Google OAuth** (Authlib), com mock de OAuth para testes locais sem credenciais reais.
- **Relatório "Escalados"** por comunidade — quem está escalado em qualquer ministério, com filtros de data/departamento/função.

Não existe sistema de papéis (não há admin/regular user). Autorização é toda por **posse do recurso** — ver seção "Autenticação/Autorização".

## Stack

- **Backend:** Flask (Application Factory em [app/\_\_init\_\_.py](app/__init__.py)), Flask-SQLAlchemy, Flask-Migrate (Alembic), Flask-Login, Flask-WTF, Authlib (OAuth), APScheduler, Twilio (SMS), smtplib via `app/emailing.py`.
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
./venv/Scripts/python.exe -m pytest -q tests/test_plantao.py::test_marcar_ausencia_troca_com_o_periodo_seguinte
```

`TestingConfig` usa SQLite `:memory:`, desativa CSRF, força e-mail/SMS/OAuth real desligados e nunca inicia os schedulers APScheduler (`create_app("testing")` pula o bloco de agendadores em [app/\_\_init\_\_.py](app/__init__.py)).

### Migrations

```powershell
./venv/Scripts/python.exe -m flask --app run db migrate -m "descrição em português, snake_case-like"
./venv/Scripts/python.exe -m flask --app run db upgrade
```

Sempre revisar a migration autogerada antes de aplicar — o histórico em `migrations/versions/` mostra o padrão usado ao adicionar uma FK obrigatória em tabela já populada: **coluna nullable → migration de backfill → migration tornando NOT NULL** (3 migrations separadas), nunca um único `alter column not null` direto.

## Estrutura de pastas

```
app/
  __init__.py        # Application Factory: registra extensões, blueprints, context processor de tema, schedulers
  config.py           # Config por ambiente (development/testing/production) via FLASK_CONFIG
  extensions.py        # db, migrate, login_manager, oauth — instâncias soltas (evita import circular)
  notificacoes.py      # Model Notificacao (sino in-app) — fora de qualquer blueprint, ver seção "Regras de negócio" abaixo
  emailing.py          # Envio de e-mail (SMTP) para notificações
  sms.py                # Envio de SMS (Twilio) para notificações
  auth/                 # Login/registro/Google OAuth — models.py (User), routes.py, forms.py
  comunidade/            # Comunidade + Membro (diretório de pessoas) — ver app/comunidade/CLAUDE.md
  ministerio/             # Ministério (organizacional) + calendário mensal
  escala/                  # Escala (manual ou gerada por rodízio) — ver app/escala/CLAUDE.md. Único módulo com agendador.py (o scheduler é único no projeto).
  plantao/                  # Motor de rodízio: TurnoPlantao + sincronizacao.py, materializa em Escala real — ver app/plantao/CLAUDE.md
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
- Helpers privados de autorização seguem o padrão `_<recurso>_do_usuario_ou_404(id)`: `_comunidade_do_usuario_ou_404`, `_ministerio_do_usuario_ou_404`, `_escala_do_usuario_ou_404`, `_funcao_do_usuario_ou_404`, `_turno_do_usuario_ou_404`. Ao adicionar um recurso novo com dono, crie o helper equivalente em vez de inline-checar em cada rota.
- Forms terminam em `Form` (`EscalaForm`, `StatusForm`); `AcaoForm` é um form vazio (só CSRF) reimplementado em cada blueprint para ações simples de POST (excluir, remover, notificar) — não existe uma classe compartilhada.
- Models em PascalCase português; `__tablename__` em snake_case, às vezes prefixado pelo módulo dono para evitar colisão (`escala_membros`, `escala_funcoes`, `turnos_plantao`).
- Templates em `app/templates/<módulo>/<ação>.html`, nome espelhando a view.
- Classes Tailwind nos temas (`app/main/themes.py`) **sempre como string literal completa**, nunca concatenada/f-string — o scanner estático do Tailwind precisa achar a classe no source.

## Autenticação / Autorização

- Flask-Login (`@login_required`) em toda rota que exige usuário logado; `login_manager.login_view = "auth.login"` redireciona não-autenticados.
- **Não há papéis/admin.** Autorização é 100% por posse: cada blueprint sobe a cadeia de FKs até `Comunidade.usuario_id` e compara com `current_user.id`, retornando **404 (não 403)** em caso de descompasso — propositalmente, para não revelar a existência do recurso a quem está adivinhando IDs pela URL. Siga o mesmo padrão (404, não 403) ao adicionar novas rotas de recurso.
- Única exceção: `comunidade._comunidade_visivel_ou_404` dá acesso **somente leitura** a quem não é dono mas tem um `Membro` no diretório da comunidade com `email` igual ao do usuário logado (usado no relatório "Escalados"). Nunca dá acesso de escrita.
- `User` acumula login tradicional e Google OAuth na mesma tabela (`password_hash` nullable para contas só-Google; `check_password` retorna `False` se não houver hash). Vínculo de conta Google a uma conta existente é por e-mail (`auth/routes.py`).
- `MOCK_GOOGLE_OAUTH` permite testar o fluxo Google sem credenciais reais (renderiza `auth/google_mock.html`, simula sucesso/negação/timeout via `?cenario=`); `ProductionConfig` trava esse mock como sempre `False` independentemente da env var — não remova essa trava.

## Regras de negócio importantes

- **Escala manual ("Escala Rápida")** é baseada em template fixo por departamento (`DEPARTAMENTOS` em `app/escala/models.py`), sem rotação automática — atribuição de pessoa a função é sempre manual. Ver [app/escala/CLAUDE.md](app/escala/CLAUDE.md).
- **Rodízio (`app/plantao`)** — regra: `membro = fila[(offset + período) % len(fila)]`. A regra em si (`TurnoPlantao`) nunca guarda quem está escalado em cada data; quem guarda é o motor de sincronização (`app/plantao/sincronizacao.py::sincronizar_turno`), que **materializa** a regra em `Escala`/`Funcao` reais numa janela rolante de 90 dias — essas linhas aparecem no calendário/relatório como qualquer escala manual. `Escala.plantao_fixado` trava uma ocorrência que divergiu da fórmula (ausência remanejada ou edição manual) para o sync não sobrescrevê-la; o histórico (ocorrências já passadas) nunca é tocado pelo sync. Ver [app/plantao/CLAUDE.md](app/plantao/CLAUDE.md) para os detalhes (idempotência obrigatória, renumeração ao mudar `data_inicio`/`recorrência`, exclusão de turno).
- **Notificações automáticas 24h/16h antes** rodam num **único** job APScheduler (`app/escala/agendador.py`), a cada 15 min com janela de tolerância de ±15 min — cobre escalas manuais e geradas por rodízio da mesma forma, já que ambas são `Escala` reais. O mesmo tick também sincroniza todo `TurnoPlantao` ativo antes de checar notificações. Não introduza um scheduler separado para rodízio — a materialização e a notificação são deliberadamente uma coisa só agora.
- O scheduler só sobe fora do modo `testing`, e há proteção contra o reloader do Flask iniciar o job duas vezes (checagem de `WERKZEUG_RUN_MAIN`). **Não há proteção contra múltiplos workers** (gunicorn etc.) duplicando notificações — comentário explícito no código sinalizando isso como problema conhecido caso o deploy mude de processo único para multi-worker.
- E-mail/SMS falhando nunca derruba a request (exceptions `EmailNaoEnviadoError`/`SmsNaoEnviadoError` são capturadas e contabilizadas) — mantenha esse comportamento ao mexer em `emailing.py`/`sms.py`.
- Notificação in-app (`Notificacao`) só é criada quando o `email` do `Membro` escalado bate com o `email` de um `User` cadastrado — é um canal extra, não substitui e-mail/SMS.
- Editar data/horário de uma `Escala` (manual ou via edição do `TurnoPlantao` que a gerou) reseta os timestamps `notificado_24h_em`/`notificado_16h_em` (para o scheduler reenviar) e dispara notificação proativa de alteração para quem já estava escalado — mas o reset só acontece se o valor **realmente mudou** (comparação explícita), nunca incondicionalmente, para não causar reenvio em loop no sync que roda a cada 15 min.
- Tema de aparência (`app/main/themes.py`) hoje só tem **2** temas implementados (`indigo`, `escuro`) apesar de textos do chatbot mockado mencionarem 4 ("Indigo, Escuro, Verde ou Laranja") — é uma inconsistência conhecida, não um bug a "corrigir" silenciosamente sem confirmar com o usuário qual é a intenção real.
- Chatbot (`/chat`) é mock por regras (`MOCK_CHATBOT=true` por padrão); não há integração real de IA — é um TODO explícito no código, não implemente uma sem alinhar antes.

## Diretrizes para a IA trabalhando neste código

- Explore o módulo relevante (e o `CLAUDE.md` local, se existir) antes de codar — a maior parte da lógica de negócio não óbvia já está documentada em comentários no próprio código-fonte (em português); leia-os.
- Siga os padrões já existentes (helpers `_..._ou_404`, `bp`, layout `models/routes/forms`, nomenclatura em português) em vez de introduzir um estilo novo.
- Não introduza bibliotecas novas sem necessidade — a stack já cobre auth (Flask-Login/Authlib), formulários (Flask-WTF), e-mail/SMS (smtplib/Twilio), agendamento (APScheduler).
- `escala` e `plantao` são acoplados de propósito (`app/plantao/sincronizacao.py` importa de `app/escala/models.py`/`routes.py`) — ao mexer no swap de membro (`trocar_atribuicao`) ou no fluxo de notificação (`enviar_notificacoes_da_escala`/`enviar_notificacao_de_alteracao`), lembre que `plantao` reaproveita essas mesmas funções; não duplique.
- Rode `pytest` ao final de qualquer mudança (veja comandos acima); há cobertura de isolamento entre contas (cross-account 404) em quase todo módulo — não quebre esse comportamento. Ao escrever teste envolvendo `TurnoPlantao`/`Escala` "futura", não use `date.today()` sem horário — o fallback de `Escala.data_hora` pra meia-noite faz uma ocorrência "de hoje" já contar como passada a qualquer hora do dia; use `date.today() + timedelta(days=1)`.
- Ao adicionar coluna obrigatória em tabela já populada com dado derivável por linha, siga o padrão de 3 migrations (nullable → backfill → not null) visto no histórico de `migrations/versions/`; se não há dado correlato pra derivar (valor é sempre uma constante arbitrária), um `ADD COLUMN ... DEFAULT` direto é aceitável (ver `889df47f5510`).
- Ao adicionar/alterar regra de negócio relevante, **atualize este CLAUDE.md** (e o `CLAUDE.md` do submódulo afetado) na mesma mudança — este arquivo é a fonte de verdade para futuras sessões de IA neste projeto.

## Diretrizes de contexto por diretório

- [app/escala/CLAUDE.md](app/escala/CLAUDE.md) — Escala (manual e gerada por rodízio): models, geração por template, restrições de UI para escalas geradas, notificações, scheduler único.
- [app/plantao/CLAUDE.md](app/plantao/CLAUDE.md) — motor de rodízio: regra (`TurnoPlantao`), sincronização/materialização em `Escala` real, `plantao_fixado`, ausências.
- [app/comunidade/CLAUDE.md](app/comunidade/CLAUDE.md) — Comunidade, diretório de Membros, autorização de leitura vinculada por e-mail.
