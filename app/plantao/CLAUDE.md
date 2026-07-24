# app/plantao — motor de rodízio da Escala

Contexto local. Visão geral do projeto e convenções gerais: [../../CLAUDE.md](../../CLAUDE.md).

## Responsabilidade

**Não é mais uma funcionalidade paralela com tela própria.** Um `TurnoPlantao` é a *regra* de um rodízio (fila de pessoas + offset + recorrência + departamento) dentro de um Ministério; o motor de sincronização em [sincronizacao.py](sincronizacao.py) materializa essa regra em `Escala`/`Funcao` **reais** (as mesmas do [app/escala](../escala/CLAUDE.md)) para uma janela rolante de 90 dias à frente. Uma vez materializada, a ocorrência aparece no calendário/lista do Ministério com a cor do departamento e é notificada 24h/16h antes pelo **mesmo** scheduler da Escala Rápida — este módulo não tem mais scheduler nem tabela de notificação próprios.

Este módulo cuida só da **configuração** da regra (criar/editar turno, montar a fila, registrar ausência) — não tem mais tela de "escala gerada" própria; as ocorrências geradas são visitadas via `escala.detalhe`, como qualquer outra escala.

## Models (`models.py`)

- `TurnoPlantao` (`turnos_plantao`) — a regra: `ministerio_id`, `nome`, `departamento` (chave de `DEPARTAMENTOS` em `app/escala/models.py`, herda cor no calendário), `nome_funcao` (nome do papel criado em cada ocorrência, default "Responsavel"), `data_inicio`, `horario`, `offset`, mais os campos de **recorrência estilo Google Agenda** (ver abaixo). **Nunca guarda quem está escalado em cada data** — isso vive nas `Escala` geradas.
- `MembroTurno` (`turno_plantao_membros`) — fila ordenada (reaproveita `Membro` de `app/escala/models.py`). Remover reordena as posições restantes para ficarem contíguas.
- `membro_do_periodo(turno, periodo)` — a **fórmula pura** do rodízio (`fila[(offset+periodo)%len]`). Uso exclusivo do motor de sincronização para decidir o valor de um período ainda não fixado — **não** representa "quem está escalado agora" (isso pode ter divergido da fórmula por causa de `Escala.plantao_fixado`; leia sempre do estado materializado, nunca desta função, para saber a atribuição atual de um período específico).

Não existe mais `OverridePlantao` nem `NotificacaoPlantaoEnviada` — ver seção seguinte.

## Recorrência estilo Google Agenda (`models.py`)

Substitui a antiga `recorrencia` (`diaria`/`semanal`/`mensal`, sempre a cada 1 unidade) por:
- `intervalo_recorrencia` (Integer, "a cada N") + `unidade_recorrencia` (`dia`/`semana`/`mes`/`ano`).
- `dias_semana` (CSV de inteiros 0=segunda..6=domingo, só unidade=semana) — **sempre leia via a property `dias_semana_efetivos`** (nunca a coluna crua): ela cai no weekday de `data_inicio` se vier vazia/`None`, evitando `ZeroDivisionError` no motor.
- `modo_mensal` (`dia_fixo`/`enesimo_dia_semana`/`ultimo_dia_semana`, só unidade=mes) — o ordinal e o dia da semana dos modos "enésimo"/"último" são **sempre derivados de `data_inicio`** no cálculo (nunca armazenados à parte), igual ao seletor do Google Agenda: mudar a data de início recalcula automaticamente qual é a "3ª terça". `opcoes_modo_mensal(data_referencia)` gera as opções (rótulo já formatado) disponíveis pra essa data — omite `enesimo_dia_semana` quando a ocorrência é a **5ª** do mês (ordinal raro, pularia quase todo mês; mesmo comportamento do Google Agenda real).
- `termino_tipo` (`nunca`/`data`/`ocorrencias`) + `termino_data`/`termino_ocorrencias`.

