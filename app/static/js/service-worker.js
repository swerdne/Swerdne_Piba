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
const CACHE_NAME = "piba-swerdne-estaticos-v2";

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
        fetch(evento.request).then(function (resposta) {
            var copia = resposta.clone();
            caches.open(CACHE_NAME).then(function (cache) { cache.put(evento.request, copia); });
            return resposta;
        }).catch(function () {
            // Sem rede (offline de verdade) -- ai sim usa o que tiver em cache.
            return caches.match(evento.request);
        })
    );
});
