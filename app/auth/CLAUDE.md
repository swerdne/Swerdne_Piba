# app/auth — Login, cadastro e confirmação de e-mail

Contexto local. Visão geral do projeto e convenções gerais: [../../CLAUDE.md](../../CLAUDE.md).

## Responsabilidade

Autenticação: cadastro/login tradicional (e-mail/senha) e Google OAuth (Authlib), na mesma tabela `User`. Desde a introdução da confirmação de e-mail, o cadastro tradicional só vira uma conta **ativa** (que consegue logar) depois que a pessoa clica no link enviado por e-mail — Google não passa por esse fluxo, porque o próprio Google já validou a posse do e-mail no consentimento OAuth.

## Confirmação de e-mail (cadastro tradicional)

Campos em `User` (`app/auth/models.py`): `email_confirmado` (bool), `token_confirmacao` (nullable, único), `token_confirmacao_expira_em` (nullable, `HORAS_VALIDADE_TOKEN_CONFIRMACAO = 24`). `User.gerar_token_confirmacao()` cria um token novo (invalida qualquer link antigo, já que troca o valor) e `User.token_confirmacao_valido(token)` confere igualdade (`secrets.compare_digest`, evita timing attack) **e** validade do prazo.

- `default=False` (Python/SQLAlchemy) pro cadastro tradicional sempre nascer não-confirmado; `server_default=true()` (SQL, só usado pela migração `34872613344e`) dá como confirmadas as contas que já existiam antes dessa coluna existir — não tem como confirmar retroativamente quem já estava cadastrado, então essas contas foram "perdoadas" pra não travar ninguém de repente. Contas Google (novas ou vinculando a uma conta tradicional já existente) são marcadas `email_confirmado=True` no momento da criação/vínculo, em `auth.routes.google_callback` — nunca passam pelo token.

### Fluxo (`app/auth/routes.py`)

1. `POST /auth/register` — valida o form (ver abaixo), cria o `User` (`email_confirmado=False`), **não loga** (mudança de comportamento importante: antes logava direto), chama `_enviar_email_de_confirmacao` e renderiza `auth/verifique_email.html` (não redireciona) com o e-mail cadastrado.
2. `GET /auth/confirmar-email/<token>` — busca `User` pelo token. Token inexistente → flash de erro + redireciona pro login. Token existe mas expirado (`token_confirmacao_valido` retorna `False`) → re-renderiza `verifique_email.html` com `link_expirado=True` (oferece reenvio). Token válido → `email_confirmado=True`, limpa o token, **loga** (`login_user`) e redireciona via `_redirecionar_apos_login()` — é o único lugar que loga depois do cadastro tradicional.
3. `POST /auth/reenviar-confirmacao` (`ReenviarConfirmacaoForm`, e-mail vem oculto/pré-preenchido no template, não digitado de novo) — gera token novo e reenvia. Conta já confirmada → avisa e não reenvia nada. E-mail não cadastrado → avisa que não achou.
4. `POST /auth/login` — se a senha bate mas `email_confirmado` é `False`, **não loga**: renderiza `verifique_email.html` (mesmo padrão do registro) em vez de `login.html`, com o formulário de reenvio.

`_enviar_email_de_confirmacao` segue o mesmo padrão de `app/convites/routes.py::_enviar_email_de_convite`: nunca deixa falha de envio (`EmailNaoEnviadoError`) quebrar a request — o token já foi salvo, só avisa e mostra o link pra copiar manualmente.

### Validação de domínio (`app/auth/dominio_email.py`)

`RegisterForm.validate_email` (`app/auth/forms.py`), além de checar unicidade, confere se o domínio do e-mail tem registro MX (ou, na falta, um registro A — RFC 5321) via `dominio_aceita_email(dominio)` (biblioteca `dnspython`). Erro de rede/timeout do nosso lado (não do domínio) **não bloqueia** o cadastro — só instabilidade momentânea de DNS não deveria barrar alguém com e-mail legítimo. Controlado por `VALIDAR_DOMINIO_EMAIL` (`app/config.py`) — `True` por padrão, `False` em `TestingConfig` (suíte não pode depender de DNS real).

### `tests/conftest.py` — fixtures `logged_in_client`/`outro_logged_in_client`

Registro sozinho **não loga mais ninguém** — por isso essas fixtures (usadas por quase todo o resto da suíte pra simular "uma conta logada") não podem mais só dar POST em `/auth/register`. `_registrar_e_confirmar(cliente, app, username, email)` registra, busca o `token_confirmacao` direto no banco (o e-mail de verdade nunca sai em teste — `RESEND_API_KEY` é `None` em `TestingConfig`) e visita `GET /auth/confirmar-email/<token>`, que é quem de fato loga. Ao adicionar um teste novo que precise de uma conta logada "do zero" (não via essas fixtures), use esse mesmo helper em vez de só `POST /auth/register`.

## Mostrar/ocultar senha

Qualquer botão com `data-toggle-senha="<id-do-input>"` (mais os dois `<svg>` internos marcados `data-icone-aberto`/`data-icone-fechado`) alterna o input entre `type="password"`/`text` — handler genérico em `app/static/js/main.js::habilitarToggleSenha`, funciona em qualquer tela sem JS por página. Usado em login/cadastro (`password`, e `confirm` no cadastro).

## Testes

`tests/test_auth.py` cobre: hashing de senha, `/auth/sessao-atual` (detecção de troca de sessão entre abas), e o fluxo de confirmação inteiro — registro não loga, confirmação loga e redireciona, token inválido/expirado, login bloqueado sem confirmar, reenvio (token novo, já confirmado, e-mail inexistente), e recusa de domínio sem MX (via `monkeypatch` em `app.auth.forms.dominio_aceita_email`, já que `VALIDAR_DOMINIO_EMAIL` fica desligado por padrão em teste).
