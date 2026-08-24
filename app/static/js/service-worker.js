// Service worker minimo, so pra habilitar a instalacao como PWA (icone
// proprio, janela sem barra de navegador). NAO cacheia paginas HTML nem
// nada autenticado/dinamico de proposito -- um site multiusuario (varias
// contas podem logar no mesmo aparelho/navegador) nao pode arriscar servir
// uma pagina em cache de outra conta. So assets estaticos (CSS/JS/imagens)
// entram em cache, com estrategia "stale-while-revalidate" (mostra o que
// tem em cache na hora, atualiza em segundo plano pro proximo acesso).
const CACHE_NAME = "piba-swerdne-estaticos-v1";

self.addEventListener("install", function (evento) {
    self.skipWaiting();
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

    // So GET de /static/* -- nunca POST, nunca paginas/rotas dinamicas.
    if (evento.request.method !== "GET" || url.pathname.indexOf("/static/") !== 0) {
        return;
    }

    evento.respondWith(
        caches.open(CACHE_NAME).then(function (cache) {
            return cache.match(evento.request).then(function (emCache) {
                var buscaRede = fetch(evento.request).then(function (resposta) {
                    cache.put(evento.request, resposta.clone());
                    return resposta;
                }).catch(function () { return emCache; });
                return emCache || buscaRede;
            });
        })
    );
});
