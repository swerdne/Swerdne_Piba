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

// Mascara de telefone brasileiro: <input data-mascara-telefone>. Vai
// formatando enquanto digita -- "(DD) 9XXXX-XXXX" (celular, 11 digitos) ou
// "(DD) XXXX-XXXX" (fixo, 10). Quem comeca com "+" esta digitando o codigo
// do pais: "+55 28 99987-2102" vira "+55 (28) 99987-2102" (o 55 nao e
// confundido com DDD). Numero colado com 55 na frente e sem "+"
// (5528999872102) tambem perde o 55. A validacao de verdade e no servidor
// (app/telefones.py, que guarda sempre sem o +55); aqui e so pra ajudar.
(function () {
    function local(d) {
        d = d.slice(0, 11);
        if (!d) return "";
        if (d.length <= 2) return "(" + d;
        var ddd = "(" + d.slice(0, 2) + ") ", resto = d.slice(2);
        var corte = d.length === 11 ? 5 : 4;
        return resto.length > corte ? ddd + resto.slice(0, corte) + "-" + resto.slice(corte) : ddd + resto;
    }
    function mascarar(valor) {
        var texto = (valor || "").trim();
        var d = texto.replace(/\D/g, "");
        if (texto.charAt(0) === "+") {
            if (d.length <= 2) return "+" + d;  // ainda digitando o codigo do pais
            if (d.indexOf("55") !== 0) return "+" + d;  // outro pais: o servidor recusa com mensagem
            return "+55 " + local(d.slice(2));
        }
        if (d.length > 11 && d.indexOf("55") === 0) d = d.slice(2);
        return local(d);
    }
    document.querySelectorAll("input[data-mascara-telefone]").forEach(function (campo) {
        if (campo.value) campo.value = mascarar(campo.value);
        campo.addEventListener("input", function () {
            var fim = campo.selectionStart === campo.value.length;
            campo.value = mascarar(campo.value);
            if (fim) campo.setSelectionRange(campo.value.length, campo.value.length);
        });
    });
})();

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

    // Mini logo (#mini-carregando em base.html): liga MINI_ATRASO_MS depois
    // do toque (resposta rapida nem pisca), por timer de JS -- no iPhone o
    // timer roda durante a navegacao, mas um transition-delay do CSS
    // iniciado no toque ficava congelado (logo preso em 1%, conferido em
    // gravacao de tela). Some sozinha depois de MINI_LIMITE_MS: link que
    // baixa arquivo (sem atributo download) nao troca de pagina e ela
    // ficaria presa na tela.
    var mini = document.getElementById("mini-carregando");
    var MINI_ATRASO_MS = 250, MINI_LIMITE_MS = 10000;
    var miniTimer = 0, miniLigar = 0;
    function esconderMini() {
        clearTimeout(miniTimer);
        clearTimeout(miniLigar);
        if (!mini) return;
        mini.classList.remove("ligado");
        mini.setAttribute("aria-hidden", "true");
    }
    if (mini) {
        // Logo ja decodificado na memoria antes de qualquer toque.
        var miniImg = mini.querySelector("img");
        if (miniImg && miniImg.decode) miniImg.decode().catch(function () {});
    }

    function iniciar() {
        if (mini) {
            esconderMini();
            miniLigar = setTimeout(function () {
                mini.classList.add("ligado");
                mini.setAttribute("aria-hidden", "false");
            }, MINI_ATRASO_MS);
            miniTimer = setTimeout(esconderMini, MINI_LIMITE_MS);
        }
        barra.classList.add("carregando");
        barra.style.transform = "scaleX(0.2)";
        // Cresce aos poucos, cada vez mais devagar -- da a sensacao de
        // progresso real sem prometer um tempo exato (nao sabemos quanto
        // vai demorar). Nunca chega a 100% sozinha de proposito: 100%
        // pareceria "pronto" e a pagina ainda nao trocou.
        setTimeout(function () { barra.style.transform = "scaleX(0.45)"; }, 150);
        setTimeout(function () { barra.style.transform = "scaleX(0.65)"; }, 500);
        setTimeout(function () { barra.style.transform = "scaleX(0.80)"; }, 1500);
    }

    // Voltar pelo navegador reaproveita a pagina da memoria (bfcache) do
    // jeito que ela estava ao sair: barra no meio do caminho e botao de
    // envio travado. Zera os dois, senao a tela "volta travada".
    window.addEventListener("pageshow", function (evento) {
        if (!evento.persisted) return;
        esconderMini();
        barra.classList.remove("carregando");
        barra.style.transform = "scaleX(0)";
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

// Instalar o app ([data-instalar] = o que aparece so quando da pra instalar;
// [data-instalar-botao] = o que instala). Android/Chrome: o pedido do
// navegador (beforeinstallprompt, guardado cedo no <head> do base.html) abre
// a instalacao num toque. iPhone: a Apple nao deixa instalar por botao, entao
// abre o passo a passo (Compartilhar > Adicionar a Tela de Inicio). Android
// sem o pedido (Firefox etc.): passo a passo pelo menu do navegador. Ja
// instalado (aberto como app) ou computador sem suporte: nada aparece.
// [data-instalar-dispensavel] some por 30 dias com "Agora nao".
(function () {
    var alvos = document.querySelectorAll("[data-instalar]");
    if (!alvos.length) return;
    var instalado = (window.matchMedia && matchMedia("(display-mode: standalone)").matches) || navigator.standalone === true;
    if (instalado) return;

    var ua = navigator.userAgent;
    var ios = /iPhone|iPad|iPod/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1);
    // Chrome do Android (e Samsung, que tambem tem "Chrome/" no nome) manda o
    // pedido quando da pra instalar; sem pedido = ja instalado. So os outros
    // (Firefox...) precisam do passo a passo pelo menu.
    var androidSemPedido = /Android/.test(ua) && !/Chrome\//.test(ua);
    var CHAVE_DISPENSA = "instalar-app-dispensado-ate";

    function dispensado() {
        try { return Number(localStorage.getItem(CHAVE_DISPENSA) || 0) > Date.now(); } catch (e) { return false; }
    }
    function mostrar() {
        alvos.forEach(function (el) {
            if (el.hasAttribute("data-instalar-dispensavel") && dispensado()) return;
            el.hidden = false;
        });
    }
    function esconder() {
        alvos.forEach(function (el) { el.hidden = true; });
    }

    function passoAPasso() {
        var passos = ios
            ? ["Toque em <b>Compartilhar</b> " + '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-3px"><path d="M12 3v12M8 7l4-4 4 4"/><path d="M5 12v7a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-7"/></svg>' +
               " (no Safari fica na barra de baixo; no Chrome, na barra de endereço).",
               "Role a lista e toque em <b>Adicionar à Tela de Início</b>.",
               "Toque em <b>Adicionar</b>. O ícone do TyBenson aparece na tela inicial."]
            : ["Toque no menu do navegador <b>⋮</b> (no canto de cima).",
               "Toque em <b>Instalar app</b> ou <b>Adicionar à tela inicial</b>.",
               "Confirme. O ícone do TyBenson aparece na tela inicial."];
        if (!document.getElementById("estilo-instalar-app")) {
            // ::backdrop nao da pra por inline; e o reset do Tailwind zera a
            // margem que centraliza o <dialog>.
            var estilo = document.createElement("style");
            estilo.id = "estilo-instalar-app";
            estilo.textContent = "dialog[data-instalar-dialogo]::backdrop{background:rgba(2,3,15,.55)}";
            document.head.appendChild(estilo);
        }
        var dialogo = document.createElement("dialog");
        dialogo.setAttribute("aria-label", "Como instalar o app");
        dialogo.setAttribute("data-instalar-dialogo", "");
        dialogo.style.cssText = "margin:auto;border:0;border-radius:24px;padding:0;max-width:min(92vw,380px);width:100%;color:#111827;background:#fff;box-shadow:0 20px 50px rgba(0,0,0,.35)";
        dialogo.innerHTML =
            '<div style="padding:22px 22px 18px;font-family:inherit">' +
            '<p style="margin:0 0 4px;font-size:18px;font-weight:800">Instalar o TyBenson</p>' +
            '<p style="margin:0 0 16px;font-size:13px;color:#6b7280">' + (ios ? "No iPhone é assim (leva 10 segundos):" : "Pelo navegador é assim:") + "</p>" +
            '<ol style="margin:0;padding:0;list-style:none;display:grid;gap:12px">' +
            passos.map(function (texto, i) {
                return '<li style="display:flex;gap:12px;align-items:flex-start;font-size:14px;line-height:1.45">' +
                    '<span style="flex:none;width:26px;height:26px;border-radius:50%;background:#4f46e5;color:#fff;font-weight:700;font-size:13px;display:grid;place-items:center">' + (i + 1) + "</span>" +
                    "<span>" + texto + "</span></li>";
            }).join("") +
            "</ol>" +
            '<button type="button" data-fechar style="margin-top:20px;width:100%;border:0;border-radius:999px;background:#4f46e5;color:#fff;font-weight:700;font-size:15px;padding:12px">Entendi</button>' +
            "</div>";
        document.body.appendChild(dialogo);
        dialogo.addEventListener("close", function () { dialogo.remove(); });
        dialogo.addEventListener("click", function (e) {
            if (e.target === dialogo || e.target.closest("[data-fechar]")) dialogo.close();
        });
        if (dialogo.showModal) dialogo.showModal(); else dialogo.setAttribute("open", "");
    }

    document.addEventListener("click", function (e) {
        if (e.target.closest("[data-instalar-dispensar]")) {
            try { localStorage.setItem(CHAVE_DISPENSA, String(Date.now() + 30 * 24 * 3600 * 1000)); } catch (erro) { /* sem storage: so esconde agora */ }
            document.querySelectorAll("[data-instalar-dispensavel]").forEach(function (el) { el.hidden = true; });
            return;
        }
        if (!e.target.closest("[data-instalar-botao]")) return;
        var pedido = window.pedidoInstalarApp;
        if (pedido) {
            pedido.prompt();
            pedido.userChoice.then(function (escolha) {
                if (escolha.outcome === "accepted") esconder();
            }).catch(function () {});
            window.pedidoInstalarApp = null;  // o navegador so deixa usar 1 vez
        } else {
            passoAPasso();
        }
    });

    window.addEventListener("appinstalled", esconder);
    if (window.pedidoInstalarApp || ios || androidSemPedido) mostrar();
    document.addEventListener("pode-instalar-app", mostrar);
})();

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
    function ligarEnvio(caixa) {
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
    }
    document.querySelectorAll('[data-envio]').forEach(ligarEnvio);

    // Carregado so quando aparece na tela (ministerio/_envio.html,
    // campos_envio_tardio): dentro de um <details> fechado, so ao abrir.
    function carregar(lugar) {
        if (lugar.getAttribute('data-carregando')) return;
        lugar.setAttribute('data-carregando', '1');
        fetch(lugar.getAttribute('data-envio-carregar'), { credentials: 'same-origin' })
            .then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); })
            .then(function (html) {
                var molde = document.createElement('div');
                molde.innerHTML = html;
                var caixa = molde.querySelector('[data-envio]');
                if (!caixa) throw new Error('vazio');
                lugar.replaceWith(caixa);
                ligarEnvio(caixa);
            })
            .catch(function () {
                lugar.removeAttribute('data-carregando');
                lugar.textContent = 'Não deu para carregar os ministérios. Toque para tentar de novo.';
                lugar.addEventListener('click', function () { carregar(lugar); }, { once: true });
            });
    }
    var lugares = document.querySelectorAll('[data-envio-carregar]');
    lugares.forEach(function (lugar) {
        var form = lugar.closest('form');
        if (form) form.querySelectorAll('[type="submit"]').forEach(function (b) { b.disabled = true; });
    });
    if ('IntersectionObserver' in window) {
        var observador = new IntersectionObserver(function (entradas) {
            entradas.forEach(function (e) {
                if (e.isIntersecting) { observador.unobserve(e.target); carregar(e.target); }
            });
        }, { rootMargin: '200px' });
        lugares.forEach(function (lugar) { observador.observe(lugar); });
    } else {
        lugares.forEach(carregar);
    }
})();

