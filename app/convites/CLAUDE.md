# app/convites — papéis por convite (Super Admin → Admin da Comunidade → Líder de Ministério → Membro → Convidado)

Contexto local. Visão geral do projeto e convenções gerais: [../../CLAUDE.md](../../CLAUDE.md).

## Responsabilidade

Antes deste módulo, autorização era 100% por posse (`Comunidade.usuario_id`) — sem papéis, sem multi-usuário por comunidade. Este módulo introduz papel **contextual** (a mesma pessoa pode ser admin numa Comunidade e membro comum noutra, ou líder de um Ministério e membro de outro), concedido **sempre via convite por e-mail aceito** — exceto o admin automático de quem cria a comunidade (ver `criar_comunidade` em `app/comunidade/models.py`).

Hierarquia (do maior pro menor alcance):
- **Super Admin** (`User.eh_super_admin`) — acesso total à plataforma, bypassa toda checagem de posse/papel. **Nunca** atribuível por convite — só via `flask criar-super-admin <email>` (comando de terminal, ver `app/__init__.py`), que exige acesso ao servidor. Não é uma opção em nenhum formulário de convite.
- **Admin da Comunidade** (`UsuarioComunidade.papel == "admin"`) — gerencia ministérios, membros e permissões daquela Comunidade. Autoridade cascata: também age como líder em **qualquer** Ministério dela, mesmo sem uma linha própria em `UsuarioMinisterio`.
- **Líder de Ministério** (`UsuarioMinisterio.papel == "lider"`) — gerencia escalas, turnos de rodízio e membros daquele Ministério específico. Não tem autoridade sobre o Ministério em si (não edita/exclui) nem sobre outros Ministérios da mesma Comunidade.
- **Membro** (`UsuarioComunidade.papel == "membro"` ou `UsuarioMinisterio.papel == "membro"`) — participa, visualiza (leitura), sem permissão administrativa. Pode marcar o **próprio** status numa `Funcao` em que está escalado (ver `escala.routes.atualizar_status`), mesmo sem ser líder/admin.
- **Convidado** — vínculo pontual a 1 única `Escala`/`Funcao`, mecanismo **separado e já existente** (`Funcao.eh_convidado`, busca+vínculo instantâneo por e-mail, sem convite/aceite) — ver [app/escala/CLAUDE.md](../escala/CLAUDE.md). Este módulo **não** cobre esse caso.

## Models

- `Convite` (`convites`, `app/convites/models.py`) — `escopo_tipo` (`"comunidade"`|`"ministerio"`) + `escopo_id` (aponta pra `Comunidade.id` ou `Ministerio.id` conforme o tipo — não dá pra usar uma FK real de banco pra 2 tabelas diferentes; resolvido em Python via as properties `comunidade`/`ministerio`/`escopo_obj`/`escopo_nome`), `papel`, `email` (alvo — **não exige conta pré-existente**, ver `usuario_ja_cadastrado`), `convidado_por_id`, `token` (unico, `secrets.token_urlsafe(32)`), `status` (`pendente`|`aceito`|`recusado`), `criado_em`/`respondido_em`. `criar_ou_reenviar_convite(...)` é find-or-create: reaproveita um convite `pendente` já existente pro mesmo escopo+e-mail (atualiza papel/token/quem convidou) em vez de acumular duplicados.
- `UsuarioComunidade` (`app/comunidade/models.py`) — `usuario_id`, `comunidade_id`, `papel` (`admin`|`membro`), `UniqueConstraint(usuario_id, comunidade_id)`.
- `UsuarioMinisterio` (`app/ministerio/models.py`) — `usuario_id`, `ministerio_id`, `papel` (`lider`|`membro`), `UniqueConstraint(usuario_id, ministerio_id)`. **Não** tem papel `convidado` — ver acima.
- `User.eh_super_admin` (`app/auth/models.py`) — bool, default `False`.