**`data_do_periodo(turno, periodo)`** é a função central — despacha por `unidade_recorrencia` com fórmula fechada O(1) para `dia`, `semana` (mesmo com múltiplos `dias_semana`, via `divmod`), `mes`+`dia_fixo` e `mes`+`ultimo_dia_semana`, e `ano`. Só `mes`+`enesimo_dia_semana` não tem fórmula fechada (um mês pode não ter a N-ésima ocorrência daquele dia da semana, ex. "5ª terça") — caminha por mês (O(meses), não O(dias)), e **meses pulados não incrementam a contagem de período** (crítico: é assim que `termino_ocorrencias` não conta um mês pulado como se fosse uma ocorrência real). Levanta `ValueError` quando o período/data passa do `termino_tipo` configurado — é assim que o término se propaga, sem precisar de uma camada de geração separada.

**`periodo_da_data(turno, data)` é uma ESTIMATIVA CONSERVADORA (nunca overestima), não mais um mapeamento exato** — mudança de contrato importante. `sincronizar_turno` só precisa de um ponto de partida barato pro loop (subestimar custa só algumas iterações descartadas); usar essa função esperando exatidão é o bug mais fácil de reintroduzir aqui (ver nota abaixo). Para achar o período **exato** de uma data digitada pelo usuário (ex. ausência por data), use `periodo_exato_da_data(turno, data)` — parte da estimativa e caminha pra frente até achar `data` exata ou `ValueError` ("não corresponde a uma ocorrência").

## O vínculo com `Escala` (`app/escala/models.py`)

`Escala` ganhou 3 colunas: `plantao_turno_id` (FK, `None` = escala manual), `plantao_periodo` (índice do período que essa ocorrência representa), `plantao_fixado` (trava que uma ocorrência específica divergiu da fórmula pura — ausência remanejada ou edição manual — e por isso o sync nunca deve sobrescrevê-la). `UniqueConstraint(plantao_turno_id, plantao_periodo)`.

## Motor de sincronização (`sincronizacao.py`)

`sincronizar_turno(turno, ate_data=None)` — caminha **período a período** (não usa mais `range()` com limites pré-calculados — não dá pra garantir que uma data de corte arbitrária como `ate_data` caia numa ocorrência exata) chamando `data_do_periodo` até um `ValueError` (recorrência terminou) ou a data ultrapassar `ate_data` (padrão `hoje + JANELA_GERACAO_DIAS` = 90 dias). Por período:
- **Não existe** → cria `Escala` + 1 `Funcao` (nunca reaproveita `criar_escala_com_funcoes_padrao`, que semearia todas as funções padrão do departamento — aqui é sempre 1 única função, `turno.nome_funcao`).
- **Já ocorreu** (`escala.data_hora <= agora`, comparação **naive**, igual a `escala/agendador.py` — não misture com `datetime.now(timezone.utc)`) → nunca toca. É assim que o histórico fica intocável.
- **Não ocorreu e não fixada** → recalcula nome/data/horário/departamento/membro a partir da config atual do turno; **só escreve e só reseta os timestamps de notificação se algo realmente mudou** (comparação explícita, não incondicional). Isso é obrigatório: a função roda a cada 15 min pelo scheduler unificado — sem a checagem de diff, resetaria notificação a cada tick e causaria reenvio em loop.
- **Fixada** → pula, preserva a exceção pontual.

`_materializar_periodo`/`_atualizar_periodo_existente` recebem `data_periodo` **já calculado pelo chamador** (não recalculam via `data_do_periodo`) — evita O(n²) dentro do loop, já que o modo mensal "enésimo dia da semana" não tem fórmula fechada O(1).

Chamada em: criar/editar turno, adicionar/remover membro da fila (`routes.py`), e a cada tick do scheduler único via `sincronizar_todos_os_turnos_ativos()` (chamada dentro de `app/escala/agendador.py::_verificar_e_notificar`, antes de checar notificações) — isso rola a janela pra frente com o tempo.

`preparar_para_renumeracao(turno)` — chamada **antes** de `sincronizar_turno` quando **qualquer** campo que afete o cálculo de período muda (`data_inicio`, `intervalo_recorrencia`, `unidade_recorrencia`, `dias_semana`, `modo_mensal`, `termino_tipo`, `termino_data`, `termino_ocorrencias` — ver `CAMPOS_QUE_AFETAM_NUMERACAO` em `routes.py`): deleta as `Escala` futuras não-fixadas do turno; nas demais (fixadas ou já ocorridas), zera `plantao_periodo` mantendo `plantao_turno_id` (preserva proveniência e data já gravada como histórico solto, sem colidir com a unique constraint na nova numeração — `NULL` não colide com `NULL`). Incluir os campos de término na lista é proposital: encurtar "após 20 ocorrências" para "após 5" precisa limpar as ocorrências futuras já materializadas além do novo limite.

