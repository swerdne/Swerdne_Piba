// JavaScript do projeto
console.log("App carregado.");

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
            botao.disabled = true;
        }
    });
});

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

// Tutorial guiado (spotlight): generico, funciona em qualquer pagina que
// tenha um <script type="application/json" id="tutorial-dados"> com
// {urlConcluir, csrf, passos: [{seletor, titulo, texto}], autoIniciar} --
// seletor null/ausente = passo centralizado (sem destacar elemento nenhum),
// usado pro primeiro e ultimo passo. autoIniciar controla se comeca sozinho
// ao carregar a pagina (1a visita) -- roda de novo a qualquer momento via
// botao com [data-tutorial-reiniciar] (ver comunidade/detalhe.html).
(function () {
    var dadosEl = document.getElementById("tutorial-dados");
    if (!dadosEl) return; // pagina sem tutorial nenhum

    var dados;
    try {
        dados = JSON.parse(dadosEl.textContent);
    } catch (e) {
        return; // JSON malformado nao deveria travar a pagina inteira
    }
    var passos = dados.passos || [];
    if (!passos.length) return;

    function iniciar() {
        var passoAtual = 0;

        var overlay = document.createElement("div");
        overlay.style.cssText = "position:fixed;inset:0;z-index:9990;background:transparent;";

        var destaque = document.createElement("div");
        destaque.style.cssText =
            "position:fixed;z-index:9991;border-radius:14px;pointer-events:none;" +
            "box-shadow:0 0 0 9999px rgba(15,23,42,.78);" +
            "transition:top .3s ease,left .3s ease,width .3s ease,height .3s ease,opacity .2s ease;" +
            "opacity:0;";

        var card = document.createElement("div");
        card.style.cssText =
            "position:fixed;z-index:9992;max-width:320px;background:#111827;color:#fff;" +
            "border-radius:16px;padding:18px 20px;box-shadow:0 20px 40px rgba(0,0,0,.4);" +
            "font:14px/1.5 ui-sans-serif,system-ui,sans-serif;" +
            "transition:top .3s ease,left .3s ease,opacity .2s ease;";
        card.setAttribute("role", "dialog");
        card.setAttribute("aria-live", "polite");

        document.body.appendChild(overlay);
        document.body.appendChild(destaque);
        document.body.appendChild(card);

        function concluir() {
            overlay.remove();
            destaque.remove();
            card.remove();
            document.removeEventListener("keydown", aoTeclar);
            window.removeEventListener("resize", posicionar);

            if (!dados.urlConcluir) return;
            fetch(dados.urlConcluir, {
                method: "POST",
                credentials: "same-origin",
                headers: { "Content-Type": "application/x-www-form-urlencoded" },
                body: "csrf_token=" + encodeURIComponent(dados.csrf || ""),
            }).catch(function () { /* melhor esforco -- nao bloqueia a UI se falhar */ });
        }

        function renderizarCard(passo, indice) {
            var ultimo = indice === passos.length - 1;
            card.innerHTML =
                '<p style="font-size:11px;font-weight:600;letter-spacing:.04em;text-transform:uppercase;color:#a5b4fc;margin:0 0 8px;">' +
                (indice + 1) + " de " + passos.length + '</p>' +
                '<h3 style="font-size:16px;font-weight:700;margin:0 0 6px;">' + passo.titulo + '</h3>' +
                '<p style="margin:0 0 16px;color:#d1d5db;">' + passo.texto + '</p>' +
                '<div style="display:flex;align-items:center;justify-content:space-between;gap:12px;">' +
                '<button type="button" data-tutorial-pular style="background:none;border:0;color:#9ca3af;font-size:13px;cursor:pointer;padding:4px 0;">Pular tutorial</button>' +
                '<button type="button" data-tutorial-proximo style="background:#4f46e5;color:#fff;border:0;border-radius:8px;padding:8px 16px;font-size:13px;font-weight:600;cursor:pointer;">' +
                (ultimo ? "Concluir" : "Proximo") + '</button>' +
                '</div>';

            card.querySelector("[data-tutorial-pular]").addEventListener("click", concluir);
            card.querySelector("[data-tutorial-proximo]").addEventListener("click", function () {
                if (ultimo) { concluir(); return; }
                passoAtual += 1;
                irParaPasso(passoAtual);
            });
        }

        function posicionar() {
            irParaPasso(passoAtual, true);
        }

        function irParaPasso(indice, semScroll) {
            var passo = passos[indice];
            var alvo = passo.seletor ? document.querySelector(passo.seletor) : null;

            function aplicar() {
                if (alvo) {
                    var r = alvo.getBoundingClientRect();
                    var folga = 8;
                    destaque.style.top = (r.top - folga) + "px";
                    destaque.style.left = (r.left - folga) + "px";
                    destaque.style.width = (r.width + folga * 2) + "px";
                    destaque.style.height = (r.height + folga * 2) + "px";
                    destaque.style.opacity = "1";
                } else {
                    // Passo sem elemento (boas-vindas/conclusao): sem cutout visivel.
                    destaque.style.opacity = "0";
                }

                var alturaEstimadaCard = 170;
                var margem = 16;
                if (alvo) {
                    var rr = alvo.getBoundingClientRect();
                    var caberEmbaixo = rr.bottom + alturaEstimadaCard + margem < window.innerHeight;
                    card.style.top = (caberEmbaixo ? rr.bottom + margem : Math.max(margem, rr.top - alturaEstimadaCard - margem)) + "px";
                    var esquerda = Math.min(Math.max(rr.left, margem), window.innerWidth - 320 - margem);
                    card.style.left = Math.max(margem, esquerda) + "px";
                    card.style.transform = "none";
                } else {
                    card.style.top = "50%";
                    card.style.left = "50%";
                    card.style.transform = "translate(-50%,-50%)";
                }

                renderizarCard(passo, indice);
            }

            if (alvo && !semScroll) {
                alvo.scrollIntoView({ behavior: "smooth", block: "center" });
                setTimeout(aplicar, 320);
            } else {
                aplicar();
            }
        }

        function aoTeclar(evento) {
            if (evento.key === "Escape") concluir();
        }

        document.addEventListener("keydown", aoTeclar);
        window.addEventListener("resize", posicionar);
        irParaPasso(0);
    }

    if (dados.autoIniciar) iniciar();

    document.querySelectorAll("[data-tutorial-reiniciar]").forEach(function (botao) {
        botao.addEventListener("click", iniciar);
    });
})();