**Enquanto pendente, o convite não concede NENHUM acesso** — a linha de papel só é criada no aceite (ver `_aplicar_papel` em `routes.py`).

## Quem pode convidar com qual papel (hierarquia)

- **Admin da Comunidade** — convida `admin`/`membro` na própria Comunidade (`comunidade.routes.papeis`) e `lider`/`membro` em **qualquer** Ministério dela (`ministerio.routes._papeis_convidaveis_no_ministerio`, via `_eh_admin_da_comunidade`) — nunca `Super Admin` (nem é uma choice em lugar nenhum).
- **Líder de Ministério** (que não seja também admin da comunidade) — convida só `membro`, só no **seu** Ministério. Não pode nomear outro líder nem admin de comunidade.
- Cada formulário de convite (`ConvidarForm.papel`) monta as `choices` dinamicamente conforme quem está pedindo (`_papeis_convidaveis_no_ministerio`) — **e a rota confirma de novo no servidor** (`if form.papel.data not in papeis_permitidos: abort`), defesa em profundidade contra um POST montado à mão fora das choices do form. WTForms `SelectField` com `validate_choice=True` (padrão) já rejeita sozinho qualquer valor fora das `choices`, incluindo tentativas de convidar como `"super_admin"` (que nunca é uma choice válida — estruturalmente impossível pelo formulário).

## Fluxo de envio (`comunidade.routes.papeis` / `ministerio.routes.papeis`)

`GET/POST /comunidade/<id>/papeis` e `GET/POST /ministerio/<id>/papeis` — cada um no blueprint dono do escopo (não em `app/convites`, que só cuida do lado de quem recebe). Listam papéis atuais + convites pendentes, e no POST chamam `criar_ou_reenviar_convite(...)` + `_enviar_email_de_convite(convite)` (`app/convites/routes.py`, compartilhada pelos dois — e-mail simples com o link `convites.ver_convite`; falha de envio nunca quebra a request, mesmo padrão de `app/emailing.py` em todo o projeto — o convite já foi salvo, só avisa que o e-mail pode não ter chegado e mostra o link pra compartilhar manualmente).

`remover_papel`/`cancelar_convite` (em cada blueprint) — um líder (não-admin) só remove papéis que ele mesmo poderia conceder (`membro`), mesma checagem de `papeis_permitidos` do envio — não pode expulsar outro líder.

## Fluxo de recebimento (`app/convites/routes.py`)

`GET /convite/<token>` (`ver_convite`, **pública**, sem `@login_required` — precisa funcionar pra quem ainda nem tem conta):
- Convite já respondido (`aceito`/`recusado`) → tela final, sem ação.
- Anônimo → guarda a URL do convite em `session["proximo_apos_login"]` (ver abaixo) e mostra "entrar" ou "criar conta" (só oferece "criar conta" se **não** existir `User` com esse e-mail, `Convite.usuario_ja_cadastrado`).
- Logado com e-mail **diferente** do convite → avisa e oferece sair (nunca deixa aceitar com a conta errada).
- Logado com e-mail igual → botões aceitar/recusar.

`POST /convite/<token>/aceitar` — revalida `status == pendente` e e-mail batendo (nunca confia só no que a tela mostrou), `_aplicar_papel` cria **ou atualiza** (`get-or-create`, não duplica) a linha `UsuarioComunidade`/`UsuarioMinisterio`, marca `status=aceito`. `POST /convite/<token>/recusar` — só marca `status=recusado`, não cria nada.

### `next` após login/registro/Google

`session["proximo_apos_login"]` (setado em `ver_convite`) é consumido por `auth.routes._redirecionar_apos_login()` — chamado no sucesso de `login`, `register` **e** `google_callback` (o valor sobrevive ao round-trip pro Google porque é sessão de servidor, não querystring). `pop` de propósito: o destino só vale uma vez. Cai no dashboard se não havia nenhum destino guardado. Ao adicionar um novo fluxo que precise "voltar pra onde a pessoa estava" após autenticar, reaproveite esse mecanismo em vez de inventar um novo.

