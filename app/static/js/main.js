// JavaScript do projeto

// Confirmacao antes de enviar: <form data-confirm-excluir="Pergunta?">. Em
// atributo (nao onsubmit="return confirm('...')") pra nome com aspas nao
// quebrar o JS. Registrado antes da trava de duplo envio abaixo, que olha
// defaultPrevented.
document.querySelectorAll("form[data-confirm-excluir]").forEach(function (form) {
    form.addEventListener("submit", function (evento) {
        if (!window.confirm(form.getAttribute("data-confirm-excluir"))) {
            evento.preventDefault();
        }
    });
});

// Menu "⋯" do cabecalho (macro menu_acoes em _macros.html): fecha ao tocar
// fora dele ou com Esc.
(function () {
    var menus = document.querySelectorAll("[data-menu-acoes]");
    if (!menus.length) return;
    document.addEventListener("click", function (evento) {
        menus.forEach(function (menu) {
            if (menu.open && !menu.contains(evento.target)) menu.open = false;
        });
    });
    document.addEventListener("keydown", function (evento) {
        if (evento.key === "Escape") menus.forEach(function (menu) { menu.open = false; });
    });
    menus.forEach(function (menu) {
        menu.querySelectorAll("[data-tutorial-reiniciar]").forEach(function (item) {
            item.addEventListener("click", function () { menu.open = false; });
        });
    });
})();

// Evita duplo-envio de formulario (duplo clique, ou clicar de novo por
// impaciencia enquanto a resposta nao volta -- ex: banco hibernado
// acordando, ver CLAUDE.md sobre cold start do Neon) -- desabilita o botao
// de submit assim que o form REALMENTE vai ser enviado. Causa real
// confirmada em producao: sem essa trava, um usuario acabou criando o
// mesmo Ministerio e o mesmo Membro varias vezes seguidas.
//
// So desabilita se o evento nao foi cancelado por outro handler antes
// (evento.defaultPrevented) -- isso cobre os dois casos que NAO devem
// desabilitar o botao: um onsubmit="return confirm(...)" que o usuario
// cancelou (nada foi enviado), ou um form que ja se vira sozinho via
// fetch/AJAX chamando preventDefault (ex: o chat do dashboard, ou a
// exclusao em lote acima) -- inline onsubmit e handlers de script no fim
// do body correm ANTES deste (registrados antes no parse da pagina),
// entao por essa altura defaultPrevented ja reflete a decisao deles.
document.querySelectorAll("form").forEach(function (form) {
    if (form.hasAttribute("data-selecao-form")) return; // cuida do proprio estado

    form.addEventListener("submit", function (evento) {
        if (evento.defaultPrevented) return;
        var botao = form.querySelector('button[type="submit"], input[type="submit"]');
        if (botao && !botao.disabled) {
            // setTimeout(0) de proposito -- desabilitar o botao de forma
            // SINCRONA dentro do proprio handler de submit e uma pegadinha
            // conhecida: alguns navegadores tratam isso como se o campo
            // nunca tivesse existido a tempo de montar o envio, e o form
            // simplesmente nao e enviado (nem da erro, so nao acontece
            // nada). Adiar pro proximo tick deixa o navegador terminar de
            // processar o envio em curso antes de desabilitar o botao.
            setTimeout(function () {
                botao.disabled = true;
                botao.setAttribute("data-travado-no-envio", "");
            }, 0);
        }
    });
});