`marcar_ausencia(turno, periodo)` — troca a atribuição do período com a do período seguinte, lendo o estado **materializado atual** (nunca `membro_do_periodo`, que ignoraria uma fixação anterior e devolveria a pessoa errada). Usa `trocar_atribuicao` (`app/escala/models.py`, a mesma função usada por `escala.routes.mover_membro`) para o swap. Marca as duas `Escala` como `plantao_fixado=True` e reseta os timestamps de notificação das duas. Rejeita período já ocorrido; se o período seguinte estiver além do `termino_tipo` configurado (ex. marcar ausência no último período de um turno "após N ocorrências"), devolve uma mensagem de domínio clara em vez do `ValueError` genérico de `data_do_periodo`.

## Rotas (`routes.py`)

`nova`/`editar` chamam `sincronizar_turno` após commit (`editar` chama `preparar_para_renumeracao` antes, se algum campo em `CAMPOS_QUE_AFETAM_NUMERACAO` mudou). `adicionar_membro_fila`/`remover_membro_fila` idem. `excluir_turno` faz detach (fixadas/ocorridas) ou delete (futuras não-fixadas) nas `Escala` geradas antes de apagar o turno — feito manualmente porque o SQLite de dev não tem `PRAGMA foreign_keys=ON`, não dá pra confiar em cascade do banco. `registrar_ausencia` (por data, tela de config — usa `periodo_exato_da_data`, não `periodo_da_data`) e `registrar_ausencia_na_escala` (a partir da própria tela da Escala gerada, `escala/detalhe.html`, já sabe o período) chamam o mesmo `marcar_ausencia`. `_aplicar_campos_do_form` centraliza a conversão form→model, incluindo o CSV↔lista de `dias_semana` (WTForms não faz isso sozinho com `SelectMultipleField` + `obj=`) e zera `modo_mensal`/`termino_data`/`termino_ocorrencias` quando não se aplicam à unidade/término escolhidos.

## Turno nascido de uma Escala (reaproveita a equipe já escalada)

`plantao.nova` aceita um query param opcional `?escala_id=<id>` (usado pelo botão "Criar turno de rodízio com esta equipe" em `escala/detalhe.html`, só exibido quando `not escala.plantao_turno_id` e a escala tem pelo menos 1 função com `membro_id`). Quando presente:
- Valida posse (`_escala_do_usuario_ou_404`) **e** que a escala pertence ao mesmo `ministerio_id` da URL (`abort(404)` senão) — evita misturar equipe de um ministério/comunidade com o turno de outro.
- No GET, pré-preenche `nome`/`departamento`/`data_inicio`/`horario` do form a partir da escala de origem (o usuário ainda pode editar antes de salvar).
- No POST bem-sucedido, `_semear_fila_a_partir_da_escala(turno, escala)` popula a fila do turno com os membros já escalados nas funções da escala (ordenado por `Funcao.ordem`, deduplicando quem estiver em mais de uma função) — poupa o passo manual de readicionar cada pessoa na tela de fila. `escala_id` persiste no GET→POST porque o `<form>` de `plantao/nova.html` não tem `action=` explícito (submete pra própria URL, preservando a query string).
- Isso é só um **seed pontual**: depois de criado, o `TurnoPlantao` é totalmente independente da escala de origem (que continua sendo um evento manual comum) — não existe um vínculo permanente no banco entre os dois.

**Este é o único caminho de criação exposto na UI.** `ministerio/detalhe.html` não tem mais um botão "Novo Turno de Rodízio" (removido de propósito — criar um turno do zero, sem escala de origem, forçava montar a fila manualmente pessoa por pessoa). A seção "Turnos de Rodízio" na tela do Ministério só lista os turnos já existentes (link pra `plantao.detalhe`/editar fila/config); a rota `plantao.nova` continua aceitando GET/POST sem `escala_id` (não removi a flexibilidade da rota, só o botão), mas isso não é mais alcançável por nenhum link do app — só chegando direto pela URL.

