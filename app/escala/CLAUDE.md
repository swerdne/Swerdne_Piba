# app/escala — Escala Rápida

Contexto local. Visão geral do projeto e convenções gerais: [../../CLAUDE.md](../../CLAUDE.md).

## Responsabilidade

Escala de um evento (culto, ensaio...) dentro de um Ministério: um conjunto de **funções**, cada uma atribuída a um **Membro** do diretório da comunidade. Uma `Escala` tem duas origens possíveis:

- **Manual ("Escala Rápida")** — criada com um conjunto fixo de funções padrão por departamento, atribuição sempre por escolha manual (`plantao_turno_id is None`).
- **Gerada por rodízio** — criada e mantida automaticamente pelo motor de sincronização de [app/plantao](../plantao/CLAUDE.md) (`plantao_turno_id`/`plantao_periodo` preenchidos). Com 1 `Funcao` **por integrante da equipe** sorteada naquele período (1 para rotação individual, mais de 1 quando a equipe tem várias pessoas — todas na mesma `Escala`, mesma data). Ver `Escala.plantao_fixado` abaixo e o CLAUDE.md de `plantao` para os detalhes do motor — este módulo só precisa saber que essas `Escala` existem e são, pra todo o resto (calendário, relatório, notificação), indistinguíveis de uma manual.

## Models (`models.py`)

- `Membro` (`escala_membros`) — pessoa do diretório da comunidade (`comunidade_id` FK). Reaproveitado por `plantao` (fila de rodízio usa o mesmo `Membro`). `iniciais` = avatar de 1-2 letras.
- `Escala` (`escalas`) — um evento: `ministerio_id`, `nome`, `departamento` (chave de `DEPARTAMENTOS`), `data`, `horario`, `notificado_24h_em`/`notificado_16h_em` (timestamps que o scheduler usa para não reenviar). `data_hora` combina `data`+`horario`. `plantao_turno_id`/`plantao_periodo` (nullable, `UniqueConstraint` no par) marcam se/qual ocorrência de rodízio gerou essa escala; `plantao_fixado` trava uma ocorrência gerada que divergiu da fórmula pura (alguém removido/reatribuído manualmente, ou edição de nome/data) para o sync de `plantao` não sobrescrever. `turno_plantao_origem_id` (nullable, direção OPOSTA de `plantao_turno_id`) marca que esta Escala **foi a origem** de um `TurnoPlantao` (ver "Escala como origem de rodízio" abaixo). `cor_selecionada` (nullable, chave de `CORES_DISPONIVEIS`) sobrepõe a cor padrão do departamento — lida via a property `cor`, que já é usada por toda a UI (lista de escalas, calendário do Ministério, badge de detalhe), então escolher uma cor aqui já reflete em todo lugar sem mudança adicional.
- `Funcao` (`escala_funcoes`) — uma linha da grade: `escala_id`, `nome`, `ordem`, `tipo` (`"funcao"` normal ou `"subcabecalho"` — linha só de rótulo, sem `membro_id`, usada para agrupar visualmente), `membro_id` (nullable = vaga aberta), `status` (`nao_notificado`/`confirmado`/`presente`/`troca_solicitada`).

`DEPARTAMENTOS` define a lista de funções padrão por departamento (ex.: Louvor → Backing Vocal, Baixo, Bateria, Guitarra, Ministro de Louvor, Teclado, Violão). `MENSAGENS_POR_DEPARTAMENTO` define o texto de notificação por departamento, com fallback `_padrao`.

## Convidado — vincular uma conta (`User`) já existente a uma `Funcao`

Além de escolher um `Membro` do diretório, o dono pode buscar uma conta já cadastrada na plataforma (por nome/username/e-mail) e vinculá-la a uma `Funcao` como participação pontual, sem duplicar cadastro:

