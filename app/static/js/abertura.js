// Animacao de abertura do app (logo se formando por particulas + laser).
// So roda na 1a pagina da sessao -- quem decide e o script inline do
// base.html, que mostra o #abertura e carrega este arquivo. Nunca segura a
// tela: assim que a pagina por baixo esta pronta (evento load), a
// animacao acelera ate o logo pronto (no maximo ~0,5 s), o logo sobe, o
// nome "TyBenson" entra letra a letra (~1 s) e tudo some. Se a pagina ficou
// pronta antes de a animacao comecar, pula direto pro logo formado + nome.
// Sem pressa (pagina ainda carregando), o nome entra 0,6 s depois do laser.
(function () {
    var cena = document.getElementById("abertura");
    if (!cena) return;
    var cv = document.getElementById("abertura-canvas");
    var halo = document.getElementById("abertura-halo");

    var W = 720, H = 600, STEP = 3, PS = STEP - 0.6;
    // Particulas so em aparelho que aguenta. O Safari nao conta qual iPhone
    // e, entao a animacao se mede: nos primeiros quadros (descarta os 3
    // primeiros, de aquecimento), se desenhar custar mais que LIMITE_DESENHO_MS
    // em media ou os quadros vierem espacados demais (abaixo de 10 fps), pula direto
    // pro logo pronto + nome. Modo Pouca Energia (iOS a 30 fps, ~33 ms entre
    // quadros) continua com particulas. Aparelho claramente fraco (2 GB de
    // memoria ou 2 nucleos) nem tenta: logo parado + nome.
    var QUADROS_MEDIDOS = 10, LIMITE_DESENHO_MS = 9, LIMITE_INTERVALO_MS = 100;
    var aparelhoFraco = (navigator.deviceMemory && navigator.deviceMemory <= 2) ||
                        (navigator.hardwareConcurrency && navigator.hardwareConcurrency <= 2);
    var LOGO = { x: 150, y: 128, w: 420, h: 420 * 689 / 840 };
    var MB = LOGO.y + LOGO.h + 20;
    var T = { laser0: 2.1, laser1: 3.4 };
    var NOME_APOS_LASER = 0.6;  // sem pressa: espera isso depois do laser pra mostrar o nome
    var SEGURA_NOME_MS = 1000;  // tempo do nome entrar letra a letra antes de sumir
    var ACELERA_EM = 0.45;  // pronta a pagina, chega no logo pronto nesse tempo
    var LIMITE_MS = 8000;   // trava de seguranca: some de qualquer jeito
    var reduzir = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;

    // Som da abertura (Web Audio, gerado aqui -- sem arquivo): um "sopro"
    // baixinho enquanto as particulas se juntam e um "brilho" curto (arpejo
    // de Mi maior, 4 notas) quando o logo forma e o nome entra. Navegador
    // bloqueia som sem toque na tela: toca onde e permitido (Chrome com o app
    // instalado na tela inicial) e, onde nao e (iPhone, aba comum), fica em
    // silencio -- nunca toca atrasado depois (tentar() so vale nos primeiros
    // 400 ms de cada chamada).
    var som = (function () {
        var audio = null, ar = null;
        try {
            var Classe = window.AudioContext || window.webkitAudioContext;
            if (Classe) {
                audio = new Classe();
                if (audio.state === "suspended" && audio.resume) audio.resume().catch(function () {});
            }
        } catch (e) { audio = null; }

        function tentar(tocar) {
            if (!audio) return;
            if (audio.state === "running") { tocar(); return; }
            var prazo = performance.now() + 400;
            if (audio.resume) audio.resume().then(function () {
                if (audio.state === "running" && performance.now() < prazo) tocar();
            }).catch(function () {});
        }

        function sopro(duracao) {
            tentar(function () {
                try {
                    var t = audio.currentTime + 0.02, n = Math.floor(audio.sampleRate * duracao);
                    var ruido = audio.createBuffer(1, n, audio.sampleRate), dados = ruido.getChannelData(0);
                    for (var i = 0; i < n; i++) dados[i] = Math.random() * 2 - 1;
                    var fonte = audio.createBufferSource(), filtro = audio.createBiquadFilter(), volume = audio.createGain();
                    fonte.buffer = ruido;
                    filtro.type = "bandpass";
                    filtro.Q.value = 0.9;
                    filtro.frequency.setValueAtTime(250, t);
                    filtro.frequency.exponentialRampToValueAtTime(1800, t + duracao * 0.85);
                    volume.gain.setValueAtTime(0.0001, t);
                    volume.gain.exponentialRampToValueAtTime(0.045, t + duracao * 0.6);
                    volume.gain.exponentialRampToValueAtTime(0.0001, t + duracao);
                    fonte.connect(filtro);
                    filtro.connect(volume);
                    volume.connect(audio.destination);
                    fonte.start(t);
                    fonte.stop(t + duracao);
                    ar = volume;
                } catch (e) { /* sem som, segue a animacao */ }
            });
        }

        function brilho() {
            tentar(function () {
                try {
                    var t = audio.currentTime + 0.02;
                    if (ar) {  // o sopro sai de cena quando o logo forma
                        ar.gain.cancelScheduledValues(t);
                        ar.gain.setValueAtTime(Math.max(ar.gain.value, 0.0001), t);
                        ar.gain.exponentialRampToValueAtTime(0.0001, t + 0.15);
                    }
                    [[659.25, 0, 0.07], [830.61, 0.09, 0.065], [987.77, 0.18, 0.06], [1318.51, 0.3, 0.04]]
                        .forEach(function (nota) {
                            var inicio = t + nota[1];
                            ["sine", "triangle"].forEach(function (forma, k) {
                                var osc = audio.createOscillator(), vol = audio.createGain();
                                osc.type = forma;
                                osc.frequency.value = nota[0];
                                var pico = k ? nota[2] * 0.25 : nota[2];  // triangle = um brilho leve por cima
                                vol.gain.setValueAtTime(0.0001, inicio);
                                vol.gain.exponentialRampToValueAtTime(pico, inicio + 0.012);
                                vol.gain.exponentialRampToValueAtTime(0.0001, inicio + 1.1);
                                osc.connect(vol);
                                vol.connect(audio.destination);
                                osc.start(inicio);
                                osc.stop(inicio + 1.15);
                            });
                        });
                } catch (e) { /* sem som */ }
            });
        }

        function liberar() {  // devolve o audio do aparelho quando a abertura acaba
            if (audio && audio.close) setTimeout(function () { try { audio.close(); } catch (e) { /* ja fechado */ } }, 2500);
        }
        return { sopro: sopro, brilho: brilho, liberar: liberar };
    })();

    var encerrada = false;
    function encerrar() {
        if (encerrada) return;
        encerrada = true;
        rodando = false;
        cena.classList.add("abertura-saindo");
        som.liberar();
        setTimeout(function () {
            cena.remove();
            document.documentElement.classList.remove("com-abertura");
            // O iOS tem um teto de memoria pra canvas: devolve tudo na hora.
            [cv, liso, buf].forEach(function (c) { if (c) { c.width = 0; c.height = 0; } });
        }, reduzir ? 200 : 400);
    }
    var trava = setTimeout(encerrar, LIMITE_MS);

    // "Pronta" = evento load (icones, fontes e imagens da tela ja chegaram) --
    // DOMContentLoaded saia cedo demais numa pagina renderizada no servidor.
    var paginaPronta = document.readyState === "complete";
    if (!paginaPronta) {
        window.addEventListener("load", function () { paginaPronta = true; });
    }

    var ctx = cv.getContext && cv.getContext("2d");
    if (!ctx || reduzir || aparelhoFraco) {
        // Sem canvas, "reduzir movimento" ou aparelho fraco: logo e nome parados, some quando a pagina fica pronta.
        cena.classList.add("abertura-estatica", "abertura-nomeada");
        som.brilho();
        var esperar = function () { paginaPronta ? setTimeout(encerrar, 600) : setTimeout(esperar, 50); };
        esperar();
        return;
    }

    var liso = document.createElement("canvas"), lctx = liso.getContext("2d");
    var buf = document.createElement("canvas"), bctx = buf.getContext("2d");
    var logo = new Image();
    var escala = 1, ox = 0, oy = 0, quadroTela = null, N = 0, tx, ty, sx, sy, atraso, dur, curva, tam, tinta, balde, P;
    var baldes = [], corBalde = [], faiscas = [];
    var t = 0, ultimo = 0, rodando = false, nomeadaEm = 0;
    var VIAJANDO = ["rgb(92,225,255)", "rgb(59,130,255)"];

    function limitar(v, a, b) { return Math.min(b, Math.max(a, v)); }
    function suavizar(p) { return 1 - Math.pow(1 - p, 3); }

    function desenharLogo(c) {
        c.imageSmoothingEnabled = true;
        c.imageSmoothingQuality = "high";
        c.drawImage(logo, LOGO.x, LOGO.y, LOGO.w, LOGO.h);
    }

    // O canvas cobre a TELA INTEIRA (as particulas nascem espalhadas por ela
    // toda), mas as contas continuam no quadro logico W x H do logo: o
    // quadro (.abertura-quadro) vira a regiao onde o logo e montado.
    function logico(c) { c.setTransform(escala, 0, 0, escala, ox, oy); }
    function pixel(c) { c.setTransform(1, 0, 0, 1, 0, 0); }

    function ajustar() {
        var vw = window.innerWidth, vh = window.innerHeight;
        var r = cv.parentElement.getBoundingClientRect();
        var dpr = Math.min(2, window.devicePixelRatio || 1);
        cv.style.left = -r.left + "px";
        cv.style.top = -r.top + "px";
        cv.style.width = vw + "px";
        cv.style.height = vh + "px";
        // Logo sobe/encolhe em volta do centro do quadro (nao da tela).
        cv.style.transformOrigin = (r.left + r.width / 2) + "px " + (r.top + r.height / 2) + "px";
        cena.style.setProperty("--abertura-sobe", (-0.1 * r.height) + "px");
        [cv, liso, buf].forEach(function (c) { c.width = Math.round(vw * dpr); c.height = Math.round(vh * dpr); });
        escala = r.width / W * dpr;
        ox = r.left * dpr;
        oy = r.top * dpr;
        quadroTela = { x0: -r.left / (r.width / W), x1: (vw - r.left) / (r.width / W),
                       y0: -r.top / (r.width / W), y1: (vh - r.top) / (r.width / W) };
        pixel(lctx);
        lctx.clearRect(0, 0, liso.width, liso.height);
        logico(lctx);
        desenharLogo(lctx);
    }

    function montarParticulas() {
        var amostra = document.createElement("canvas");
        amostra.width = W; amostra.height = H;
        var ac = amostra.getContext("2d", { willReadFrequently: true });
        desenharLogo(ac);
        var dados = ac.getImageData(0, 0, W, H).data, pts = [];
        amostra.width = amostra.height = 0;  // so servia pra ler os pixels
        for (var y = 0; y < H - STEP; y += STEP) {
            for (var x = 0; x < W - STEP; x += STEP) {
                var i = ((y + (STEP >> 1)) * W + x + (STEP >> 1)) * 4;
                if (dados[i + 3] >= 150) pts.push([x + STEP / 2, y + STEP / 2, dados[i], dados[i + 1], dados[i + 2]]);
            }
        }
        N = pts.length;
        tx = new Float32Array(N); ty = new Float32Array(N); sx = new Float32Array(N); sy = new Float32Array(N);
        atraso = new Float32Array(N); dur = new Float32Array(N); curva = new Float32Array(N);
        tam = new Float32Array(N); tinta = new Uint8Array(N); balde = new Uint16Array(N); P = new Float32Array(N);
        var mapa = {};
        pts.forEach(function (p, i) {
            tx[i] = p[0]; ty[i] = p[1];
            // Nasce em qualquer ponto da tela e viaja ate o seu lugar no logo.
            sx[i] = quadroTela.x0 + Math.random() * (quadroTela.x1 - quadroTela.x0);
            sy[i] = quadroTela.y0 + Math.random() * (quadroTela.y1 - quadroTela.y0);
            atraso[i] = 0.15 + Math.random() * 0.7;
            dur[i] = 0.8 + Math.random() * 0.4;
            curva[i] = (Math.random() - 0.5) * 80;
            tam[i] = 2 + Math.random() * 1.6;
            tinta[i] = Math.random() < 0.55 ? 0 : 1;
            var chave = ((p[2] >> 4) << 8) | ((p[3] >> 4) << 4) | (p[4] >> 4);
            if (!(chave in mapa)) {
                mapa[chave] = baldes.length;
                baldes.push([]);
                corBalde.push("rgb(" + ((p[2] >> 4) * 16 + 8) + "," + ((p[3] >> 4) * 16 + 8) + "," + ((p[4] >> 4) * 16 + 8) + ")");
            }
            balde[i] = mapa[chave];
            baldes[balde[i]].push(i);
        });
    }

    // Brilho do laser so sobre os tracos do logo (mascara = logo lisa).
    function forja(lx) {
        pixel(bctx);
        bctx.globalCompositeOperation = "source-over";
        bctx.clearRect(0, 0, buf.width, buf.height);
        logico(bctx);
        var g = bctx.createLinearGradient(lx - 140, 0, lx + 16, 0);
        g.addColorStop(0, "rgba(255,255,255,0)");
        g.addColorStop(0.72, "rgba(255,255,255,.55)");
        g.addColorStop(0.93, "rgba(255,255,255,1)");
        g.addColorStop(1, "rgba(255,255,255,0)");
        bctx.fillStyle = g;
        bctx.fillRect(lx - 140, LOGO.y - 10, 156, LOGO.h + 20);
        bctx.globalCompositeOperation = "destination-in";
        pixel(bctx);
        bctx.drawImage(liso, 0, 0);
        bctx.globalCompositeOperation = "source-over";
        ctx.globalCompositeOperation = "lighter";
        pixel(ctx);
        ctx.drawImage(buf, 0, 0);
        logico(ctx);
        ctx.globalCompositeOperation = "source-over";
    }

    function desenhar(tempo, dt) {
        pixel(ctx);
        ctx.globalAlpha = 1;
        ctx.clearRect(0, 0, cv.width, cv.height);
        logico(ctx);

        var laserLigado = tempo >= T.laser0 && tempo < T.laser1;
        var pronto = tempo >= T.laser1;
        var lp = limitar((tempo - T.laser0) / (T.laser1 - T.laser0), 0, 1);
        var laserX = pronto ? 1e5 : tempo < T.laser0 ? -1e5 :
            (LOGO.x - 16) + (LOGO.w + 50) * (0.5 - 0.5 * Math.cos(Math.PI * lp));

        if (laserLigado || pronto) {
            ctx.save();
            ctx.beginPath(); ctx.rect(0, 0, pronto ? W : laserX, MB); ctx.clip();
            pixel(ctx);
            ctx.drawImage(liso, 0, 0);
            ctx.restore();
        }

        if (!pronto) {
            var entrada = limitar(tempo / 0.5, 0, 1), i, k, p;
            for (i = 0; i < N; i++) P[i] = limitar((tempo - atraso[i]) / dur[i], 0, 1);
            // Desenho em lote: 1 caminho por cor x estado (parada/viajando) e
            // um unico fill -- antes era 1 fillRect + 1 troca de opacidade por
            // particula (~7 mil por quadro), o que mais pesava no iPhone.
            for (k = 0; k < 2; k++) {
                ctx.fillStyle = VIAJANDO[k];
                for (var viajando = 0; viajando < 2; viajando++) {
                ctx.beginPath();
                for (i = 0; i < N; i++) {
                    p = P[i];
                    if (p >= 1 || tinta[i] !== k || (p > 0) !== (viajando === 1)) continue;
                    var x, y, s;
                    if (p <= 0) {
                        x = sx[i] + Math.sin(tempo * 1.3 + i) * 5;
                        y = sy[i] + Math.cos(tempo * 1.1 + i * 0.7) * 5;
                        s = tam[i];
                    } else {
                        var e = suavizar(p), dx = tx[i] - sx[i], dy = ty[i] - sy[i], d = Math.hypot(dx, dy) || 1;
                        var desvio = Math.sin(Math.PI * e) * curva[i];
                        x = sx[i] + dx * e + (-dy / d) * desvio;
                        y = sy[i] + dy * e + (dx / d) * desvio;
                        s = tam[i] + (PS - tam[i]) * e;
                    }
                    ctx.rect(x - s / 2, y - s / 2, s, s);
                }
                ctx.globalAlpha = entrada * (viajando ? 0.95 : 0.75);
                ctx.fill();
                }
            }
            ctx.globalAlpha = 1;
            var clarao = [];
            for (var b = 0; b < baldes.length; b++) {
                ctx.fillStyle = corBalde[b];
                ctx.beginPath();
                var lista = baldes[b];
                for (var j = 0; j < lista.length; j++) {
                    i = lista[j];
                    if (P[i] < 1 || tx[i] < laserX) continue;
                    if (tx[i] < laserX + 26) { clarao.push(i); continue; }
                    ctx.rect(tx[i] - PS / 2, ty[i] - PS / 2, PS, PS);
                }
                ctx.fill();
            }
            if (clarao.length) {
                ctx.fillStyle = "#FFFFFF";
                clarao.forEach(function (i) {
                    ctx.globalAlpha = 1 - (tx[i] - laserX) / 26 * 0.4;
                    ctx.fillRect(tx[i] - PS / 2 - 0.3, ty[i] - PS / 2 - 0.3, PS + 0.6, PS + 0.6);
                });
                ctx.globalAlpha = 1;
            }
        }

        if (laserLigado) forja(laserX);

        if (laserLigado && dt) {
            var n = 260 * dt, qtd = Math.floor(n) + (Math.random() < n % 1 ? 1 : 0);
            for (var q = 0; q < qtd; q++) {
                var y0 = -1;
                for (var tentativa = 0; tentativa < 40; tentativa++) {
                    var r = (Math.random() * N) | 0;
                    if (Math.abs(tx[r] - laserX) < 10) { y0 = ty[r]; break; }
                }
                if (y0 < 0) continue;
                faiscas.push({ x: laserX, y: y0, vx: 40 + Math.random() * 130, vy: (Math.random() - 0.5) * 90,
                               vida: 0, max: 0.3 + Math.random() * 0.35, s: 1.4 + Math.random() * 1.6 });
            }
        }
        if (dt) {
            faiscas = faiscas.filter(function (f) { f.vida += dt; f.x += f.vx * dt; f.y += f.vy * dt; return f.vida < f.max; });
        }
        if (faiscas.length) {
            ctx.fillStyle = "#FFFFFF";
            faiscas.forEach(function (f) {
                ctx.globalAlpha = 1 - f.vida / f.max;
                ctx.fillRect(f.x - f.s / 2, f.y - f.s / 2, f.s, f.s);
            });
            ctx.globalAlpha = 1;
        }

        halo.style.opacity = tempo < T.laser0 ? 0 : limitar((tempo - T.laser0) / 1.2, 0, 1);
    }

    var velocidadeRapida = 0, medidos = -3, somaDesenho = 0, somaIntervalo = 0;
    function quadro(agora) {
        if (!rodando) return;
        var intervalo = agora - ultimo;
        var dt = Math.min(0.05, intervalo / 1000);
        ultimo = agora;
        if (paginaPronta && t < T.laser1) {
            // Pagina pronta: chega no logo pronto em ate ACELERA_EM segundos.
            if (!velocidadeRapida) velocidadeRapida = Math.max(2.2, (T.laser1 - t) / ACELERA_EM);
            t = Math.min(T.laser1, t + dt * velocidadeRapida);
        } else {
            t += dt;
        }
        var inicioDesenho = performance.now();
        desenhar(t, dt);
        if (medidos < QUADROS_MEDIDOS && t < T.laser1) {
            if (medidos >= 0) {
                somaDesenho += performance.now() - inicioDesenho;
                somaIntervalo += intervalo;
            }
            medidos++;
            if (medidos === QUADROS_MEDIDOS &&
                (somaDesenho / QUADROS_MEDIDOS > LIMITE_DESENHO_MS || somaIntervalo / QUADROS_MEDIDOS > LIMITE_INTERVALO_MS)) {
                t = T.laser1;  // aparelho nao aguenta: logo pronto, sem particulas
                cena.setAttribute("data-abertura-leve", "");
            }
        }
        if (!nomeadaEm && t >= T.laser1 && (paginaPronta || t >= T.laser1 + NOME_APOS_LASER)) {
            cena.classList.add("abertura-nomeada");
            nomeadaEm = agora;
            som.brilho();
        }
        if (nomeadaEm) {
            if (paginaPronta && agora - nomeadaEm >= SEGURA_NOME_MS) {
                clearTimeout(trava);
                return encerrar();
            }
        }
        requestAnimationFrame(quadro);
    }

    logo.onload = function () {
        if (encerrada) return;
        ajustar();
        if (paginaPronta) t = T.laser1;  // pagina ja pronta: pula direto pro logo formado
        else som.sopro(1.8);  // particulas vao se juntar: sopro ate o logo formar
        montarParticulas();
        window.addEventListener("resize", ajustar);
        rodando = true;
        ultimo = performance.now();
        requestAnimationFrame(quadro);
    };
    logo.onerror = encerrar;
    logo.src = cena.getAttribute("data-logo");
})();
