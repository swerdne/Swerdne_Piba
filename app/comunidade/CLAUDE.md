# app/comunidade — Comunidade e diretório de membros

Contexto local. Visão geral do projeto e convenções gerais: [../../CLAUDE.md](../../CLAUDE.md).

## Responsabilidade

`Comunidade` é a raiz de posse de todo o resto do sistema: todo `Ministerio`, `Escala`, `TurnoPlantao` e `Membro` pertence, direta ou indiretamente, a uma comunidade — e comunidades são independentes entre si (não há dados compartilhados entre comunidades de donos diferentes). É aqui também que fica o **diretório de pessoas** (`Membro`, definido em `app/escala/models.py` mas usado tanto por `escala` quanto por `plantao`) e o relatório cross-ministério "Escalados".

## Models

`Comunidade` (`comunidades`): `usuario_id` (FK do criador original — metadado histórico, ver abaixo), `nome`, `descricao`, `imagem`, `criada_em`. Criada via `criar_comunidade(...)`, que também insere automaticamente uma linha `UsuarioComunidade(papel="admin")` pro criador.

`UsuarioComunidade` (papel `admin`|`membro` por conta) e a lógica de quem pode gerenciar/ver uma Comunidade vivem em `app/convites/CLAUDE.md` — leia lá antes de mexer em autorização deste módulo. Resumo rápido: `_comunidade_do_usuario_ou_404` (escrita, admin) e `_comunidade_visivel_ou_404` (leitura: admin, papel=membro, OU `Membro` do diretório vinculado por e-mail) delegam pra `_eh_admin_da_comunidade`/`_eh_membro_da_comunidade`, ambas definidas neste arquivo (`comunidade/routes.py`) e reaproveitadas por `ministerio`/`escala`/`plantao`.

`Membro` **não está** em `app/comunidade/models.py` — está em `app/escala/models.py` (tabela `escala_membros`), importado aqui. Se for procurar o model do diretório de pessoas, é lá. **Não confundir com `UsuarioComunidade`**: `Membro` é o diretório de pessoas escaláveis (nome/telefone/email, sem conta obrigatória); `UsuarioComunidade` é papel de uma **conta com login**. Os dois só se cruzam por coincidência de e-mail, quando faz sentido (ver `_comunidade_visivel_ou_404`).

## Tutorial guiado (spotlight)

`comunidade.detalhe` mostra um tour guiado (destaque com "spotlight" sobre elementos reais da tela, não um modal de slides) na **primeira vez** que a conta abre uma Comunidade — nunca mais depois disso, pra conta inteira (não é por comunidade). Controlado por `User.tutorial_comunidade_visto` (bool, `app/auth/models.py`).

- Passos em `PASSOS_TUTORIAL_COMUNIDADE` (`comunidade/routes.py`), casando por `seletor` CSS com atributos `data-tutorial="..."` no template (`convites`, `membros`, `escalados`, `novo-ministerio`); `seletor: None` = passo centralizado, sem destacar nada (boas-vindas/conclusão).
- Motor genérico em `app/static/js/main.js` (IIFE sem nome no topo) — lê um `<script type="application/json" id="tutorial-dados">` (**sempre presente** no HTML, mesmo depois de já visto) com `{urlConcluir, csrf, passos, autoIniciar}`. `autoIniciar` (= `not User.tutorial_comunidade_visto`) controla só o disparo automático ao carregar a página — reaproveitável em qualquer outra tela só adicionando esse bloco + atributos `data-tutorial`, sem JS novo por página.
- Botão "Rever tutorial" (ícone `?`) no cabeçalho — `[data-tutorial-reiniciar]`, sempre visível, dispara o mesmo motor a qualquer momento independente de `autoIniciar`/já ter sido visto.
- `POST /tutorial-comunidade-visto` (`app/main/routes.py`) marca visto — chamado via `fetch` quando a pessoa clica "Pular"/"Concluir" ou aperta Esc (inclusive numa reexecução manual, idempotente). Usa `generate_csrf()` direto na rota (não o global Jinja `csrf_token()`, que só existe se `CSRFProtect(app)` for registrado globalmente — não é o caso neste projeto, que usa `FlaskForm` por rota).

## Regras específicas

- `GET/POST /comunidade/<id>/papeis` (`papeis`) — tela de gestão de papéis: lista admins/membros atuais + convites pendentes, formulário pra convidar por e-mail (`app/convites`). Só admin chega aqui (`_comunidade_do_usuario_ou_404`).
- `POST /comunidade/<id>/excluir` (`excluir_comunidade`, botão no header de `comunidade/detalhe.html`) apaga a comunidade inteira — mesmo padrão de `ministerio.excluir_ministerio`: cascade do ORM (`cascade="all, delete-orphan"` em `Comunidade.ministerios`, `Comunidade.membros` e `Comunidade.papeis_usuarios`) apaga junto todos os `Ministerio` (e, por tabela, todas as `Escala`/`Funcao`/`TurnoPlantao` deles), todo o diretório de `Membro` e toda linha de `UsuarioComunidade` — nada é preservado como histórico, diferente de `plantao.excluir_turno`. Exige admin (`_comunidade_do_usuario_ou_404`) e confirmação client-side (`confirm(...)`), como toda ação destrutiva do projeto.
- `POST /comunidade/excluir-varias` (`excluir_varias`) — exclusão em lote a partir de `comunidade/lista.html` ("Minhas comunidades"): checkboxes com `name="comunidade_ids"`, filtra cada id por `_eh_admin_da_comunidade` individualmente (nunca confia na lista recebida — um form adulterado com id de outra conta simplesmente é ignorado, sem 404 pra não travar o resto do lote). UI genérica de "modo seleção" em `app/static/js/main.js` (`data-selecao-*`), reaproveitada também em `escala.excluir_varias`.
- Exclusão de `Membro` é bloqueada se ele estiver escalado em algum lugar: `Funcao.query.filter_by(membro_id=...).count() > 0` impede a exclusão (evita quebrar referências históricas em escalas já criadas). Essa checagem não se aplica à exclusão da comunidade inteira acima, que apaga tudo incondicionalmente.
- `GET /comunidade/<id>/escalados` junta `Funcao → Escala → Ministerio`, com filtros `data_de`, `data_ate`, `departamento`, `funcao` — é o único relatório cross-ministério do sistema; ao adicionar um novo tipo de escalação (ex. se `plantao` ganhar um relatório equivalente), considere se deve entrar aqui também em vez de criar um relatório paralelo.
- Upload de logo (`_salvar_logo`/`_remover_logo_antiga`) usa nome de arquivo UUID em `COMUNIDADE_UPLOAD_FOLDER` — mesmo padrão usado por avatar de usuário (`app/main`) e logo de ministério.

## Testes

`tests/test_comunidade.py`: CRUD, estado vazio, isolamento cross-account (404), diretório de membros (adicionar/excluir, exclusão bloqueada se escalado), filtros do relatório `/escalados`, e especificamente o comportamento de visibilidade por vínculo de e-mail (`test_membro_vinculado_por_email_ve_escalados_de_leitura`, `test_terceiro_sem_vinculo_nao_ve_escalados`) — são os testes de referência para não quebrar essa regra ao mexer em autorização deste módulo.
