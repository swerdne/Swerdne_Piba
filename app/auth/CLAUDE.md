# app/auth — Login e cadastro

Contexto local. Visão geral do projeto e convenções gerais: [../../CLAUDE.md](../../CLAUDE.md).

## Responsabilidade

Autenticação: cadastro/login tradicional (e-mail/senha) e Google OAuth (Authlib), na mesma tabela `User`. **Não há confirmação de e-mail** — cadastro tradicional loga direto (`POST /auth/register` → `login_user` → `_redirecionar_apos_login()`), igual ao fluxo do Google. Já existiu um fluxo de confirmação por link (token + e-mail); foi desativado por decisão do usuário — ver "Ex-confirmação de e-mail" abaixo antes de reativar algo parecido.

## Segurança

- **Rate limiting** (`app/extensions.py::limiter`, Flask-Limiter): `/auth/login` 10/min, `/auth/register` 5/hora, tudo por IP. Armazenamento em memória (mesma ressalva do scheduler único sobre múltiplos workers — não há storage compartilhado configurado). Desligado em teste via `RATELIMIT_ENABLED=False` (`TestingConfig`), senão a suíte estouraria o limite (`_registrar` roda em quase todo teste, ver `tests/conftest.py`). Página de erro 429 estilizada em `app/errors.py`.
- **`SECRET_KEY`**: `ProductionConfig` exige a env var de verdade e falha ao subir (`RuntimeError`) se ausente — não usa mais o fallback fraco da classe base `Config` (`"troque-esta-chave"`) em produção, que ficaria exposto no código-fonte público.
- **Cookies de sessão**: `SESSION_COOKIE_SECURE`/`SAMESITE` e `REMEMBER_COOKIE_SECURE`/`SAMESITE` setados em `ProductionConfig` (só trafegam por HTTPS).
- **Senha mínima**: 8 caracteres (`RegisterForm.password`).

## Ex-confirmação de e-mail (desativada)

Existiu um fluxo completo de confirmação por link (token + e-mail via Resend, rotas `GET /auth/confirmar-email/<token>` e `POST /auth/reenviar-confirmacao`, template `auth/verifique_email.html`) — **removido a pedido do usuário** (cadastro tradicional passou a bloquear login até clicar no link, o que gerou fricção/problemas reais). As colunas `email_confirmado`, `token_confirmacao`, `token_confirmacao_expira_em` continuam em `User` (`app/auth/models.py`) **sem uso ativo**, de propósito — evita uma migration destrutiva sem necessidade. Toda conta nova (tradicional ou Google) nasce com `email_confirmado=True`, só por consistência de dado, nada mais lê esse campo. Se for reativar esse fluxo no futuro, o histórico de como funcionava está no commit que o removeu.

### Validação de domínio (`app/auth/dominio_email.py`)

`RegisterForm.validate_email` (`app/auth/forms.py`), além de checar unicidade, confere se o domínio do e-mail tem registro MX (ou, na falta, um registro A — RFC 5321) via `dominio_aceita_email(dominio)` (biblioteca `dnspython`). Erro de rede/timeout do nosso lado (não do domínio) **não bloqueia** o cadastro — só instabilidade momentânea de DNS não deveria barrar alguém com e-mail legítimo. Controlado por `VALIDAR_DOMINIO_EMAIL` (`app/config.py`) — `True` por padrão, `False` em `TestingConfig` (suíte não pode depender de DNS real).

### `tests/conftest.py` — fixtures `logged_in_client`/`outro_logged_in_client`

`_registrar(cliente, username, email)` só dá `POST /auth/register` — registro já loga direto. Ao adicionar um teste novo que precise de uma conta logada "do zero" (não via essas fixtures), use esse mesmo helper.

## Mostrar/ocultar senha

Qualquer botão com `data-toggle-senha="<id-do-input>"` (mais os dois `<svg>` internos marcados `data-icone-aberto`/`data-icone-fechado`) alterna o input entre `type="password"`/`text` — handler genérico em `app/static/js/main.js::habilitarToggleSenha`, funciona em qualquer tela sem JS por página. Usado em login/cadastro (`password`, e `confirm` no cadastro).

## Testes

`tests/test_auth.py` cobre: hashing de senha, cadastro (loga direto), login após registro/logout, `/auth/sessao-atual` (detecção de troca de sessão entre abas), e recusa de domínio sem MX (via `monkeypatch` em `app.auth.forms.dominio_aceita_email`, já que `VALIDAR_DOMINIO_EMAIL` fica desligado por padrão em teste).
