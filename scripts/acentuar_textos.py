"""Poe acento nas palavras comuns escritas sem acento nos textos que o usuario
VE (telas, avisos, rotulos de formulario), sem mexer em codigo.

    venv/Scripts/python.exe scripts/acentuar_textos.py [--checar]

Onde mexe:
- templates (.html): texto entre tags; atributos visiveis (placeholder,
  title, aria-label, alt, data-confirm-excluir); strings com espaco dentro
  de {{ }}/{% %} e dentro de <script>;
- static/js: strings com espaco;
- Python (app/): so em flash(), ValidationError(), rotulos de *Field(),
  choices, message=, valores de "mensagem"/"rotulo"/"titulo"/"erro" e
  dicionarios *_LABELS. Docstrings, comentarios, chaves e nomes ficam.
Nao mexe em app/whatsapp*.py (modelos aprovados na Meta, intencoes) nem em
e-mails. --checar so lista o que mudaria (sai com 1 se houver algo).
"""
import ast
import glob
import io
import os
import re
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PALAVRAS = """
nao:não voce:você voces:vocês ja:já ate:até sera:será tambem:também so:só alem:além entao:então porem:porém
apos:após atraves:através ultimo:último ultima:última ultimos:últimos ultimas:últimas proximo:próximo
proxima:próxima proximos:próximos proximas:próximas numero:número numeros:números unico:único unica:única
unicos:únicos unicas:únicas periodo:período periodos:períodos inicio:início horario:horário horarios:horários
calendario:calendário calendarios:calendários ministerio:ministério ministerios:ministérios rodizio:rodízio
rodizios:rodízios funcao:função funcoes:funções notificacao:notificação notificacoes:notificações
configuracao:configuração configuracoes:configurações informacao:informação informacoes:informações
acao:ação acoes:ações opcao:opção opcoes:opções descricao:descrição edicao:edição exclusao:exclusão
sessao:sessão permissao:permissão permissoes:permissões versao:versão conexao:conexão localizacao:localização
confirmacao:confirmação alteracao:alteração alteracoes:alterações solicitacao:solicitação
atualizacao:atualização organizacao:organização participacao:participação transcricao:transcrição
recorrencia:recorrência frequencia:frequência sequencia:sequência referencia:referência
preferencia:preferência preferencias:preferências ausencia:ausência disponivel:disponível
indisponivel:indisponível disponiveis:disponíveis possivel:possível possiveis:possíveis impossivel:impossível
invalido:inválido invalida:inválida invalidos:inválidos invalidas:inválidas musica:música musicas:músicas
midia:mídia midias:mídias video:vídeo videos:vídeos audio:áudio audios:áudios pagina:página paginas:páginas
codigo:código codigos:códigos endereco:endereço enderecos:endereços lider:líder lideres:líderes area:área
areas:áreas historico:histórico automatico:automático automatica:automática automaticos:automáticos
automaticamente:automaticamente rapido:rápido rapida:rápida rapidos:rápidos facil:fácil dificil:difícil
obrigatorio:obrigatório obrigatoria:obrigatória usuario:usuário usuarios:usuários diretorio:diretório
relatorio:relatório relatorios:relatórios formulario:formulário comentario:comentário comentarios:comentários
necessario:necessário necessaria:necessária proprio:próprio propria:própria proprios:próprios proprias:próprias
conteudo:conteúdo titulo:título titulos:títulos minimo:mínimo minima:mínima maximo:máximo maxima:máxima
sabado:sábado sabados:sábados mes:mês meses:meses tres:três alguem:alguém ninguem:ninguém estao:estão sao:são
saida:saída excluido:excluído excluida:excluída excluidos:excluídos excluidas:excluídas incluido:incluído
incluida:incluída atribuido:atribuído concluido:concluído visivel:visível visiveis:visíveis
invisivel:invisível responsavel:responsável responsaveis:responsáveis nivel:nível niveis:níveis
papeis:papéis duvida:dúvida duvidas:dúvidas seguranca:segurança crianca:criança criancas:crianças
familia:família proxima:próxima estara:estará tera:terá podera:poderá havera:haverá ficara:ficará
terca:terça diario:diário aprovacao:aprovação remocao:remoção inscricao:inscrição selecao:seleção
situacao:situação condicao:condição posicao:posição atencao:atenção observacao:observação
verificacao:verificação validacao:validação duracao:duração criacao:criação excecao:exceção
transmissao:transmissão decisao:decisão revisao:revisão parabens:parabéns secao:seção especifico:específico
especifica:específica generico:genérico otimo:ótimo otima:ótima basico:básico indigo:índigo
ha:há sincronizacao:sincronização substituicao:substituição publico:público publica:pública
padrao:padrão padroes:padrões botao:botão botoes:botões cartao:cartão regiao:região razao:razão
voluntario:voluntário voluntarios:voluntários convidado:convidado orgao:órgão grafico:gráfico
graficos:gráficos estatistica:estatística estatisticas:estatísticas
historia:história memoria:memória vitoria:vitória agua:água analise:análise analises:análises
genero:gênero logico:lógico critico:crítico pratico:prático tecnico:técnico tecnica:técnica
eletronico:eletrônico telefonico:telefônico catalogo:catálogo metodo:método musico:músico musicos:músicos
celula:célula celulas:células louvavel:louvável veiculo:veículo indice:índice
faca:faça instrucao:instrução instrucoes:instruções redefinicao:redefinição dominio:domínio dominios:domínios
ancora:âncora termino:término conferencia:conferência ve:vê repertorio:repertório repertorios:repertórios projecao:projeção observacoes:observações observacao:observação ocorrencia:ocorrência ocorrencias:ocorrências sugestao:sugestão sugestoes:sugestões versoes:versões exibicao:exibição combinacao:combinação cenario:cenário administracao:administração ministracao:ministração atribuicao:atribuição atribuicoes:atribuições automaticas:automáticas aparencia:aparência adicao:adição adicoes:adições varios:vários varias:várias importacao:importação adoracao:adoração numeracao:numeração servico:serviço servicos:serviços agendamento:agendamento senao:senão tambem:também ola:olá
""".split()
MAPA = {}
for par in PALAVRAS:
    sem, com = par.split(":")
    if sem != com:
        MAPA[sem] = com