- `GET /escala/funcao/<funcao_id>/buscar-usuario?q=...` — exige dono da função (`_funcao_do_usuario_ou_404`); `q` com menos de 2 caracteres devolve `[]` de propósito (evita varredura trivial); busca `User` por `name`/`username`/`email` (`ilike`), limita a 8, devolve só `{"id", "label"}` (nunca campos sensíveis).
- `POST /escala/funcao/<funcao_id>/adicionar-convidado` — exige dono, CSRF via `AcaoForm` vazio + `usuario_id` lido direto de `request.form` (escolha vem da busca dinâmica, não de um `SelectField`). Faz find-or-create de `Membro` por `comunidade_id` + `email` do `User` (reaproveita se já existir de uma escalação anterior — é assim que "sem duplicar cadastro" é garantido), atribui à função (`membro_id`, `status=STATUS_PADRAO`, `notificado_em=None`, **`eh_convidado=True`**) e chama `_fixar_se_gerada_por_rodizio` como qualquer atribuição manual.
- `Funcao.eh_convidado` (bool) só controla o selo visual "Convidado" no template — notificação e rodízio continuam operando em cima de `Membro` normalmente, sem nenhuma mudança de caminho.
- `_escala_visivel_ou_404(escala_id)` (mesmo formato de `comunidade._comunidade_visivel_ou_404`) dá ao dono acesso total e ao convidado (`Funcao.eh_convidado=True` cujo `Membro.email` bate com `current_user.email`) acesso **só de leitura** àquela `Escala` específica — usado em `detalhe()`; todas as outras rotas de escrita continuam com a checagem estrita de dono. `trocar_atribuicao` também troca `eh_convidado` no swap (senão a marca "ficaria" na posição errada ao mover/trocar).

## Geração da escala

`criar_escala_com_funcoes_padrao(ministerio_id, nome, departamento, data, horario)` cria a `Escala` e semeia as `Funcao` do departamento, todas com `membro_id=None`. Atribuir alguém é uma ação manual separada (`SelecionarMembroForm`) — **não existe fila/rotação aqui**. Só é usada para escalas manuais; escalas geradas por rodízio são criadas por `app/plantao/sincronizacao.py::_materializar_periodo` (sempre 1 única `Funcao`, nunca esta função).

`POST /escala/funcao/<id>/mover` usa `trocar_atribuicao(funcao_a, funcao_b)` (`models.py`) para o **swap completo** (membro + status + notificado_em) entre duas `Funcao` — não é "mover uma pessoa para uma vaga vazia", é sempre troca de duas posições, dentro da mesma escala (só aparece com 2+ funções).

## Escalas geradas por rodízio — restrições de UI/rota

Uma `Escala` com `plantao_turno_id` preenchido:
- **Não** oferece "adicionar função"/"adicionar subcabeçalho" (`escala.adicionar_funcao`/`adicionar_subcabecalho` rejeitam explicitamente) — sempre exatamente 1 função, a rotacionada.
- Qualquer edição manual que a toque (`editar`, `adicionar_membro`, `remover_membro`, `mover_membro`) chama `_fixar_se_gerada_por_rodizio(escala)` (helper no topo de `routes.py`), marcando `plantao_fixado=True` — senão o próximo sync de `plantao` sobrescreveria a mudança manual com a fórmula pura do rodízio.
- Ausência nessas escalas usa o **mesmo fluxo genérico** de qualquer escala manual — `escala.remover_membro` (não há mais um caminho separado de "registrar ausência" com remanejamento automático). O botão "remover" fica disponível mesmo quando a escala gerada tem só 1 função (uma equipe de 1 pessoa) — só o botão "mover/trocar" exige 2+ funções. Ver [app/plantao/CLAUDE.md](../plantao/CLAUDE.md) para o conceito de equipe (grupo de 1+ pessoas que atua em bloco numa ocorrência).

## Escala como origem de rodízio