## Cálculo de dia da semana/posição no mês ao vivo (`plantao/nova.html`, `editar.html`)

As opções de `modo_mensal` (`dia_fixo`/`enésimo_dia_semana`/`último_dia_semana`) são calculadas a partir de `data_inicio`, mas o campo de data é um `<input type=date>` puramente client-side — sem JS, os rótulos mostrados ficariam presos à referência do último *render* do servidor (hoje, em `nova`, ou a data salva do turno, em `editar`), incoerentes com a data que o usuário está prestes a escolher no seletor. Cada template tem um script (duplicado entre os dois, mesmo padrão dos outros toggles da página) que recalcula dia da semana + posição no mês **inteiramente no client**, espelhando `_ordinal_do_dia_semana_no_mes`/`data_do_periodo`, e reescreve o texto das 3 opções a cada `change`/`input` do campo `#data_inicio` (e uma vez no load, pra sincronizar com um valor já preenchido). Atenção ao converter a data: `new Date("YYYY-MM-DD")` interpreta como UTC e pode voltar um dia em fusos negativos (Brasil é UTC-3) — o script usa `new Date(ano, mes-1, dia)` (fuso local) de propósito. `JS getDay()` é 0=domingo..6=sábado; convertido pra 0=segunda..6=domingo (`(getDay()+6)%7`) pra bater com `date.weekday()` do Python.

Pra isso funcionar sem precisar criar/remover elementos do DOM em JS, as rotas passam a montar `form.modo_mensal.choices` sempre com as **3** opções (`opcoes_modo_mensal_completas`, em vez de `opcoes_modo_mensal` que omite "enésimo" no caso raro da 5ª ocorrência) — o JS é quem esconde a opção "enésimo" (e troca a seleção pra "último" se estiver marcada) quando a data escolhida cai numa 5ª ocorrência do dia da semana no mês. `opcoes_modo_mensal` (a que omite) continua existindo e testada — é a função "canônica"/defesa em profundidade; `opcoes_modo_mensal_completas` só embrulha ela garantindo as 3 chaves sempre presentes.

## Edição manual de uma ocorrência gerada

Uma escala gerada por rodízio pode ser editada manualmente como qualquer escala (trocar responsável, editar nome/data) — mas isso marca `plantao_fixado=True` (via `escala.routes._fixar_se_gerada_por_rodizio`) para o próximo sync não sobrescrever. Ela **não** oferece "adicionar função"/"nova categoria" (sempre exatamente 1 função, a rotacionada) — reforçado tanto na UI (`escala/detalhe.html`) quanto nas rotas `escala.adicionar_funcao`/`adicionar_subcabecalho`.

## Testes

`tests/test_plantao.py`: motor de recorrência (`data_do_periodo` por unidade/modo, incl. "pula mês" no modo enésimo e término não contar mês pulado; `periodo_exato_da_data`; `opcoes_modo_mensal_completas` sempre com 3 chaves e batendo com `opcoes_modo_mensal` fora do ordinal 5), fórmula pura do rodízio, motor de sync (cria, idempotência, preserva fixado, nunca toca passado, reflete edição de turno, recria períodos na mudança de qualquer campo de recorrência — **incluindo o teste de regressão do bug em que `sincronizar_turno` dependia de `ate_data` cair exatamente numa ocorrência**, que quebrava pra semana/mês flexíveis), ausência (swap sobre estado materializado, cascata, rejeita passado, mensagem amigável no limite do término), exclusão de turno (detach/delete), turno nascido de escala (semeia fila deduplicada e na ordem certa, pré-preenchimento do form, isolamento cross-account e cross-ministério, link só aparece quando faz sentido), integração com calendário/relatório. `tests/test_agendador.py` cobre a integração com o scheduler único (materializa + notifica na janela 24h/16h a partir de um `TurnoPlantao`).

**Cuidado ao escrever testes:** uma `Escala` materializada para "hoje" sem horário usa `datetime.min.time()` (meia-noite) como fallback em `Escala.data_hora` — na prática já conta como "passado" a qualquer hora do dia em que o teste rodar. Para testar comportamento de período **futuro**, use `data_inicio=date.today() + timedelta(days=1)` (ou um horário explicitamente à frente de `datetime.now()`), não `date.today()` sem horário.
