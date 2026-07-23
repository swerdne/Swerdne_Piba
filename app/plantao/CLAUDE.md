# app/plantao — motor de rodízio da Escala

Contexto local. Visão geral do projeto e convenções gerais: [../../CLAUDE.md](../../CLAUDE.md).

## Responsabilidade

**Não é mais uma funcionalidade paralela com tela própria.** Um `TurnoPlantao` é a *regra* de um rodízio (fila de pessoas + offset + recorrência + departamento) dentro de um Ministério; o motor de sincronização em [sincronizacao.py](sincronizacao.py) materializa essa regra em `Escala`/`Funcao` **reais** (as mesmas do [app/escala](../escala/CLAUDE.md)) para uma janela rolante de 90 dias à frente. Uma vez materializada, a ocorrência aparece no calendário/lista do Ministério com a cor do departamento e é notificada 24h/16h antes pelo **mesmo** scheduler da Escala Rápida — este módulo não tem mais scheduler nem tabela de notificação próprios.

Este módulo cuida só da **configuração** da regra (criar/editar turno, montar a fila, registrar ausência) — não tem mais tela de "escala gerada" própria; as ocorrências geradas são visitadas via `escala.detalhe`, como qualquer outra escala.

## Models (`models.py`)

- `TurnoPlantao` (`turnos_plantao`) — a regra: `ministerio_id`, `nome`, `departamento` (chave de `DEPARTAMENTOS` em `app/escala/models.py`, herda cor no calendário), `nome_funcao` (nome do papel criado em cada ocorrência, default "Responsavel"), `data_inicio`, `horario`, `recorrencia` (`diaria`/`semanal`/`mensal`), `offset`. **Nunca guarda quem está escalado em cada data** — isso vive nas `Escala` geradas.
- `MembroTurno` (`turno_plantao_membros`) — fila ordenada (reaproveita `Membro` de `app/escala/models.py`). Remover reordena as posições restantes para ficarem contíguas.
- `membro_do_periodo(turno, periodo)` — a **fórmula pura** do rodízio (`fila[(offset+periodo)%len]`). Uso exclusivo do motor de sincronização para decidir o valor de um período ainda não fixado — **não** representa "quem está escalado agora" (isso pode ter divergido da fórmula por causa de `Escala.plantao_fixado`; leia sempre do estado materializado, nunca desta função, para saber a atribuição atual de um período específico).
- `data_do_periodo`/`periodo_da_data`/`_somar_meses`/`_diferenca_em_meses` — matemática pura de conversão data↔período, sem mudança de comportamento.

Não existe mais `OverridePlantao` nem `NotificacaoPlantaoEnviada` — ver seção seguinte.

## O vínculo com `Escala` (`app/escala/models.py`)

`Escala` ganhou 3 colunas: `plantao_turno_id` (FK, `None` = escala manual), `plantao_periodo` (índice do período que essa ocorrência representa), `plantao_fixado` (trava que uma ocorrência específica divergiu da fórmula pura — ausência remanejada ou edição manual — e por isso o sync nunca deve sobrescrevê-la). `UniqueConstraint(plantao_turno_id, plantao_periodo)`.

## Motor de sincronização (`sincronizacao.py`)

`sincronizar_turno(turno, ate_data=None)` — para cada período entre hoje e `ate_data` (padrão `hoje + JANELA_GERACAO_DIAS` = 90 dias):
- **Não existe** → cria `Escala` + 1 `Funcao` (nunca reaproveita `criar_escala_com_funcoes_padrao`, que semearia todas as funções padrão do departamento — aqui é sempre 1 única função, `turno.nome_funcao`).
- **Já ocorreu** (`escala.data_hora <= agora`, comparação **naive**, igual a `escala/agendador.py` — não misture com `datetime.now(timezone.utc)`) → nunca toca. É assim que o histórico fica intocável.
- **Não ocorreu e não fixada** → recalcula nome/data/horário/departamento/membro a partir da config atual do turno; **só escreve e só reseta os timestamps de notificação se algo realmente mudou** (comparação explícita, não incondicional). Isso é obrigatório: a função roda a cada 15 min pelo scheduler unificado — sem a checagem de diff, resetaria notificação a cada tick e causaria reenvio em loop.
- **Fixada** → pula, preserva a exceção pontual.