/* Salvar status sem recarregar (escala.atualizar_status responde JSON com
   o cabecalho X-Requested-With: fetch). So o caminho mais comum -- confirmar
   / voltar pra "nao notificado" -- vai rapido; troca (tem motivo/sugestao)
   e "presente" (mexe no check-in e em outras partes da tela) continuam com
   o envio normal da pagina. Qualquer falha de rede tambem cai no envio
   normal, entao nunca se perde um toque. */
window.salvarStatus = function (select) {
    var form = select.form;
    var anterior = select.getAttribute('data-status-atual') || '';
    var novo = select.value;
    var rapido = window.fetch && (novo === 'confirmado' || novo === 'nao_notificado') && anterior !== 'presente';
    if (!rapido) { form.submit(); return; }

    var id = select.getAttribute('data-status-select');
    var aviso = form.querySelector('[data-status-aviso]');
    if (!aviso) {
        aviso = document.createElement('span');
        aviso.setAttribute('data-status-aviso', '');
        aviso.className = 'block text-[11px] font-semibold mt-1';
        select.insertAdjacentElement('afterend', aviso);
    }
    function avisar(texto, erro) {
        aviso.textContent = texto;
        aviso.classList.toggle('text-red-500', !!erro);
        aviso.classList.toggle('text-emerald-600', !erro);
    }

    var dados = new FormData(form);
    select.disabled = true;
    avisar('Salvando...');
    fetch(form.action, { method: 'POST', body: dados, credentials: 'same-origin',
                         headers: { 'X-Requested-With': 'fetch' } })
        .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
        .then(function (res) {
            if (!res.ok || !res.j.ok) { var e = new Error('recusado'); e.mensagem = res.j.mensagem; throw e; }
            select.setAttribute('data-status-atual', res.j.status);
            document.querySelectorAll('[data-status-rotulo="' + id + '"]').forEach(function (el) { el.textContent = res.j.rotulo; });
            document.querySelectorAll('[data-status-ponto="' + id + '"]').forEach(function (el) {
                el.className = el.className.replace(/\bbg-\S+/g, '').trim() + ' ' + res.j.cor;
            });
            avisar('\u2713 Salvo');
            setTimeout(function () { if (aviso.textContent === '\u2713 Salvo') aviso.textContent = ''; }, 2500);
        })
        .catch(function (e) {
            if (e && e.mensagem) { select.value = anterior; avisar(e.mensagem, true); return; }
            form.submit();  // sem rede/servidor: envio normal da pagina
        })
        .then(function () { select.disabled = false; });
};

