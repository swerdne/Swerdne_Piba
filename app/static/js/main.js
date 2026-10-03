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
            // setTimeout(0) de proposito -- desabilitar o botao de forma
            // SINCRONA dentro do proprio handler de submit e uma pegadinha
            // conhecida: alguns navegadores tratam isso como se o campo
            // nunca tivesse existido a tempo de montar o envio, e o form
            // simplesmente nao e enviado (nem da erro, so nao acontece
            // nada). Adiar pro proximo tick deixa o navegador terminar de
            // processar o envio em curso antes de desabilitar o botao.
            setTimeout(function () { botao.disabled = true; }, 0);
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