Chamada em: criar/editar turno, adicionar/remover membro da fila (`routes.py`), e a cada tick do scheduler único via `sincronizar_todos_os_turnos_ativos()` (chamada dentro de `app/escala/agendador.py::_verificar_e_notificar`, antes de checar notificações) — isso rola a janela pra frente com o tempo.

`preparar_para_renumeracao(turno)` — chamada **antes** de `sincronizar_turno` quando `data_inicio`/`recorrencia` mudam (a numeração de período passa a significar outra data): deleta as `Escala` futuras não-fixadas do turno; nas demais (fixadas ou já ocorridas), zera `plantao_periodo` mantendo `plantao_turno_id` (preserva proveniência e data já gravada como histórico solto, sem colidir com a unique constraint na nova numeração — `NULL` não colide com `NULL`).

`marcar_ausencia(turno, periodo)` — troca a atribuição do período com a do período seguinte, lendo o estado **materializado atual** (nunca `membro_do_periodo`, que ignoraria uma fixação anterior e devolveria a pessoa errada). Usa `trocar_atribuicao` (`app/escala/models.py`, a mesma função usada por `escala.routes.mover_membro`) para o swap. Marca as duas `Escala` como `plantao_fixado=True` e reseta os timestamps de notificação das duas. Rejeita período já ocorrido.

## Rotas (`routes.py`)

`nova`/`editar` chamam `sincronizar_turno` após commit (`editar` chama `preparar_para_renumeracao` antes, se `data_inicio`/`recorrencia` mudaram). `adicionar_membro_fila`/`remover_membro_fila` idem. `excluir_turno` faz detach (fixadas/ocorridas) ou delete (futuras não-fixadas) nas `Escala` geradas antes de apagar o turno — feito manualmente porque o SQLite de dev não tem `PRAGMA foreign_keys=ON`, não dá pra confiar em cascade do banco. `registrar_ausencia` (por data, tela de config) e `registrar_ausencia_na_escala` (a partir da própria tela da Escala gerada, `escala/detalhe.html`) chamam o mesmo `marcar_ausencia`.

## Edição manual de uma ocorrência gerada

Uma escala gerada por rodízio pode ser editada manualmente como qualquer escala (trocar responsável, editar nome/data) — mas isso marca `plantao_fixado=True` (via `escala.routes._fixar_se_gerada_por_rodizio`) para o próximo sync não sobrescrever. Ela **não** oferece "adicionar função"/"nova categoria" (sempre exatamente 1 função, a rotacionada) — reforçado tanto na UI (`escala/detalhe.html`) quanto nas rotas `escala.adicionar_funcao`/`adicionar_subcabecalho`.

## Testes

`tests/test_plantao.py`: matemática de período (inalterada), fórmula pura, motor de sync (cria, idempotência, preserva fixado, nunca toca passado, reflete edição de turno, recria períodos na mudança de `data_inicio`/`recorrência`), ausência (swap sobre estado materializado, cascata, rejeita passado), exclusão de turno (detach/delete), integração com calendário/relatório. `tests/test_agendador.py` cobre a integração com o scheduler único (materializa + notifica na janela 24h/16h a partir de um `TurnoPlantao`).

**Cuidado ao escrever testes:** uma `Escala` materializada para "hoje" sem horário usa `datetime.min.time()` (meia-noite) como fallback em `Escala.data_hora` — na prática já conta como "passado" a qualquer hora do dia em que o teste rodar. Para testar comportamento de período **futuro**, use `data_inicio=date.today() + timedelta(days=1)` (ou um horário explicitamente à frente de `datetime.now()`), não `date.today()` sem horário.