// Barra de progresso no topo (ver #barra-carregamento em base.html) --
// mostra em QUALQUER navegacao real (link ou form) pra suavizar a espera,
// mais perceptivel quando o banco esta "acordando" (mesmo cold start do
// Neon comentado acima). Nao tenta "terminar" a barra: a pagina atual vai
// ser descartada de qualquer forma quando a proxima carregar, entao so
// precisa aparecer e crescer, nunca precisa esconder sozinha.
(function () {
    var barra = document.getElementById("barra-carregamento");
    if (!barra) return;

    function iniciar() {
        barra.classList.add("carregando");
        barra.style.width = "20%";
        // Cresce aos poucos, cada vez mais devagar -- da a sensacao de
        // progresso real sem prometer um tempo exato (nao sabemos quanto
        // vai demorar). Nunca chega a 100% sozinha de proposito: 100%
        // pareceria "pronto" e a pagina ainda nao trocou.
        setTimeout(function () { barra.style.width = "45%"; }, 150);
        setTimeout(function () { barra.style.width = "65%"; }, 500);
        setTimeout(function () { barra.style.width = "80%"; }, 1500);
    }

    // Voltar pelo navegador reaproveita a pagina da memoria (bfcache) do
    // jeito que ela estava ao sair: barra no meio do caminho e botao de
    // envio travado. Zera os dois, senao a tela "volta travada".
    window.addEventListener("pageshow", function (evento) {
        if (!evento.persisted) return;
        barra.classList.remove("carregando");
        barra.style.width = "0%";
        document.querySelectorAll("[data-travado-no-envio]").forEach(function (botao) {
            botao.disabled = false;
            botao.removeAttribute("data-travado-no-envio");
        });
    });

    document.addEventListener("click", function (evento) {
        var link = evento.target.closest("a[href]");
        if (!link) return;
        if (link.target === "_blank" || link.hasAttribute("download")) return;
        if (evento.defaultPrevented || evento.button !== 0) return;
        if (evento.metaKey || evento.ctrlKey || evento.shiftKey || evento.altKey) return; // abrir em nova aba/janela

        var href = link.getAttribute("href");
        if (!href || href.charAt(0) === "#") return;
        try {
            var destino = new URL(href, window.location.href);
            if (destino.origin !== window.location.origin) return; // link externo
            if (destino.pathname === window.location.pathname && destino.hash) return; // so ancora na mesma pagina
        } catch (e) {
            return;
        }

        iniciar();
    });

    document.querySelectorAll("form").forEach(function (form) {
        if (form.hasAttribute("data-selecao-form")) return; // tratado a parte, ver selecao em lote abaixo

        form.addEventListener("submit", function (evento) {
            if (evento.defaultPrevented) return; // form que se vira sozinho via fetch/AJAX (ex: chat)
            iniciar();
        });
    });
})();

// Selecao em lote generica (excluir varias comunidades/escalas de uma vez) --
// funciona em qualquer pagina que tenha, no maximo, UM <form data-selecao-form>
// com checkboxes [data-selecao-item] (cada um com [data-selecao-url] apontando
// pra rota de exclusao INDIVIDUAL daquele item), uma barra [data-selecao-barra]
// (com checkbox [data-selecao-todas], botao [data-selecao-excluir] e um
// <span data-selecao-contagem>), e um botao [data-selecao-alternar] (fora do
// form) que entra/sai do modo selecao. Ver comunidade/lista.html e
// ministerio/detalhe.html pros dois usos.
//
// Importante: exclui um item POR VEZ via fetch sequencial nas rotas de
// exclusao individual (ja provadas rapidas/confiaveis), em vez de mandar
// tudo junto num POST so pra uma rota de "excluir varias". Um lote grande
// numa unica requisicao (varias comunidades, cada uma cascateando bastante
// coisa) podia demorar o bastante pra estourar o timeout do servidor --
// nesse caso a conexao e derrubada no meio, sem chance nem da nossa propria
// pagina de erro aparecer (o navegador so mostra "Internal Server Error" cru),
// e pior, se o timeout bater ANTES do commit, nada fica salvo. Excluindo um
// de cada vez, cada requisicao e curta e ja comprovadamente funciona.
(function () {
    var form = document.querySelector("[data-selecao-form]");
    if (!form) return;

    var botaoAlternar = document.querySelector("[data-selecao-alternar]");
    var itens = form.querySelectorAll("[data-selecao-item]");
    var todasCheckbox = form.querySelector("[data-selecao-todas]");
    var barra = form.querySelector("[data-selecao-barra]");
    var botaoExcluir = form.querySelector("[data-selecao-excluir]");
    var contagemEl = form.querySelector("[data-selecao-contagem]");
    var textoExcluir = form.querySelector("[data-selecao-excluir-texto]");
    var csrfInput = form.querySelector('input[name="csrf_token"]');
    var csrf = csrfInput ? csrfInput.value : "";
    if (!itens.length) return;

    function atualizarContagem() {
        var marcados = 0;
        itens.forEach(function (item) { if (item.checked) marcados++; });
        if (contagemEl) contagemEl.textContent = marcados;
        if (botaoExcluir) botaoExcluir.disabled = marcados === 0;
        if (todasCheckbox) todasCheckbox.checked = marcados === itens.length;
    }

    if (botaoAlternar) {
        // Texto/icone em elementos separados (nao textContent do botao
        // inteiro) pra nao apagar o icone junto na hora de trocar o rotulo.
        var textoAlternar = botaoAlternar.querySelector("[data-selecao-alternar-texto]");
        var iconeAlternar = botaoAlternar.querySelector("[data-selecao-alternar-icone]");

        botaoAlternar.addEventListener("click", function () {
            var entrando = itens[0].classList.contains("hidden");
            itens.forEach(function (item) {
                item.classList.toggle("hidden", !entrando);
                if (!entrando) item.checked = false;
            });
            if (barra) barra.classList.toggle("hidden", !entrando);
            if (textoAlternar) textoAlternar.textContent = entrando ? "Cancelar" : "Selecionar";
            if (iconeAlternar) {
                iconeAlternar.classList.toggle("fa-square-check", !entrando);
                iconeAlternar.classList.toggle("fa-xmark", entrando);
            }
            atualizarContagem();
        });
    }

    itens.forEach(function (item) { item.addEventListener("change", atualizarContagem); });
    if (todasCheckbox) {
        todasCheckbox.addEventListener("change", function () {
            itens.forEach(function (item) { item.checked = todasCheckbox.checked; });
            atualizarContagem();
        });
    }

    function excluirUm(url) {
        return fetch(url, {
            method: "POST",
            credentials: "same-origin",
            headers: { "Content-Type": "application/x-www-form-urlencoded" },
            body: "csrf_token=" + encodeURIComponent(csrf),
        }).then(function (resposta) { return resposta.ok; }).catch(function () { return false; });
    }

    form.addEventListener("submit", function (evento) {
        evento.preventDefault();
        var selecionados = [];
        itens.forEach(function (item) { if (item.checked) selecionados.push(item); });
        if (!selecionados.length) return;

        var mensagem = form.dataset.selecaoConfirmar || "Excluir os itens selecionados? Essa acao nao pode ser desfeita.";
        if (!window.confirm(mensagem)) return;

        var total = selecionados.length;
        var falhas = 0;
        if (botaoExcluir) botaoExcluir.disabled = true;
        if (todasCheckbox) todasCheckbox.disabled = true;

        function processar(indice) {
            if (indice >= total) {
                if (falhas > 0) {
                    window.alert(
                        falhas + " de " + total + " nao puderam ser excluidos agora. " +
                        "O que deu certo ja foi salvo -- confira a lista e tente de novo com o restante."
                    );
                }
                window.location.reload();
                return;
            }
            if (textoExcluir) textoExcluir.textContent = "Excluindo " + (indice + 1) + " de " + total + "...";
            var url = selecionados[indice].dataset.selecaoUrl;
            excluirUm(url).then(function (ok) {
                if (!ok) falhas++;
                processar(indice + 1);
            });
        }
        processar(0);
    });
})();

