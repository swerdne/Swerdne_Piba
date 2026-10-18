// Animacao de abertura do app (logo se formando por particulas + laser).
// So roda na 1a pagina da sessao -- quem decide e o script inline do
// base.html, que mostra o #abertura e carrega este arquivo. Nunca segura a
// tela: assim que a pagina por baixo esta pronta (evento load), a
// animacao acelera ate o logo pronto (no maximo ~0,5 s) e some. Se a
// pagina ficou pronta antes de a animacao comecar, pula direto pro logo
// formado (0,3 s) e some.
(function () {
    var cena = document.getElementById("abertura");
    if (!cena) return;
    var cv = document.getElementById("abertura-canvas");
    var halo = document.getElementById("abertura-halo");

    var W = 720, H = 600, STEP = 3, PS = STEP - 0.6;
    var LOGO = { x: 150, y: 128, w: 420, h: 420 * 689 / 840 };
    var MB = LOGO.y + LOGO.h + 20;
    var T = { laser0: 2.0, laser1: 3.3 };
    var SEGURA_LOGO = 0.3;  // segundos mostrando o logo pronto antes de sumir
    var ACELERA_EM = 0.45;  // pronta a pagina, chega no logo pronto nesse tempo
    var LIMITE_MS = 8000;   // trava de seguranca: some de qualquer jeito
    var reduzir = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;

    var encerrada = false;
    function encerrar() {
        if (encerrada) return;
        encerrada = true;
        rodando = false;
        cena.classList.add("abertura-saindo");
        setTimeout(function () {
            cena.remove();
            document.documentElement.classList.remove("com-abertura");
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
    if (!ctx || reduzir) {
        // Sem canvas ou com "reduzir movimento": so o logo parado, some quando a pagina fica pronta.
        cena.classList.add("abertura-estatica");
        var esperar = function () { paginaPronta ? setTimeout(encerrar, 250) : setTimeout(esperar, 50); };
        esperar();
        return;
    }

    var liso = document.createElement("canvas"), lctx = liso.getContext("2d");
    var buf = document.createElement("canvas"), bctx = buf.getContext("2d");
    var logo = new Image();
    var escala = 1, N = 0, tx, ty, sx, sy, atraso, dur, curva, tam, tinta, balde, P;
    var baldes = [], corBalde = [], faiscas = [];
    var t = 0, ultimo = 0, rodando = false, chegouNoLogoEm = 0;
    var VIAJANDO = ["rgb(92,225,255)", "rgb(59,130,255)"];

    function limitar(v, a, b) { return Math.min(b, Math.max(a, v)); }
    function suavizar(p) { return 1 - Math.pow(1 - p, 3); }

    function desenharLogo(c) {
        c.imageSmoothingEnabled = true;
        c.imageSmoothingQuality = "high";
        c.drawImage(logo, LOGO.x, LOGO.y, LOGO.w, LOGO.h);
    }

    function ajustar() {
        var larg = cv.clientWidth || 360;
        var dpr = Math.min(2, window.devicePixelRatio || 1);
        var pw = Math.round(larg * dpr), ph = Math.round(larg * dpr * H / W);
        [cv, liso, buf].forEach(function (c) { c.width = pw; c.height = ph; });
        escala = pw / W;
        lctx.setTransform(escala, 0, 0, escala, 0, 0);
        desenharLogo(lctx);
    }

    function montarParticulas() {
        var amostra = document.createElement("canvas");
        amostra.width = W; amostra.height = H;
        var ac = amostra.getContext("2d", { willReadFrequently: true });
        desenharLogo(ac);
        var dados = ac.getImageData(0, 0, W, H).data, pts = [];
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
        var g = function () { return (Math.random() + Math.random() + Math.random() - 1.5) / 1.5; };
        pts.forEach(function (p, i) {
            tx[i] = p[0]; ty[i] = p[1];
            var longe = Math.random() < 0.12;
            var a = Math.random() * Math.PI * 2, r = longe ? 220 + Math.random() * 170 : 40 + Math.abs(g()) * 190;
            sx[i] = W / 2 + Math.cos(a) * r * 1.15;
            sy[i] = 260 + Math.sin(a) * r * 0.9;
            atraso[i] = 0.2 + Math.random() * 0.75;
            dur[i] = 0.6 + Math.random() * 0.3;
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
        bctx.setTransform(escala, 0, 0, escala, 0, 0);
        bctx.globalCompositeOperation = "source-over";
        bctx.clearRect(0, 0, W, H);
        var g = bctx.createLinearGradient(lx - 140, 0, lx + 16, 0);
        g.addColorStop(0, "rgba(255,255,255,0)");
        g.addColorStop(0.72, "rgba(255,255,255,.55)");
        g.addColorStop(0.93, "rgba(255,255,255,1)");
        g.addColorStop(1, "rgba(255,255,255,0)");
        bctx.fillStyle = g;
        bctx.fillRect(lx - 140, LOGO.y - 10, 156, LOGO.h + 20);
        bctx.globalCompositeOperation = "destination-in";
        bctx.setTransform(1, 0, 0, 1, 0, 0);
        bctx.drawImage(liso, 0, 0);
        bctx.globalCompositeOperation = "source-over";
        ctx.globalCompositeOperation = "lighter";
        ctx.drawImage(buf, 0, 0, W, H);
        ctx.globalCompositeOperation = "source-over";
    }

    function desenhar(tempo, dt) {
        ctx.setTransform(escala, 0, 0, escala, 0, 0);
        ctx.globalAlpha = 1;
        ctx.clearRect(0, 0, W, H);

        var laserLigado = tempo >= T.laser0 && tempo < T.laser1;
        var pronto = tempo >= T.laser1;
        var lp = limitar((tempo - T.laser0) / (T.laser1 - T.laser0), 0, 1);
        var laserX = pronto ? 1e5 : tempo < T.laser0 ? -1e5 :
            (LOGO.x - 16) + (LOGO.w + 50) * (0.5 - 0.5 * Math.cos(Math.PI * lp));

        if (laserLigado || pronto) {
            ctx.save();
            ctx.beginPath(); ctx.rect(0, 0, pronto ? W : laserX, MB); ctx.clip();
            ctx.drawImage(liso, 0, 0, W, H);
            ctx.restore();
        }

        if (!pronto) {
            var entrada = limitar(tempo / 0.5, 0, 1), i, k, p;
            for (i = 0; i < N; i++) P[i] = limitar((tempo - atraso[i]) / dur[i], 0, 1);
            for (k = 0; k < 2; k++) {
                ctx.fillStyle = VIAJANDO[k];
                for (i = 0; i < N; i++) {
                    p = P[i];
                    if (p >= 1 || tinta[i] !== k) continue;
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
                    ctx.globalAlpha = entrada * (p <= 0 ? 0.75 : 0.95);
                    ctx.fillRect(x - s / 2, y - s / 2, s, s);
                }
            }
            ctx.globalAlpha = 1;
            var clarao = [];
            for (var b = 0; b < baldes.length; b++) {
                ctx.fillStyle = corBalde[b];
                var lista = baldes[b];
                for (var j = 0; j < lista.length; j++) {
                    i = lista[j];
                    if (P[i] < 1 || tx[i] < laserX) continue;
                    if (tx[i] < laserX + 26) { clarao.push(i); continue; }
                    ctx.fillRect(tx[i] - PS / 2, ty[i] - PS / 2, PS, PS);
                }
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

    var velocidadeRapida = 0;
    function quadro(agora) {
        if (!rodando) return;
        var dt = Math.min(0.05, (agora - ultimo) / 1000);
        ultimo = agora;
        if (paginaPronta && t < T.laser1) {
            // Pagina pronta: chega no logo pronto em ate ACELERA_EM segundos.
            if (!velocidadeRapida) velocidadeRapida = Math.max(2.2, (T.laser1 - t) / ACELERA_EM);
            t = Math.min(T.laser1, t + dt * velocidadeRapida);
        } else {
            t += dt;
        }
        desenhar(t, dt);
        if (t >= T.laser1) {
            if (!chegouNoLogoEm) chegouNoLogoEm = agora;
            if (paginaPronta && agora - chegouNoLogoEm >= SEGURA_LOGO * 1000) {
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
        montarParticulas();
        window.addEventListener("resize", ajustar);
        rodando = true;
        ultimo = performance.now();
        requestAnimationFrame(quadro);
    };
    logo.onerror = encerrar;
    logo.src = cena.getAttribute("data-logo");
})();