/* Botao "Colar cifra" ([data-colar-area="<seletor do textarea>"]): le a
   area de transferencia (o que a pessoa copiou no site de cifras), poe no
   campo e ja envia -- o form do botao, ou clica em [data-depois-clicar].
   Sem permissao/suporte (navegador antigo, a pessoa negou): abre o campo
   pra colar a mao e explica. O texto vem da pessoa; o servidor nunca busca
   site nenhum. */
(function () {
    document.querySelectorAll('[data-colar-area]').forEach(function (botao) {
        var form = botao.closest('form');
        var caixa = botao.closest('form, details, section') || document;
        var aviso = (form || caixa).querySelector('[data-colar-aviso]') || caixa.querySelector('[data-colar-aviso]');

        function avisar(texto, erro) {
            if (!aviso) return;
            aviso.textContent = texto;
            aviso.classList.remove('hidden');
            aviso.classList.toggle('text-red-500', !!erro);
        }

        function colarAMao(campo, texto) {
            var detalhes = campo.closest('details');
            if (detalhes) detalhes.open = true;
            campo.focus();
            avisar(texto, true);
        }

        botao.addEventListener('click', function () {
            var campo = document.querySelector(botao.getAttribute('data-colar-area'));
            if (!campo) return;
            if (!navigator.clipboard || !navigator.clipboard.readText) {
                colarAMao(campo, 'Este navegador não deixa ler o que foi copiado: toque e segure na caixa e escolha Colar.');
                return;
            }
            navigator.clipboard.readText().then(function (texto) {
                if (!texto || !texto.trim()) {
                    avisar('Nada copiado ainda: copie a cifra no site (acordes e letra) e toque de novo.', true);
                    return;
                }
                campo.value = texto;
                avisar('Cifra colada, salvando...');
                var depois = botao.getAttribute('data-depois-clicar');
                if (depois) { var alvo = document.querySelector(depois); if (alvo) alvo.click(); return; }
                if (form) { if (form.requestSubmit) form.requestSubmit(); else form.submit(); }
            }).catch(function () {
                colarAMao(campo, 'Sem permissão para ler o que foi copiado: toque e segure na caixa e escolha Colar.');
            });
        });
    });
})();