// Botao de excluir 1 item FORA de um form de selecao em lote (ex: cada
// comunidade na lista, comunidade/lista.html) -- confirma e monta um
// <form> escondido na hora pra enviar o POST. Nao da pra so colocar um
// <form> ao redor do botao no HTML porque cada card ja fica dentro do
// <form data-selecao-form> que envolve a lista inteira (form dentro de
// form e invalido, o navegador ignora o de dentro).
document.querySelectorAll("[data-excluir-item]").forEach(function (botao) {
    botao.addEventListener("click", function () {
        var mensagem = botao.getAttribute("data-excluir-confirmar") || "Tem certeza?";
        if (!window.confirm(mensagem)) return;

        var campoCsrf = document.querySelector('input[name="csrf_token"]');
        var form = document.createElement("form");
        form.method = "POST";
        form.action = botao.getAttribute("data-excluir-item");
        form.style.display = "none";
        if (campoCsrf) {
            var campo = document.createElement("input");
            campo.type = "hidden";
            campo.name = "csrf_token";
            campo.value = campoCsrf.value;
            form.appendChild(campo);
        }
        document.body.appendChild(form);
        form.submit();
    });
});

// Registra o service worker (PWA instalavel) -- so assets estaticos entram
// em cache, ver app/static/js/service-worker.js. Progressive enhancement:
// navegadores sem suporte (ou http local sem TLS) simplesmente ignoram.
if ("serviceWorker" in navigator) {
    window.addEventListener("load", function () {
        navigator.serviceWorker.register("/service-worker.js").catch(function () {
            /* instalacao como app e um extra, nao pode quebrar o site se falhar */
        });
    });
}

