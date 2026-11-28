// Modo palco: a cifra em tela cheia, fundo escuro, letra grande (A- / A+),
// rolagem automatica com velocidade ajustavel e tela sempre ligada (Wake
// Lock, quando o navegador tem). Botao: [data-modo-palco="#seletor"].
// O seletor pode ser um <pre> (pagina da musica: leva a cifra no tom que
// esta na tela) ou a folha do repertorio da escala (todas as musicas do dia,
// uma depois da outra). Estilo inline: a folha nao carrega o Tailwind.
// Tamanho da letra e velocidade ficam guardados neste aparelho.
(function () {
    var botoes = document.querySelectorAll('[data-modo-palco]');
    if (!botoes.length) return;

    function ler(chave, padrao) {
        try { var v = parseFloat(localStorage.getItem(chave)); return isNaN(v) ? padrao : v; } catch (e) { return padrao; }
    }
    function guardar(chave, valor) { try { localStorage.setItem(chave, String(valor)); } catch (e) { /* sem armazenamento */ } }
    function escapar(t) { return t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }

    var tela = null, texto, rotuloVel, rotuloFonte, botaoRolar;
    var fonte = ler('palco-fonte', 22), velocidade = ler('palco-velocidade', 3);
    var rolando = false, ultimo = null, sobra = 0, trava = null;

    function botao(rotulo, titulo, acao) {
        var b = document.createElement('button');
        b.type = 'button';
        b.title = titulo;
        b.setAttribute('aria-label', titulo);
        b.style.cssText = 'min-width:36px;height:38px;padding:0 9px;border:0;border-radius:11px;background:rgba(255,255,255,.12);' +
            'color:#fff;font-size:15px;font-weight:700;cursor:pointer;margin:0 4px 0 0';
        b.innerHTML = rotulo;
        b.addEventListener('click', acao);
        return b;
    }
    function rotulo() {
        var s = document.createElement('span');
        s.style.cssText = 'color:rgba(255,255,255,.6);font-size:11px;min-width:22px;text-align:center;margin-right:4px';
        return s;
    }

    function montar() {
        tela = document.createElement('div');
        tela.setAttribute('data-palco', '');
        tela.style.cssText = 'position:fixed;top:0;right:0;bottom:0;left:0;z-index:2147483000;background:#000;color:#fff;' +
            'display:flex;flex-direction:column';
        var barra = document.createElement('div');
        barra.style.cssText = 'display:flex;flex-wrap:wrap;align-items:center;row-gap:6px;padding:8px 8px;' +
            'padding-top:max(8px, env(safe-area-inset-top));background:#0b0b0b;border-bottom:1px solid rgba(255,255,255,.1)';
        barra.appendChild(botao('&#x2715;', 'Sair do modo palco', fechar));
        barra.appendChild(botao('A&minus;', 'Letra menor', function () { mudarFonte(-2); }));
        rotuloFonte = rotulo();
        barra.appendChild(rotuloFonte);
        barra.appendChild(botao('A+', 'Letra maior', function () { mudarFonte(2); }));
        var espaco = document.createElement('span');
        espaco.style.flex = '1';
        barra.appendChild(espaco);
        botaoRolar = botao('&#9654;&#xFE0E;', 'Rolar sozinho', alternarRolagem);
        barra.appendChild(botaoRolar);
        barra.appendChild(botao('&minus;', 'Mais devagar', function () { mudarVelocidade(-1); }));
        rotuloVel = rotulo();
        barra.appendChild(rotuloVel);
        barra.appendChild(botao('+', 'Mais rápido', function () { mudarVelocidade(1); }));
        texto = document.createElement('div');
        texto.setAttribute('data-palco-texto', '');
        texto.style.cssText = 'flex:1;overflow:auto;-webkit-overflow-scrolling:touch;padding:24px 16px 50vh;' +
            'white-space:pre;line-height:1.5;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace';
        texto.addEventListener('touchstart', function () { if (rolando) alternarRolagem(); }, { passive: true });
        tela.appendChild(barra);
        tela.appendChild(texto);
        document.body.appendChild(tela);
        document.addEventListener('keydown', function (e) {
            if (!tela || tela.style.display === 'none') return;
            if (e.key === 'Escape') fechar();
            if (e.key === ' ') { e.preventDefault(); alternarRolagem(); }
        });
    }

    // Conteudo: um <pre>/<textarea> direto, ou cada <section> da folha (titulo + cifra/letra).
    function conteudo(origem) {
        if (origem.tagName === 'TEXTAREA') return escapar(origem.value);
        if (origem.tagName === 'PRE') return origem.innerHTML;
        var partes = [];
        origem.querySelectorAll('section').forEach(function (sec) {
            var titulo = sec.querySelector('h2');
            var corpo = sec.querySelector('pre');
            var bloco = '<span style="color:#fbbf24;font-weight:700">' + escapar(titulo ? titulo.textContent.trim() : '') + '</span>\n';
            if (corpo) {
                bloco += corpo.innerHTML;
            } else {
                var linhas = [];
                sec.querySelectorAll('.rotulo, .linha').forEach(function (p) { linhas.push(escapar(p.textContent)); });
                bloco += linhas.join('\n');
            }
            partes.push(bloco);
        });
        return partes.join('\n\n\n');
    }

    function mudarFonte(passo) {
        fonte = Math.max(14, Math.min(48, fonte + passo));
        texto.style.fontSize = fonte + 'px';
        rotuloFonte.textContent = fonte;
        guardar('palco-fonte', fonte);
    }
    function mudarVelocidade(passo) {
        velocidade = Math.max(1, Math.min(10, velocidade + passo));
        rotuloVel.textContent = velocidade;
        guardar('palco-velocidade', velocidade);
    }

    function quadro(agora) {
        if (!rolando) return;
        if (ultimo !== null) {
            // velocidade 1..10 -> 6..60 px por segundo
            sobra += (agora - ultimo) / 1000 * velocidade * 6;
            var inteiro = Math.floor(sobra);
            if (inteiro) { texto.scrollTop += inteiro; sobra -= inteiro; }
            if (texto.scrollTop + texto.clientHeight >= texto.scrollHeight - 1) { alternarRolagem(); return; }
        }
        ultimo = agora;
        requestAnimationFrame(quadro);
    }
    function alternarRolagem() {
        rolando = !rolando;
        ultimo = null;
        botaoRolar.innerHTML = rolando ? '&#10073;&#10073;' : '&#9654;&#xFE0E;';
        botaoRolar.title = rolando ? 'Parar' : 'Rolar sozinho';
        botaoRolar.setAttribute('aria-label', botaoRolar.title);
        if (rolando) requestAnimationFrame(quadro);
    }

    function manterTelaLigada() {
        if (!('wakeLock' in navigator)) return;
        navigator.wakeLock.request('screen').then(function (t) { trava = t; }).catch(function () { trava = null; });
    }
    document.addEventListener('visibilitychange', function () {
        // O navegador solta a trava quando a tela some; pede de novo ao voltar.
        if (tela && tela.style.display !== 'none' && document.visibilityState === 'visible') manterTelaLigada();
    });

    function abrir(origem) {
        if (!tela) montar();
        texto.innerHTML = conteudo(origem);
        texto.scrollTop = 0;
        mudarFonte(0);
        mudarVelocidade(0);
        tela.style.display = 'flex';
        document.documentElement.style.overflow = 'hidden';
        manterTelaLigada();
        if (tela.requestFullscreen) {
            var pedido = tela.requestFullscreen();
            if (pedido && pedido.catch) pedido.catch(function () { /* iPhone: fica a tela fixa */ });
        }
    }
    function fechar() {
        if (rolando) alternarRolagem();
        tela.style.display = 'none';
        document.documentElement.style.overflow = '';
        if (trava) { trava.release().catch(function () {}); trava = null; }
        if (document.fullscreenElement && document.exitFullscreen) document.exitFullscreen().catch(function () {});
    }

    botoes.forEach(function (b) {
        b.addEventListener('click', function () {
            var origem = document.querySelector(b.getAttribute('data-modo-palco'));
            if (origem) abrir(origem);
        });
    });
})();