_RE = re.compile(r"(?<![\w@/#.-])(" + "|".join(sorted(MAPA, key=len, reverse=True)) + r")(?![\w@/-]|\.\w)", re.I)


# "esta"/"está" e "e"/"é" dependem do contexto: so nos casos sem duvida.
_FRASES = [
    (re.compile(r"\b(n[aã]o|j[aá]|voc[eê]|ainda|ningu[eé]m|quem|ele|ela|isso|isto|tudo|que|onde|como|s[oó]) esta\b", re.I), " está"),
    (re.compile(r"\b(n[aã]o|agora|isso|isto|tamb[eé]m|s[oó]|j[aá]|qual|o que) e\b(?! [ao]s? )(?=[ ,.!?\"])", re.I), " é"),
    (re.compile(r"\besta (?=ligad|desligad|cadastrad|escalad|vazi|cheia|abert|fechad|feit|pront|confirmad|ativ|inativ|sendo|funcionando|em uso|no |na |nos |nas )", re.I), "está "),
]


def acentuar(texto):
    def troca(m):
        palavra = m.group(0)
        certa = MAPA[palavra.lower()]
        if palavra.isupper() and len(palavra) > 1:
            return certa.upper()
        if palavra[0].isupper():
            return certa[0].upper() + certa[1:]
        return certa
    texto = _RE.sub(troca, texto)
    for padrao, fim in _FRASES:
        def troca_frase(m, fim=fim):
            if m.lastindex:  # palavra de antes + "está"/"é"
                return acentuar_palavra(m.group(1)) + fim
            return fim[0].upper() + fim[1:] if m.group(0)[0].isupper() else fim
        texto = padrao.sub(troca_frase, texto)
    return texto


def acentuar_palavra(palavra):
    certa = MAPA.get(palavra.lower())
    if not certa:
        return palavra
    return certa[0].upper() + certa[1:] if palavra[0].isupper() else certa


# --- Strings de JS/Jinja ---------------------------------------------------
_STR = re.compile(r"""'(?:[^'\\\n]|\\.)*'|"(?:[^"\\\n]|\\.)*\"""")


def _parece_codigo(conteudo):
    return (not conteudo.strip() or conteudo.lstrip()[:1] in "[.#/{<" or '="' in conteudo
            or "=" in conteudo and " " not in conteudo)


def acentuar_strings_com_espaco(codigo):
    def troca(m):
        bruto = m.group(0)
        conteudo = bruto[1:-1]
        if " " not in conteudo or _parece_codigo(conteudo):
            return bruto
        return bruto[0] + acentuar(conteudo) + bruto[-1]
    return _STR.sub(troca, codigo)


# --- Templates -----------------------------------------------------------------
_ATRIBUTOS = re.compile(r'''(\s(?:placeholder|title|aria-label|alt|data-confirm-excluir)=)("[^"]*"|'[^']*')''')
_PEDACO = re.compile(r"(\{\{.*?\}\}|\{%.*?%\}|\{#.*?#\}|<script\b.*?</script>|<style\b.*?</style>|<!--.*?-->|<[^>]*>)", re.S)