// Aviso de troca/perda de sessao nesta aba. O cookie de sessao do Flask-Login
// e compartilhado por todo o navegador (nao por aba) -- logar com outra conta
// numa aba troca a sessao usada por todas as outras abas do mesmo dominio,
// sem nenhum aviso. Isso compara periodicamente o usuario autenticado no
// servidor com o usuario que renderizou esta pagina (ver data-user-id em
// templates/base.html + GET /auth/sessao-atual) e avisa quando divergem, em
// vez de deixar a aba continuar mostrando dados/acoes do usuario antigo
// silenciosamente.
(function vigiaTrocaDeSessao() {
    var idInicial = document.body.dataset.userId;
    if (!idInicial) return; // pagina publica/nao autenticada: nada a vigiar

    var avisado = false;

    function verificar() {
        if (avisado) return;
        fetch("/auth/sessao-atual", { credentials: "same-origin" })
            .then(function (resposta) { return resposta.json(); })
            .then(function (dados) {
                var idAtual = (dados.usuario_id === null || dados.usuario_id === undefined)
                    ? null
                    : String(dados.usuario_id);
                if (idAtual !== idInicial) {
                    avisado = true;
                    mostrarAviso(idAtual);
                }
            })
            .catch(function () { /* falha de rede: tenta de novo no proximo ciclo */ });
    }

    function mostrarAviso(idAtual) {
        var aviso = document.createElement("div");
        aviso.setAttribute("role", "alert");
        aviso.style.cssText =
            "position:fixed;top:0;left:0;right:0;z-index:9999;" +
            "background:#b91c1c;color:#fff;padding:10px 16px;" +
            "font:14px/1.4 ui-sans-serif,system-ui,sans-serif;" +
            "display:flex;align-items:center;justify-content:center;gap:12px;flex-wrap:wrap;";

        var texto = document.createElement("span");
        texto.textContent = idAtual === null
            ? "Sua sessao foi encerrada neste navegador (login/logout em outra aba). Recarregue a pagina."
            : "A conta logada neste navegador mudou em outra aba. Recarregue a pagina para ver os dados corretos.";

        var botao = document.createElement("button");
        botao.type = "button";
        botao.textContent = "Recarregar";
        botao.style.cssText =
            "background:#fff;color:#b91c1c;border:0;border-radius:6px;" +
            "padding:4px 12px;font-weight:600;cursor:pointer;";
        botao.addEventListener("click", function () { window.location.reload(); });

        aviso.appendChild(texto);
        aviso.appendChild(botao);
        document.body.prepend(aviso);
    }

    var INTERVALO_MS = 20000;
    setInterval(verificar, INTERVALO_MS);
    document.addEventListener("visibilitychange", function () {
        if (document.visibilityState === "visible") verificar();
    });
    window.addEventListener("focus", verificar);
})();

// Mostrar/ocultar senha: qualquer botao com [data-toggle-senha="<id-do-input>"]
// alterna o input entre type="password"/"text" e troca de icone (olho aberto/fechado).
// Generico de proposito -- funciona em qualquer tela (login, cadastro, futuras)
// sem precisar de JS por pagina.
(function habilitarToggleSenha() {
    document.querySelectorAll("[data-toggle-senha]").forEach(function (botao) {
        var input = document.getElementById(botao.getAttribute("data-toggle-senha"));
        if (!input) return;

        var iconeAberto = botao.querySelector("[data-icone-aberto]");
        var iconeFechado = botao.querySelector("[data-icone-fechado]");

        botao.addEventListener("click", function () {
            var mostrando = input.type === "text";
            input.type = mostrando ? "password" : "text";
            if (iconeAberto) iconeAberto.classList.toggle("hidden", !mostrando);
            if (iconeFechado) iconeFechado.classList.toggle("hidden", mostrando);
            botao.setAttribute("aria-label", mostrando ? "Mostrar senha" : "Ocultar senha");
        });
    });
})();