Quando um `TurnoPlantao` nasce a partir desta `Escala` (botão "Criar turno de rodízio com esta equipe", ver [app/plantao/CLAUDE.md](../plantao/CLAUDE.md)), o vínculo é **permanente**: `escala.turno_plantao_origem_id` é setado no momento da criação (`plantao.routes.nova`) e nunca mais muda. Isso muda a navegação: a escala de origem passa a mostrar um badge "Rodízio vinculado" linkando pra `plantao.detalhe` (em vez do botão de criar, que some — `not escala.plantao_turno_id and not escala.turno_plantao_origem_id` — pra não linkar um segundo turno à mesma escala), **e** `ministerio._escalas_agrupadas_por_turno` deixa de gerar uma capa separada pra esse turno na listagem do Ministério — a escala de origem (que já aparece lá, como qualquer escala manual) é o único ponto de entrada. Sem isso, a escala de origem e a capa do turno apareciam como duas entradas parecidas (mesmo nome/departamento, pré-preenchidos) na mesma lista, dando impressão de duplicação. Se a escala de origem for excluída, o turno continua existindo (sem cascade nessa direção) e volta a gerar sua própria capa normalmente (fallback automático, já que a checagem é sempre `turno.escala_origem is not None` em tempo de request, não um estado persistido à parte).

## Notificações

`enviar_notificacoes_da_escala(escala)` em `routes.py` é a função central (chamada tanto pelo botão manual `POST /escala/<id>/notificar` quanto pelo scheduler). Para cada `Funcao` com `membro_id`:
1. Se `Membro.email` bate com um `User.email` existente, cria `Notificacao` in-app (extra, não substitui e-mail).
2. Tenta `enviar_email` (se `membro.email`).
3. Tenta `enviar_sms` (se `membro.telefone`).
4. Falhas de e-mail/SMS são capturadas (`EmailNaoEnviadoError`/`SmsNaoEnviadoError`), nunca propagam como 500 — só entram na contagem de retorno (`email_falhas`, `sms_falhas`, `sem_contato`).
5. `marcar_notificado` só stampa `notificado_em` se pelo menos um canal teve sucesso.

Editar `data`/`horario` de uma `Escala` existente reseta `notificado_24h_em`/`notificado_16h_em` para `None` (para o scheduler reconsiderar) e chama `enviar_notificacao_de_alteracao(...)` avisando proativamente quem já estava escalado.

## Scheduler (`agendador.py`) — único do projeto

`BackgroundScheduler` (timezone `America/Sao_Paulo`), job `interval` a cada 15 min (`INTERVALO_VERIFICACAO_MINUTOS`). **Único agendador do projeto**: a cada tick, primeiro chama `plantao.sincronizacao.sincronizar_todos_os_turnos_ativos()` (materializa as próximas ocorrências de todo `TurnoPlantao`, rolando a janela de 90 dias pra frente), depois checa notificação. Para cada `Escala` com `data` preenchida (manual ou gerada por rodízio — indistintas aqui), calcula `faltam = data_hora - agora`; se `notificado_24h_em is None and abs(faltam - timedelta(hours=24)) <= _JANELA` (±15 min, idem para 16h), chama `enviar_notificacoes_da_escala` e stampa o timestamp correspondente. Não existe mais scheduler nem tabela de notificação próprios do `plantao` — foram eliminados quando o rodízio passou a materializar em `Escala` real.

**Atenção:** usa `datetime.now()` (hora local, naive), enquanto os defaults de modelo (ex. `Notificacao.criada_em`) usam `datetime.now(timezone.utc)`. É uma inconsistência existente — não assuma que os dois são diretamente comparáveis se for mexer nessa lógica. `app/plantao/sincronizacao.py` segue a mesma convenção naive de propósito, pelo mesmo motivo.

## Testes

`tests/test_escala.py` cobre: criação com funções padrão, atribuição/troca/status/remoção de membro, envio de notificação (com SMTP/Twilio não configurados, sem 500), sino in-app, subcabeçalhos, isolamento cross-account (404 para outro dono). `tests/test_agendador.py` cobre a janela de disparo do scheduler, incluindo a materialização+notificação de `Escala` geradas por `TurnoPlantao`.