## Como os helpers de posse passaram a consultar papel

Nenhuma rota de conteúdo (escala, turno, membro do diretório) foi reescrita uma por uma — os helpers centrais (`_<recurso>_do_usuario_ou_404`) é que passaram a consultar papel por baixo, então toda rota que já os usava herdou a hierarquia automaticamente:

- `comunidade.routes._eh_admin_da_comunidade(comunidade, usuario)` — `usuario.eh_super_admin` OU `comunidade.usuario_id == usuario.id` (dono original, mantido como metadado histórico — toda comunidade **existente** antes desta migração foi *backfillada* com uma linha `UsuarioComunidade(papel=admin)` pro dono, ver `migrations/versions/d78e7cdd121e_*.py`, então na prática isso é redundante pra dados novos, só relevante como fallback) OU `UsuarioComunidade(papel=admin)`. Usado por `_comunidade_do_usuario_ou_404` (estrito) e `_comunidade_visivel_ou_404` (+ `UsuarioComunidade(papel=membro)`, além do vínculo por e-mail já existente).
- `ministerio.routes._eh_lider_do_ministerio(ministerio, usuario)` — `_eh_admin_da_comunidade(ministerio.comunidade, usuario)` (cascata) OU `UsuarioMinisterio(papel=lider)`. `_eh_membro_do_ministerio` — só `UsuarioMinisterio(papel=membro)`.
- **Três tiers** de acesso a Ministério (`ministerio.routes`): `_ministerio_do_usuario_ou_404` (estrito, só admin — exclusivo pro CRUD do Ministério: `editar`/`excluir_ministerio`), `_ministerio_gerenciavel_ou_404` (admin OU líder — conteúdo: `escala.nova`, `plantao.nova`, e tudo que desce da cadeia `_escala_do_usuario_ou_404`/`_funcao_do_usuario_ou_404`/`_turno_do_usuario_ou_404`, todos importando `_eh_lider_do_ministerio` de `ministerio.routes`), `_ministerio_visivel_ou_404` (admin OU líder OU membro, retorna `(ministerio, pode_gerenciar)` — usado por `detalhe`/`calendario`, o template esconde ações de escrita quando `pode_gerenciar` é falso).
- `escala.routes._escala_visivel_ou_404` — `pode_gerenciar` (líder/admin) OU membro do ministério (leitura) OU convidado por e-mail (leitura, mecanismo antigo, escopado a 1 `Escala`) — variável de template continua se chamando `eh_dono` nos templates existentes (não renomeada, pra não reescrever `escala/detalhe.html` inteiro), mas semanticamente agora significa "pode gerenciar".
- `escala.routes.atualizar_status` é a **única** exceção que não passa pelos helpers acima: além de líder/admin, o próprio escalado (`Funcao.membro.email` == e-mail da conta logada) pode marcar seu status, sem precisar de nenhum papel formal — ver `escala/routes.py` e o `{% elif funcao.id in formularios_status %}` em `escala/detalhe.html`.

## Testes

`tests/test_papeis.py`: admin automático do criador, matriz de convite (admin convida admin/membro/líder; líder só convida membro, rejeitado tanto na UI quanto no servidor se tentar mais que isso), `super_admin` nunca é uma choice válida, aceitar cria/atualiza papel e dá acesso, recusar não cria nada, e-mail errado e convite já respondido são rejeitados, tela pública mostra "criar conta" só quando não existe `User` com aquele e-mail, admin da comunidade gerencia ministério sem linha própria (cascata), membro vê mas não gerencia (sem botão "nova escala", 404 em rotas de escrita), membro escalado marca o próprio status, não-membro recebe 404 em Ministério/Escala, bootstrap via CLI (`app.test_cli_runner()`) cria e recusa e-mail sem conta, Super Admin acessa qualquer Comunidade sem nenhuma linha de papel.