// Tutorial guiado (spotlight): funciona em qualquer pagina com
// <script type="application/json" id="tutorial-dados"> (macro tutorial() em
// _macros.html; passos em app/tutoriais.py) -- {urlConcluir, csrf, passos:
// [{seletor, titulo, texto}], autoIniciar}. Seletor null = passo centralizado
// (boas-vindas/conclusao). Passo cujo elemento nao esta visivel na pagina
// (ex: botao so de lider) e pulado. Fundo sempre escurecido (inclusive nos
// passos centralizados, senao o balao fica "solto" em cima do conteudo); no
// celular o balao ocupa a largura toda e vai pra cima ou pra baixo do
// elemento destacado, onde couber. Recomeca por [data-tutorial-reiniciar].
(function () {
    var dadosEl = document.getElementById("tutorial-dados");
    if (!dadosEl) return;

    var dados;
    try {
        dados = JSON.parse(dadosEl.textContent);
    } catch (e) {
        return; // JSON malformado nao deveria travar a pagina inteira
    }
    if (!(dados.passos || []).length) return;

    var MARGEM = 16;
    var aberto = false;

    function visivel(el) {
        if (!el) return false;
        var r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0;
    }

    function passosDaPagina() {
        return dados.passos.filter(function (passo) {
            return !passo.seletor || visivel(document.querySelector(passo.seletor));
        });
    }

    function botao(texto, primario) {
        var b = document.createElement("button");
        b.type = "button";
        b.textContent = texto;
        b.style.cssText = primario
            ? "background:#4f46e5;color:#fff;border:0;border-radius:999px;padding:10px 20px;font-size:14px;font-weight:600;cursor:pointer;"
            : "background:none;border:0;color:#9ca3af;font-size:14px;font-weight:500;cursor:pointer;padding:10px 4px;";
        return b;
    }

    function iniciar() {
        if (aberto) return;
        var passos = passosDaPagina();
        if (!passos.length) return;
        aberto = true;
        var atual = 0;

        // Escurece a tela toda; o recorte em volta do elemento destacado vem
        // do box-shadow gigante do "destaque".
        var fundo = document.createElement("div");
        fundo.style.cssText = "position:fixed;inset:0;z-index:9990;background:rgba(15,23,42,.72);transition:opacity .2s ease;";
        var destaque = document.createElement("div");
        destaque.style.cssText =
            "position:fixed;z-index:9991;border-radius:16px;pointer-events:none;" +
            "box-shadow:0 0 0 3px rgba(129,140,248,.9),0 0 0 9999px rgba(15,23,42,.72);" +
            "transition:top .25s ease,left .25s ease,width .25s ease,height .25s ease;display:none;";
        var card = document.createElement("div");
        card.setAttribute("role", "dialog");
        card.setAttribute("aria-modal", "true");
        card.style.cssText =
            "position:fixed;z-index:9992;background:#111827;color:#fff;border:1px solid rgba(255,255,255,.08);" +
            "border-radius:20px;padding:20px;box-shadow:0 24px 48px rgba(0,0,0,.45);box-sizing:border-box;" +
            "font:15px/1.55 Inter,ui-sans-serif,system-ui,sans-serif;transition:top .25s ease,opacity .2s ease;";

        document.body.appendChild(fundo);
        document.body.appendChild(destaque);
        document.body.appendChild(card);

        function concluir() {
            fundo.remove();
            destaque.remove();
            card.remove();
            document.removeEventListener("keydown", aoTeclar);
            window.removeEventListener("resize", reposicionar);
            aberto = false;
            if (!dados.urlConcluir) return;
            fetch(dados.urlConcluir, {
                method: "POST",
                credentials: "same-origin",
                headers: { "Content-Type": "application/x-www-form-urlencoded" },
                body: "csrf_token=" + encodeURIComponent(dados.csrf || ""),
            }).catch(function () { /* melhor esforco -- nao bloqueia a UI */ });
        }

        function montarCard(indice) {
            var passo = passos[indice];
            var ultimo = indice === passos.length - 1;
            card.textContent = "";

            var pontos = document.createElement("div");
            pontos.style.cssText = "display:flex;gap:6px;margin-bottom:12px;";
            passos.forEach(function (_, i) {
                var p = document.createElement("span");
                p.style.cssText = "height:6px;border-radius:999px;transition:all .2s;" +
                    (i === indice ? "width:18px;background:#818cf8;" : "width:6px;background:rgba(255,255,255,.25);");
                pontos.appendChild(p);
            });
            var titulo = document.createElement("h3");
            titulo.textContent = passo.titulo;
            titulo.style.cssText = "font-size:17px;font-weight:700;margin:0 0 6px;line-height:1.3;";
            var texto = document.createElement("p");
            texto.textContent = passo.texto;
            texto.style.cssText = "margin:0 0 16px;color:#d1d5db;";

            var acoes = document.createElement("div");
            acoes.style.cssText = "display:flex;align-items:center;gap:8px;";
            var pular = botao(ultimo ? "" : "Pular", false);
            pular.addEventListener("click", concluir);
            if (ultimo) pular.style.visibility = "hidden";
            var espaco = document.createElement("span");
            espaco.style.flex = "1";
            acoes.appendChild(pular);
            acoes.appendChild(espaco);
            if (indice > 0) {
                var voltar = botao("Voltar", false);
                voltar.style.color = "#e5e7eb";
                voltar.addEventListener("click", function () { irPara(indice - 1); });
                acoes.appendChild(voltar);
            }
            var proximo = botao(ultimo ? "Concluir" : "Próximo", true);
            proximo.addEventListener("click", function () {
                if (ultimo) concluir(); else irPara(indice + 1);
            });
            acoes.appendChild(proximo);

            card.appendChild(pontos);
            card.appendChild(titulo);
            card.appendChild(texto);
            card.appendChild(acoes);
            proximo.focus({ preventScroll: true, focusVisible: false });
        }

        function posicionar(indice) {
            var passo = passos[indice];
            var alvo = passo.seletor ? document.querySelector(passo.seletor) : null;
            var largura = Math.min(360, window.innerWidth - MARGEM * 2);
            card.style.width = largura + "px";

            if (!alvo) {
                destaque.style.display = "none";
                fundo.style.opacity = "1";
                card.style.left = (window.innerWidth - largura) / 2 + "px";
                card.style.top = Math.max(MARGEM, (window.innerHeight - card.offsetHeight) / 2) + "px";
                return;
            }
            // Com destaque, o escurecimento vem do box-shadow dele.
            fundo.style.opacity = "0";
            var r = alvo.getBoundingClientRect();
            var folga = 6;
            // Elemento mais alto que a tela (ex: grade inteira): destaca so a parte visivel.
            var topo = Math.max(r.top, 8), base = Math.min(r.bottom, window.innerHeight - 8);
            destaque.style.display = "block";
            destaque.style.top = (topo - folga) + "px";
            destaque.style.left = (r.left - folga) + "px";
            destaque.style.width = (r.width + folga * 2) + "px";
            destaque.style.height = (base - topo + folga * 2) + "px";

            var altura = card.offsetHeight;
            var embaixo = base + folga + 12;
            var emCima = topo - folga - 12 - altura;
            var top;
            if (embaixo + altura <= window.innerHeight - MARGEM) top = embaixo;
            else if (emCima >= MARGEM) top = emCima;
            else top = window.innerHeight - altura - MARGEM; // sem espaco: rodape da tela
            card.style.top = top + "px";
            var esquerda = r.left + r.width / 2 - largura / 2;
            card.style.left = Math.min(Math.max(esquerda, MARGEM), window.innerWidth - largura - MARGEM) + "px";
        }

        function irPara(indice) {
            atual = indice;
            montarCard(indice);
            var passo = passos[indice];
            var alvo = passo.seletor ? document.querySelector(passo.seletor) : null;
            if (alvo) {
                var r = alvo.getBoundingClientRect();
                var cabe = r.top >= 0 && r.bottom <= window.innerHeight;
                if (!cabe) {
                    alvo.scrollIntoView({ block: r.height > window.innerHeight * 0.6 ? "start" : "center" });
                }
            }
            posicionar(indice);
        }

        function reposicionar() { posicionar(atual); }

        function aoTeclar(evento) {
            if (evento.key === "Escape") concluir();
            else if (evento.key === "ArrowRight" && atual < passos.length - 1) irPara(atual + 1);
            else if (evento.key === "ArrowLeft" && atual > 0) irPara(atual - 1);
        }

        document.addEventListener("keydown", aoTeclar);
        window.addEventListener("resize", reposicionar);
        irPara(0);
    }

    // Comeca sozinho na 1a visita, depois que a pagina terminou de montar
    // (fontes/icones mudam o tamanho dos elementos destacados).
    if (dados.autoIniciar) {
        if (document.readyState === "complete") setTimeout(iniciar, 250);
        else window.addEventListener("load", function () { setTimeout(iniciar, 250); });
    }

    document.querySelectorAll("[data-tutorial-reiniciar]").forEach(function (botaoRever) {
        botaoRever.addEventListener("click", function () {
            window.scrollTo(0, 0);
            iniciar();
        });
    });
})();

