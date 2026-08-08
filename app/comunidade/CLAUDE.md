# app/comunidade — Comunidade e diretório de membros

Contexto local. Visão geral do projeto e convenções gerais: [../../CLAUDE.md](../../CLAUDE.md).

## Responsabilidade

`Comunidade` é a raiz de posse de todo o resto do sistema: todo `Ministerio`, `Escala`, `TurnoPlantao` e `Membro` pertence, direta ou indiretamente, a uma comunidade — e comunidades são independentes entre si (não há dados compartilhados entre comunidades de donos diferentes). É aqui também que fica o **diretório de pessoas** (`Membro`, definido em `app/escala/models.py` mas usado tanto por `escala` quanto por `plantao`) e o relatório cross-ministério "Escalados".

## Models

`Comunidade` (`comunidades`): `usuario_id` (FK dono), `nome`, `descricao`, `imagem`, `criada_em`. Criada via `criar_comunidade(...)`.

`Membro` **não está** em `app/comunidade/models.py` — está em `app/escala/models.py` (tabela `escala_membros`), importado aqui. Se for procurar o model do diretório de pessoas, é lá.

## Duas formas de acesso — não confundir

```python
def _comunidade_do_usuario_ou_404(comunidade_id):
    """Acesso de DONO (leitura+escrita)."""
    comunidade = Comunidade.query.get_or_404(comunidade_id)
    if comunidade.usuario_id != current_user.id:
        abort(404)
    return comunidade

def _comunidade_visivel_ou_404(comunidade_id):
    """Acesso de LEITURA: dono OU membro do diretorio cujo email bate com a
    conta logada."""
    comunidade = Comunidade.query.get_or_404(comunidade_id)
    eh_dono = comunidade.usuario_id == current_user.id
    eh_membro_vinculado = Membro.query.filter_by(
        comunidade_id=comunidade.id, email=current_user.email
    ).first() is not None
    if not eh_dono and not eh_membro_vinculado:
        abort(404)
    return comunidade, eh_dono
```

`_comunidade_visivel_ou_404` é a **única exceção** no sistema à regra "só o dono acessa" — usada em `GET /comunidade/<id>/escalados`. Um `Membro` do diretório cujo `email` bate com o `User.email` logado ganha visibilidade **somente leitura** (aparece em "comunidades que participa" na listagem, vê o relatório de escalados) — nunca escrita. Toda rota nova de leitura que deveria respeitar esse vínculo precisa usar este helper, não `_comunidade_do_usuario_ou_404`; toda rota de escrita deve continuar usando o helper de dono.

## Regras específicas

- `POST /comunidade/<id>/excluir` (`excluir_comunidade`, botão no header de `comunidade/detalhe.html`) apaga a comunidade inteira — mesmo padrão de `ministerio.excluir_ministerio`: cascade do ORM (`cascade="all, delete-orphan"` em `Comunidade.ministerios` e `Comunidade.membros`) apaga junto todos os `Ministerio` (e, por tabela, todas as `Escala`/`Funcao`/`TurnoPlantao` deles) e todo o diretório de `Membro` — nada é preservado como histórico, diferente de `plantao.excluir_turno`. Exige dono (`_comunidade_do_usuario_ou_404`) e confirmação client-side (`confirm(...)`), como toda ação destrutiva do projeto.
- Exclusão de `Membro` é bloqueada se ele estiver escalado em algum lugar: `Funcao.query.filter_by(membro_id=...).count() > 0` impede a exclusão (evita quebrar referências históricas em escalas já criadas). Essa checagem não se aplica à exclusão da comunidade inteira acima, que apaga tudo incondicionalmente.
- `GET /comunidade/<id>/escalados` junta `Funcao → Escala → Ministerio`, com filtros `data_de`, `data_ate`, `departamento`, `funcao` — é o único relatório cross-ministério do sistema; ao adicionar um novo tipo de escalação (ex. se `plantao` ganhar um relatório equivalente), considere se deve entrar aqui também em vez de criar um relatório paralelo.
- Upload de logo (`_salvar_logo`/`_remover_logo_antiga`) usa nome de arquivo UUID em `COMUNIDADE_UPLOAD_FOLDER` — mesmo padrão usado por avatar de usuário (`app/main`) e logo de ministério.

## Testes

`tests/test_comunidade.py`: CRUD, estado vazio, isolamento cross-account (404), diretório de membros (adicionar/excluir, exclusão bloqueada se escalado), filtros do relatório `/escalados`, e especificamente o comportamento de visibilidade por vínculo de e-mail (`test_membro_vinculado_por_email_ve_escalados_de_leitura`, `test_terceiro_sem_vinculo_nao_ve_escalados`) — são os testes de referência para não quebrar essa regra ao mexer em autorização deste módulo.
