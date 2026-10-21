// Service worker minimo, so pra habilitar a instalacao como PWA (icone
// proprio, janela sem barra de navegador). NAO cacheia paginas HTML nem
// nada autenticado/dinamico de proposito -- um site multiusuario (varias
// contas podem logar no mesmo aparelho/navegador) nao pode arriscar servir
// uma pagina em cache de outra conta. So assets estaticos (CSS/JS/imagens)
// entram em cache, com estrategia "rede primeiro" (busca a versao mais nova
// sempre que ha internet; cache so entra como fallback se a rede falhar).
// Era "stale-while-revalidate" (mostra o cache na hora, atualiza depois) --
// trocado porque, num app mudando rapido, isso fazia correcoes recentes
// (JS/CSS) so aparecerem depois de 2+ recarregamentos, dando a impressao de
// "continua quebrado" mesmo com o deploy certo no ar.
// Excecao: arquivo com ?v=<hash> no endereco (app/desempenho.py) nunca muda
// -- deploy novo gera endereco novo --, entao vem direto do cache, sem rede:
// e o que deixa a troca de pagina rapida no celular.
const CACHE_NAME = "piba-swerdne-estaticos-v4";

// Tela "sem internet" (static/offline.html): guardada na instalacao e
// mostrada quando uma PAGINA (navegacao) falha por falta de rede -- no app
// instalado, no lugar do erro do navegador. As paginas em si continuam indo
// sempre pra rede (nunca cache de HTML com dado de conta).
const PAGINA_OFFLINE = "/static/offline.html";
const ARQUIVOS_OFFLINE = [PAGINA_OFFLINE, "/static/img/logo-mini.webp"];

self.addEventListener("install", function (evento) {
    self.skipWaiting();
    evento.waitUntil(
        caches.open(CACHE_NAME).then(function (cache) { return cache.addAll(ARQUIVOS_OFFLINE); }).catch(function () {})
    );
});

self.addEventListener("activate", function (evento) {
    evento.waitUntil(
        caches.keys().then(function (chaves) {
            return Promise.all(
                chaves.filter(function (chave) { return chave !== CACHE_NAME; })
                      .map(function (chave) { return caches.delete(chave); })
            );
        }).then(function () { return self.clients.claim(); })
    );
});

self.addEventListener("fetch", function (evento) {
    var url = new URL(evento.request.url);

    // Pagina (navegacao GET): sempre da rede; sem rede, a tela "sem internet".
    if (evento.request.mode === "navigate" && evento.request.method === "GET") {
        evento.respondWith(
            fetch(evento.request).catch(function () {
                return caches.match(PAGINA_OFFLINE).then(function (pagina) {
                    return pagina || Response.error();
                });
            })
        );
        return;
    }

    // So GET de /static/* -- nunca POST, nunca paginas/rotas dinamicas.
    if (evento.request.method !== "GET" || url.pathname.indexOf("/static/") !== 0) {
        return;
    }

    if (url.searchParams.has("v")) {
        evento.respondWith(
            caches.open(CACHE_NAME).then(function (cache) {
                return cache.match(evento.request).then(function (guardado) {
                    return guardado || fetch(evento.request).then(function (resposta) {
                        if (resposta.ok) {
                            // Versao nova: apaga as antigas do mesmo arquivo (cache nao cresce a cada deploy).
                            cache.keys().then(function (chaves) {
                                chaves.forEach(function (chave) {
                                    var antiga = new URL(chave.url);
                                    if (antiga.pathname === url.pathname && antiga.search !== url.search) cache.delete(chave);
                                });
                            });
                            cache.put(evento.request, resposta.clone());
                        }
                        return resposta;
                    });
                });
            })
        );
        return;
    }

    evento.respondWith(
        fetch(evento.request).then(function (resposta) {
            var copia = resposta.clone();
            caches.open(CACHE_NAME).then(function (cache) { cache.put(evento.request, copia); });
            return resposta;
        }).catch(function () {
            // Sem rede (offline de verdade) -- ai sim usa o que tiver em cache.
            return caches.match(evento.request, { ignoreSearch: ARQUIVOS_OFFLINE.indexOf(url.pathname) !== -1 });
        })
    );
});