// Botao "Copiar" generico -- usado pelo link de convite da comunidade
// (comunidade/papeis.html), mas escrito sem nada especifico dele: qualquer
// botao com data-copiar-link="<id-do-input>" copia o value desse input.
document.querySelectorAll("[data-copiar-link]").forEach(function (botao) {
    var input = document.getElementById(botao.getAttribute("data-copiar-link"));
    if (!input) return;

    var textoOriginal = botao.innerHTML;
    botao.addEventListener("click", function () {
        navigator.clipboard.writeText(input.value).then(function () {
            botao.innerHTML = "<i class=\"fa-solid fa-check mr-1\"></i>Copiado!";
            setTimeout(function () { botao.innerHTML = textoOriginal; }, 2000);
        });
    });
});

// Reduz fotos antes do upload (input[type=file][data-reduzir-imagem]).
// Foto de celular costuma ter 3-12 MB e o servidor recusa qualquer
// requisicao acima de 2 MB (MAX_CONTENT_LENGTH) -- sem isso, escolher uma
// foto tirada na hora quebrava a criacao/edicao de Comunidade e Ministerio.
// Redimensiona pro lado maior ter no maximo LADO_MAX px e recomprime
// (PNG continua PNG, pra manter transparencia de logo; se ainda passar do
// limite vira JPEG). Ao terminar dispara "imagem:pronta" no input (detail =
// arquivo final) -- quem quiser mostrar preview escuta esse evento em vez
// de "change", que dispara antes da reducao acabar.
(function () {
    var LADO_MAX = 1024;
    var LIMITE = 2 * 1024 * 1024;
    var JA_PEQUENO = 300 * 1024;

    function exportar(canvas, tipo, nomeBase) {
        return new Promise(function (resolve) {
            canvas.toBlob(function (blob) {
                if (!blob) { resolve(null); return; }
                var extensao = tipo === 'image/png' ? '.png' : '.jpg';
                resolve(new File([blob], nomeBase + extensao, { type: tipo }));
            }, tipo, 0.85);
        });
    }

    function reduzir(arquivo) {
        return new Promise(function (resolve, reject) {
            var url = URL.createObjectURL(arquivo);
            var img = new Image();
            img.onload = function () {
                URL.revokeObjectURL(url);
                var escala = Math.min(1, LADO_MAX / Math.max(img.naturalWidth, img.naturalHeight));
                var canvas = document.createElement('canvas');
                canvas.width = Math.max(1, Math.round(img.naturalWidth * escala));
                canvas.height = Math.max(1, Math.round(img.naturalHeight * escala));
                canvas.getContext('2d').drawImage(img, 0, 0, canvas.width, canvas.height);
                var nomeBase = (arquivo.name || 'imagem').replace(/\.[^.]+$/, '') || 'imagem';
                var tipo = arquivo.type === 'image/png' ? 'image/png' : 'image/jpeg';
                exportar(canvas, tipo, nomeBase).then(function (resultado) {
                    if (resultado && resultado.size > LIMITE && tipo === 'image/png') {
                        return exportar(canvas, 'image/jpeg', nomeBase);
                    }
                    return resultado;
                }).then(function (resultado) {
                    if (resultado) resolve(resultado); else reject();
                });
            };
            img.onerror = function () { URL.revokeObjectURL(url); reject(); };
            img.src = url;
        });
    }

    document.querySelectorAll('input[type="file"][data-reduzir-imagem]').forEach(function (input) {
        input.addEventListener('change', function () {
            var arquivo = input.files && input.files[0];
            if (!arquivo) return;

            function pronto(final) {
                input.dispatchEvent(new CustomEvent('imagem:pronta', { detail: final }));
            }

            var jaServe = arquivo.size <= JA_PEQUENO &&
                (arquivo.type === 'image/jpeg' || arquivo.type === 'image/png');
            if (jaServe || typeof DataTransfer === 'undefined') { pronto(arquivo); return; }

            var botoes = input.form ? input.form.querySelectorAll('[type="submit"]') : [];
            Array.prototype.forEach.call(botoes, function (b) { b.disabled = true; });

            reduzir(arquivo).then(function (novo) {
                var transferencia = new DataTransfer();
                transferencia.items.add(novo);
                input.files = transferencia.files;
                pronto(novo);
            }).catch(function () {
                // Formato que o navegador nao decodifica (ex: HEIC fora do
                // Safari): segue o original e o servidor responde com a
                // mensagem de formato invalido.
                pronto(arquivo);
            }).then(function () {
                Array.prototype.forEach.call(botoes, function (b) { b.disabled = false; });
            });
        });
    });
})();

