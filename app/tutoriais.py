"""Tutoriais guiados (spotlight) das telas principais.

Cada tutorial e uma lista de passos {seletor, titulo, texto}: o seletor bate
com um atributo data-tutorial="..." no template; None = passo centralizado
(boas-vindas/conclusao). Passo cujo elemento nao esta na pagina (ex: botao
que so o lider ve) e pulado sozinho pelo JS (static/js/main.js), entao a
mesma lista serve pra quem gerencia e pra quem so visualiza.

Comeca sozinho na 1a vez que a conta abre a tela; depois, so pelo botao
"Ver tutorial" (data-tutorial-reiniciar). Visto = User.tutoriais_vistos.
"""
from flask import url_for
from flask_wtf.csrf import generate_csrf

TUTORIAIS = {
    "comunidade": [
        {"seletor": None, "titulo": "Bem-vindo à sua comunidade!",
         "texto": "Em menos de um minuto você vê onde fica cada coisa. Toque em “Próximo” para avançar."},
        {"seletor": "[data-tutorial='membros']", "titulo": "Membros",
         "texto": "Todas as pessoas que podem ser escaladas, com telefone e e-mail. Elas não precisam ter conta no app."},
        {"seletor": "[data-tutorial='escalados']", "titulo": "Quem está escalado",
         "texto": "Num lugar só, quem serve em cada ministério, com filtro por data e função."},
        {"seletor": "[data-tutorial='banco']", "titulo": "Banco de músicas",
         "texto": "Cifras e letras de projeção da comunidade. Todos os ministérios usam estas músicas nas escalas."},
        {"seletor": "[data-tutorial='calendario']", "titulo": "Calendário",
         "texto": "Todas as escalas e eventos da comunidade, mês a mês."},
        {"seletor": "[data-tutorial='convites']", "titulo": "Papéis e convites",
         "texto": "Convide pessoas por e-mail ou link e defina quem é administrador ou membro."},
        {"seletor": "[data-tutorial='novo-ministerio']", "titulo": "Ministérios",
         "texto": "Cada área (Louvor, Mídia, Kids...) é um ministério. É dentro dele que as escalas são criadas."},
        {"seletor": None, "titulo": "Pronto!",
         "texto": "Para ver este tutorial de novo, toque no ? no topo da tela."},
    ],
    "ministerio": [
        {"seletor": None, "titulo": "Este é o ministério",
         "texto": "Aqui ficam as escalas, os rodízios e o calendário da equipe."},
        {"seletor": "[data-tutorial='nova-escala']", "titulo": "Criar uma escala",
         "texto": "Crie a escala de um culto ou evento. As funções da equipe já vêm prontas, é só escolher as pessoas."},
        {"seletor": "[data-tutorial='escalas']", "titulo": "Escalas",
         "texto": "Toque numa escala para ver a equipe, os ensaios, os materiais e o repertório."},
        {"seletor": "[data-tutorial='rodizios']", "titulo": "Rodízios",
         "texto": "Equipes que se revezam sozinhas. O app gera as próximas escalas automaticamente."},
        {"seletor": "[data-tutorial='calendario']", "titulo": "Calendário",
         "texto": "Os dias com escala ficam marcados. Toque num dia para abrir."},
        {"seletor": "[data-tutorial='menu']", "titulo": "Mais opções",
         "texto": "Banco de músicas, papéis e convites, editar e o tutorial ficam neste menu."},
    ],
    "escala": [
        {"seletor": None, "titulo": "Esta é a escala",
         "texto": "Veja quem serve em cada função, os ensaios, os materiais e o repertório do dia."},
        {"seletor": "[data-tutorial='funcoes']", "titulo": "Equipe",
         "texto": "Cada linha é uma função. Escolha a pessoa e confirme. Cada um marca aqui se confirmou presença ou se precisa de troca."},
        {"seletor": "[data-tutorial='notificar']", "titulo": "Avisar a equipe",
         "texto": "Manda e-mail, SMS e aviso no app para quem está escalado. O app também avisa sozinho 24h e 16h antes."},
        {"seletor": "[data-tutorial='repertorio']", "titulo": "Repertório",
         "texto": "As músicas do dia, com tom e momento. Daqui você gera a folha de cifras e a de projeção."},
        {"seletor": "[data-tutorial='menu']", "titulo": "Mais opções",
         "texto": "Editar ou excluir a escala e rever este tutorial."},
    ],
    "banco": [
        {"seletor": None, "titulo": "Banco de músicas",
         "texto": "Todas as músicas com cifra e letra de projeção, prontas para as escalas."},
        {"seletor": "[data-tutorial='busca']", "titulo": "Buscar",
         "texto": "Procure por nome, artista, tom ou tema (ex: cruz, graça). Os temas mais usados aparecem logo abaixo."},
        {"seletor": "[data-tutorial='modos']", "titulo": "Lista ou repertórios",
         "texto": "Em Lista, marque músicas para montar um repertório (ex: manhã, noite). Em Repertórios, veja e envie os prontos."},
        {"seletor": "[data-tutorial='baixar']", "titulo": "Baixar",
         "texto": "Baixa as músicas em Word (.docx), com a cifra alinhada. Com músicas marcadas, baixa só elas."},
        {"seletor": "[data-tutorial='adicionar']", "titulo": "Adicionar músicas",
         "texto": "Cadastre uma música à mão ou importe vários PDFs e documentos do Word de uma vez."},
    ],
}


def dados_do_tutorial(chave, usuario):
    """JSON pro <script id="tutorial-dados"> (ver templates/_macros.html)."""
    return {
        "urlConcluir": url_for("main.tutorial_visto", chave=chave),
        # generate_csrf() direto (nao o csrf_token() global do Jinja, que so
        # existe com CSRFProtect global -- nao e o caso aqui).
        "csrf": generate_csrf(),
        "passos": TUTORIAIS[chave],
        "autoIniciar": not usuario.viu_tutorial(chave),
    }
