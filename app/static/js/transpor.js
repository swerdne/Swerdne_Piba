// Transposicao de cifras na tela -- mesma logica de app/escala/models.py
// (transpor_cifra/transpor_tom), pra o resultado bater com a folha impressa.
(function () {
    var SUST = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];
    var BEMOL = ['C', 'Db', 'D', 'Eb', 'E', 'F', 'Gb', 'G', 'Ab', 'A', 'Bb', 'B'];
    var INDICE = { 'Cb': 11, 'B#': 0, 'E#': 5, 'Fb': 4 };
    SUST.forEach(function (n, i) { INDICE[n] = i; });
    BEMOL.forEach(function (n, i) { INDICE[n] = i; });
    var MAIORES_BEMOL = [5, 10, 3, 8, 1];
    var MENORES_BEMOL = [2, 7, 0, 5, 10, 3];

    // Mesmas regras de app/escala/models.py (_SUFIXO/_MARCAS_OK) -- manter iguais.
    var SUFIXO = '(?:maj|min|dim|aug|sus|add|no|omit|alt|m|M|º|°|ø|Δ|\\+|-|\\d|\\(|\\)|[#b](?=\\d)|/(?=[#b]?\\d)|,)*';
    var TOKEN = new RegExp('^(\\(?)([A-G][#b]?)(' + SUFIXO + ')(?:/([A-G][#b]?))?([)\\],.]*)$');
    var ROTULO = /^\s*(?:\[[^\]]*\]|[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ ]*\d*\s*:)/;
    var MARCAS = /^(?:\|+:?|:\|+|:|-+|\/|%|\(|\)|\.{2,}|…|->|→|\*+|N\.?C\.?|\(?\d*x\d*\)?|\(?\d+x?\)?)$/i;
    var TOM = /^\s*([A-G][#b]?)(m(?!aj))?/;

    function mod12(n) { return ((n % 12) + 12) % 12; }

    function lerTom(tom) {
        var m = TOM.exec(tom || '');
        return m ? { indice: INDICE[m[1]], menor: !!m[2], nota: m[1] } : null;
    }

    function prefereBemol(tom) {
        var t = lerTom(tom);
        if (!t) return false;
        if (t.nota.length === 2) return t.nota[1] === 'b';
        return (t.menor ? MENORES_BEMOL : MAIORES_BEMOL).indexOf(t.indice) !== -1;
    }

    function transporTom(tom, semitons) {
        var t = lerTom(tom);
        if (!t) return tom;
        var novo = mod12(t.indice + semitons);
        var bemol = (t.menor ? MENORES_BEMOL : MAIORES_BEMOL).indexOf(novo) !== -1;
        return (bemol ? BEMOL : SUST)[novo] + (t.menor ? 'm' : '');
    }

    function nota(n, s, bemol) { return (bemol ? BEMOL : SUST)[mod12(INDICE[n] + s)]; }

    function token(t, s, bemol) {
        var m = TOKEN.exec(t);
        if (!m) return t;
        var novo = m[1] + nota(m[2], s, bemol) + m[3];
        if (m[4]) novo += '/' + nota(m[4], s, bemol);
        return novo + m[5];
    }

    function ehLinhaDeAcordes(linha) {
        var resto = linha.replace(ROTULO, '');
        var tokens = resto.split(/\s+/).filter(Boolean);
        var acordes = 0;
        for (var i = 0; i < tokens.length; i++) {
            if (TOKEN.test(tokens[i])) acordes++;
            else if (!MARCAS.test(tokens[i])) return false;
        }
        return acordes > 0;
    }

    function linha(l, s, bemol) {
        var saida = '', sobra = 0;
        l.split(/(\s+)/).forEach(function (parte) {
            if (!parte) return;
            if (/^\s+$/.test(parte)) {
                if (sobra) {
                    var tamanho = parte.length - sobra;
                    sobra = 0;
                    if (tamanho < 1) { sobra = 1 - tamanho; tamanho = 1; }
                    parte = new Array(tamanho + 1).join(' ');
                }
                saida += parte;
                return;
            }
            var nova = token(parte, s, bemol);
            sobra += nova.length - parte.length;
            saida += nova;
        });
        return saida;
    }

    function cifra(texto, s, bemol) {
        if (!texto || !mod12(s)) return texto;
        return texto.replace(/\r\n/g, '\n').split('\n').map(function (l) {
            return ehLinhaDeAcordes(l) ? linha(l, s, bemol) : l;
        }).join('\n');
    }

    // Sem tom cadastrado: decide bemol/sustenido pelo que a cifra ja usa.
    function bemolPeloTexto(texto) {
        var b = (texto.match(/\b[A-G]b/g) || []).length;
        var s = (texto.match(/\b[A-G]#/g) || []).length;
        return b > s;
    }

    // Acordes em <span class="acorde"> (cor forte, ver static/css/input.css) --
    // monta com nos de texto, nunca innerHTML com o texto da cifra. Mesma
    // logica de escala.models.cifra_em_html (folha impressa).
    function colorirCifra(pre, texto) {
        pre.textContent = '';
        texto.replace(/\r\n/g, '\n').split('\n').forEach(function (linha, n) {
            if (n) pre.appendChild(document.createTextNode('\n'));
            if (!ehLinhaDeAcordes(linha)) { pre.appendChild(document.createTextNode(linha)); return; }
            linha.split(/(\s+)/).forEach(function (pedaco) {
                if (pedaco && !/^\s+$/.test(pedaco) && TOKEN.test(pedaco)) {
                    var span = document.createElement('span');
                    span.className = 'acorde';
                    span.textContent = pedaco;
                    pre.appendChild(span);
                } else if (pedaco) {
                    pre.appendChild(document.createTextNode(pedaco));
                }
            });
        });
    }
    document.querySelectorAll('pre[data-colorir-acordes]').forEach(function (pre) { colorirCifra(pre, pre.textContent); });

    window.Transpor = { cifra: cifra, tom: transporTom, prefereBemol: prefereBemol, lerTom: lerTom, bemolPeloTexto: bemolPeloTexto, colorir: colorirCifra };

    // Liga os controles: [data-transpor] envolve os botoes; o alvo e um
    // textarea (lider, edita e salva) ou um <pre> (so leitura).
    document.querySelectorAll('[data-transpor]').forEach(function (caixa) {
        var alvo = document.querySelector(caixa.getAttribute('data-transpor'));
        if (!alvo) return;
        var ehCampo = alvo.tagName === 'TEXTAREA';
        var ler = function () { return ehCampo ? alvo.value : alvo.textContent; };
        var escrever = function (t) {
            if (ehCampo) alvo.value = t;
            else if (alvo.hasAttribute('data-colorir-acordes')) colorirCifra(alvo, t);
            else alvo.textContent = t;
        };
        var tomOriginal = caixa.getAttribute('data-tom') || '';
        var textoOriginal = ler();
        var tomAtual = tomOriginal;
        var deslocamento = 0;
        var seletor = caixa.querySelector('[data-transpor-tom]');
        var rotulo = caixa.querySelector('[data-transpor-rotulo]');
        var campoTom = document.querySelector(caixa.getAttribute('data-transpor-campo') || '_');
        var aviso = document.querySelector(caixa.getAttribute('data-transpor-aviso') || '_');
        var original = caixa.querySelector('[data-transpor-original]');

        if (seletor && lerTom(tomOriginal)) {
            for (var i = 0; i < 12; i++) {
                var opcao = document.createElement('option');
                opcao.value = String(i);
                opcao.textContent = transporTom(tomOriginal, i) + (i === 0 ? ' (atual)' : '');
                seletor.appendChild(opcao);
            }
        } else if (seletor) {
            seletor.classList.add('hidden');
        }

        // Avisa o rascunho automatico (static/js/rascunho.js) que o texto mudou.
        function avisarMudanca() {
            if (ehCampo) alvo.dispatchEvent(new Event('input', { bubbles: true }));
        }

        function atualizar() {
            var d = mod12(deslocamento);
            if (seletor) seletor.value = String(d);
            if (rotulo) {
                rotulo.textContent = lerTom(tomOriginal)
                    ? '' : (d ? (deslocamento > 0 ? '+' : '') + (deslocamento) + ' semitom' + (Math.abs(deslocamento) > 1 ? 's' : '') : 'Tom original');
            }
            if (original) original.classList.toggle('hidden', d === 0);
            // O campo leva o tom do texto que esta no editor: o servidor grava
            // na original (se for o tom do cadastro) ou numa versao separada.
            if (campoTom) campoTom.value = lerTom(tomOriginal) ? tomAtual : '';
            if (aviso) {
                aviso.classList.toggle('hidden', d === 0);
                var cadastro = lerTom(caixa.getAttribute('data-tom-cadastro'));
                var atual = lerTom(tomAtual);
                var ehOriginal = cadastro && atual && cadastro.indice === atual.indice && cadastro.menor === atual.menor;
                aviso.textContent = !atual ? 'Ao salvar, a cifra e substituida pela convertida.'
                    : ehOriginal ? 'Ao salvar, substitui a cifra original em ' + tomAtual + '.'
                    : 'Ao salvar, vira uma versao em ' + tomAtual + ' -- a original nao muda.';
            }
        }

        function mover(passo) {
            var texto = ler();
            var novoTom = lerTom(tomOriginal) ? transporTom(tomOriginal, mod12(deslocamento + passo)) : '';
            var bemol = novoTom ? prefereBemol(novoTom) : bemolPeloTexto(texto);
            escrever(cifra(texto, passo, bemol));
            deslocamento += passo;
            tomAtual = novoTom;
            atualizar();
            avisarMudanca();
        }

        caixa.querySelectorAll('[data-transpor-passo]').forEach(function (botao) {
            botao.addEventListener('click', function () { mover(parseInt(botao.getAttribute('data-transpor-passo'), 10)); });
        });
        if (seletor) {
            seletor.addEventListener('change', function () {
                var alvoD = parseInt(seletor.value, 10);
                var passo = mod12(alvoD - mod12(deslocamento));
                if (passo > 6) passo -= 12;
                mover(passo);
            });
        }
        if (original) {
            original.addEventListener('click', function () {
                escrever(textoOriginal);
                deslocamento = 0;
                tomAtual = tomOriginal;
                atualizar();
                avisarMudanca();
            });
        }
        atualizar();
    });
})();