def acentuar_template(s):
    partes = _PEDACO.split(s)
    saida = []
    for i, p in enumerate(partes):
        if i % 2 == 0:  # texto entre tags
            saida.append(acentuar(p))
        elif p.startswith("{#") or p.startswith("<!--") or p.startswith("<style"):
            saida.append(p)
        elif p.startswith("{{") or p.startswith("{%"):
            saida.append(acentuar_strings_com_espaco(p))
        elif p.startswith("<script"):
            abre = p.index(">") + 1
            fecha = p.rindex("</script>")
            corpo = p[abre:fecha]
            # Jinja dentro do script: so as strings com espaco
            saida.append(p[:abre] + acentuar_strings_com_espaco(corpo) + p[fecha:])
        else:  # tag HTML: so atributos visiveis (sem Jinja dentro)
            def troca(m):
                valor = m.group(2)
                if "{{" in valor or "{%" in valor:
                    return m.group(0)
                return m.group(1) + valor[0] + acentuar(valor[1:-1]) + valor[-1]
            saida.append(_ATRIBUTOS.sub(troca, p))
    return "".join(saida)


# --- Python ----------------------------------------------------------------------
_CHAMADAS_TEXTO = {"flash", "ValidationError", "falha", "avisar_erro"}
_CHAVES_TEXTO = {"mensagem", "rotulo", "titulo", "erro"}


def _alvos_python(arvore):
    """Nos (Constant/JoinedStr) de texto visivel."""
    alvos = []

    def add(no):
        if isinstance(no, ast.Constant) and isinstance(no.value, str):
            alvos.append(no)
        elif isinstance(no, ast.JoinedStr):
            alvos.append(no)

    for no in ast.walk(arvore):
        if isinstance(no, ast.Call):
            nome = getattr(no.func, "id", None) or getattr(no.func, "attr", None) or ""
            if nome in _CHAMADAS_TEXTO and no.args:
                add(no.args[0])
            if nome == "responder" and len(no.args) >= 2:
                add(no.args[1])
            if nome.endswith("Field") and no.args:
                add(no.args[0])
            for kw in no.keywords:
                if kw.arg in ("message", "description", "label"):
                    add(kw.value)
                if kw.arg == "choices" and isinstance(kw.value, (ast.List, ast.Tuple)):
                    for item in kw.value.elts:
                        if isinstance(item, ast.Tuple) and len(item.elts) == 2:
                            add(item.elts[1])
        if isinstance(no, ast.Dict):
            for chave, valor in zip(no.keys, no.values):
                if isinstance(chave, ast.Constant) and chave.value in _CHAVES_TEXTO:
                    add(valor)
        if isinstance(no, ast.Assign) and isinstance(no.value, ast.Dict):
            nomes = [getattr(t, "id", "") for t in no.targets]
            if any(n.endswith("_LABELS") for n in nomes):
                for valor in no.value.values:
                    add(valor)
    return alvos


def acentuar_python(s):
    arvore = ast.parse(s)
    linhas = s.splitlines(keepends=True)
    inicio_linha = [0]
    for l in linhas:
        inicio_linha.append(inicio_linha[-1] + len(l))

    def pos(linha, col):
        # col_offset do ast e em bytes UTF-8
        texto_linha = linhas[linha - 1]
        return inicio_linha[linha - 1] + len(texto_linha.encode("utf-8")[:col].decode("utf-8"))

    trechos = []
    for no in _alvos_python(arvore):
        a, b = pos(no.lineno, no.col_offset), pos(no.end_lineno, no.end_col_offset)
        trechos.append((a, b))
    trechos = sorted(set(trechos), reverse=True)
    for a, b in trechos:
        original = s[a:b]
        if original.lstrip("rbfuRBFU")[:3] in ('"""', "'''"):
            continue
        # fora das chaves {} de f-string
        partes = re.split(r"(\{[^{}]*\})", original)
        novo = "".join(p if p.startswith("{") else acentuar(p) for p in partes)
        s = s[:a] + novo + s[b:]
    return s


def arquivos():
    for p in glob.glob(os.path.join(RAIZ, "app", "templates", "**", "*.html"), recursive=True):
        yield p, acentuar_template
    for p in glob.glob(os.path.join(RAIZ, "app", "static", "js", "*.js")):
        if not p.endswith(".min.js"):
            yield p, acentuar_strings_com_espaco
    for p in glob.glob(os.path.join(RAIZ, "app", "**", "*.py"), recursive=True):
        base = os.path.basename(p)
        if base.startswith("whatsapp") or base in ("emailing.py", "sms.py", "migracao_dados.py"):
            continue
        yield p, acentuar_python


def main():
    checar = "--checar" in sys.argv
    mudados = []
    for p, funcao in arquivos():
        s = io.open(p, encoding="utf-8").read()
        novo = funcao(s)
        if novo != s:
            mudados.append(os.path.relpath(p, RAIZ))
            if not checar:
                io.open(p, "w", encoding="utf-8", newline="\n").write(novo)
    print(("Sem acento em: " if checar else "Acentuados: ") + str(len(mudados)))
    for m in mudados:
        print("  " + m)
    return 1 if checar and mudados else 0


if __name__ == "__main__":
    sys.exit(main())