/* Formulario "Adicionar pessoa" (Papeis da Comunidade/Ministerio): avisa,
   ANTES de enviar, se a pessoa entra na hora ou recebe um convite -- ver
   app/convites/adicao.py e convites.routes.verificar_adicao. O botao muda
   de texto junto, pra ninguem achar que alguem ja entrou quando so foi
   convidado. Sem resposta (offline/erro), o form continua funcionando
   normal; a mensagem final vem do servidor de qualquer jeito. */
(function () {
    var MENSAGENS = {
        adicionar: ['A pessoa ja tem conta e vai entrar na hora.', 'text-green-500', 'Adicionar'],
        ja_faz_parte: ['Essa pessoa ja faz parte com esse papel.', 'text-amber-500', 'Adicionar'],
        sem_conta: ['A pessoa ainda nao tem conta: vai um convite por e-mail, e ela so entra depois de se cadastrar e aceitar.', 'text-amber-500', 'Enviar convite'],
        exige_aprovacao: ['Essa pessoa exige aprovacao pra entrar em grupos: vai um convite, e ela so entra depois de aceitar.', 'text-amber-500', 'Enviar convite'],
        muda_papel: ['Essa pessoa ja faz parte com outro papel: vai um convite, e a mudanca so vale depois que ela aceitar.', 'text-amber-500', 'Enviar convite']
    };

    document.querySelectorAll('form[data-verificar-adicao-url]').forEach(function (form) {
        var email = form.querySelector('input[name="email"]');
        var papel = form.querySelector('select[name="papel"]');
        var aviso = form.querySelector('[data-aviso-adicao]');
        var botao = form.querySelector('[type="submit"]');
        if (!email || !aviso) return;
        var espera = null;
        var ultimaConsulta = 0;

        function limpar() {
            aviso.classList.add('hidden');
            if (botao) botao.value = 'Adicionar';
        }

        function verificar() {
            var valor = email.value.trim();
            if (valor.indexOf('@') < 1) { limpar(); return; }
            var consulta = ++ultimaConsulta;
            var url = form.getAttribute('data-verificar-adicao-url') +
                '&email=' + encodeURIComponent(valor) +
                '&papel=' + encodeURIComponent(papel ? papel.value : '');
            fetch(url, { credentials: 'same-origin', headers: { 'Accept': 'application/json' } })
                .then(function (r) { return r.ok ? r.json() : null; })
                .then(function (dados) {
                    if (consulta !== ultimaConsulta) return; // resposta velha
                    var chave = dados && (dados.modo === 'convite' ? dados.motivo : dados.modo);
                    var info = chave && MENSAGENS[chave];
                    if (!info) { limpar(); return; }
                    aviso.textContent = info[0];
                    aviso.classList.remove('hidden', 'text-green-500', 'text-amber-500');
                    aviso.classList.add(info[1]);
                    if (botao) botao.value = info[2];
                })
                .catch(limpar);
        }

        email.addEventListener('input', function () {
            clearTimeout(espera);
            espera = setTimeout(verificar, 400);
        });
        if (papel) papel.addEventListener('change', verificar);
    });
})();

/* Formulario "pra quem enviar o repertorio" (templates/ministerio/_envio.html):
   varios ministerios e/ou funcoes marcados de uma vez. Marcar "Todo o
   ministerio" desliga as funcoes dele (ja estao incluidas). O botao de
   enviar do form so liga com algo marcado. */
(function () {
    document.querySelectorAll('[data-envio]').forEach(function (caixa) {
        var resumo = caixa.querySelector('[data-envio-resumo]');
        var form = caixa.closest('form');
        var botoes = form ? form.querySelectorAll('[type="submit"]') : [];

        function atualizar() {
            var grupos = 0;
            caixa.querySelectorAll('[data-envio-ministerio]').forEach(function (bloco) {
                var todo = bloco.querySelector('[data-envio-todo]');
                var funcoes = bloco.querySelectorAll('[data-envio-funcao]');
                funcoes.forEach(function (f) {
                    if (todo.checked) f.checked = false;
                    f.disabled = todo.checked || f.getAttribute('data-pessoas') === '0';
                });
                var marcados = (todo.checked ? 1 : 0) + bloco.querySelectorAll('[data-envio-funcao]:checked').length;
                grupos += marcados;
                var etiqueta = bloco.querySelector('[data-envio-marcados]');
                etiqueta.textContent = todo.checked ? 'todo' : marcados + ' funcao' + (marcados > 1 ? 'oes' : '');
                etiqueta.classList.toggle('hidden', !marcados);
            });
            resumo.textContent = grupos
                ? grupos + ' grupo(s) marcado(s) -- quem estiver em mais de um recebe uma vez so.'
                : 'Marque pelo menos um ministerio ou funcao.';
            Array.prototype.forEach.call(botoes, function (b) { b.disabled = !grupos; });
        }

        caixa.addEventListener('change', atualizar);
        atualizar();
    });
})();
