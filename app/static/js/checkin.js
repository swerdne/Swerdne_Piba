// Botoes de check-in por localizacao ([data-checkin-botao] dentro de um
// [data-checkin-bloco], com [data-checkin-texto] e [data-checkin-msg]; CSRF
// em [data-checkin-csrf]). Usado em Minha escala (escala e ensaios) e no
// Inicio (culto). O servidor confere a distancia ate o local.

// Som de confirmacao do check-in: um "ding" curto e baixo gerado pelo proprio
// navegador (Web Audio, duas notas senoidais -- sem arquivo pra baixar), mais
// uma vibracao curta no Android. O iPhone so deixa tocar som se o audio foi
// "liberado" num toque do usuario: preparar() roda no toque do botao, e
// tocar() so quando o servidor confirma (segundos depois, apos o GPS). No
// iPhone com a chave de silencioso ligada nao toca (regra do aparelho).
window.somDeConfirmacao = (function () {
    var contexto = null;
    function preparar() {
        try {
            var Classe = window.AudioContext || window.webkitAudioContext;
            if (!Classe) return;
            if (!contexto) contexto = new Classe();
            if (contexto.state === 'suspended') contexto.resume();
            // iOS mais antigo: tocar um trecho mudo no toque destrava o audio.
            var mudo = contexto.createBufferSource();
            mudo.buffer = contexto.createBuffer(1, 1, 22050);
            mudo.connect(contexto.destination);
            mudo.start(0);
        } catch (e) { contexto = null; }
    }
    function tocar() {
        if (navigator.vibrate) { try { navigator.vibrate(40); } catch (e) { /* sem vibracao */ } }
        if (!contexto) return;
        try {
            var inicio = contexto.currentTime + 0.02;
            [[880, 0], [1318.5, 0.12]].forEach(function (nota) {  // La5 e Mi6: "ding" agradavel
                var oscilador = contexto.createOscillator();
                var volume = contexto.createGain();
                var t = inicio + nota[1];
                oscilador.type = 'sine';
                oscilador.frequency.value = nota[0];
                volume.gain.setValueAtTime(0.0001, t);
                volume.gain.exponentialRampToValueAtTime(0.16, t + 0.015);
                volume.gain.exponentialRampToValueAtTime(0.0001, t + 0.35);
                oscilador.connect(volume);
                volume.connect(contexto.destination);
                oscilador.start(t);
                oscilador.stop(t + 0.4);
            });
        } catch (e) { /* sem som: o texto verde ja confirma */ }
    }
    return { preparar: preparar, tocar: tocar };
})();

(function () {
    // Check-in por localizacao: pega a melhor posicao do GPS em ate ~12 s
    // (a 1a leitura costuma vir imprecisa e melhora em segundos) e manda pro
    // servidor, que confere a distancia ate o local (escala.routes.checkin).
    document.querySelectorAll('[data-checkin-botao]').forEach(function (botao) {
        var bloco = botao.closest('[data-checkin-bloco]');
        var texto = botao.querySelector('[data-checkin-texto]');
        var msg = bloco.querySelector('[data-checkin-msg]');
        var classeNeutra = (msg.className.match(/text-gray-\d+/) || ['text-gray-500'])[0];
        var campoCsrf = document.querySelector('[data-checkin-csrf] input[name="csrf_token"]');
        var BOA_PRECISAO = 30, ESPERA_MAXIMA = 12000;

        function mostrar(textoMsg, tipo) {
            msg.textContent = textoMsg;
            msg.className = 'text-sm font-semibold ' +
                (tipo === 'ok' ? 'text-emerald-600' : tipo === 'erro' ? 'text-red-500' : classeNeutra);
        }
        function liberar(rotulo) {
            botao.disabled = false;
            texto.textContent = rotulo || 'Tentar de novo';
        }

        function enviar(pos) {
            texto.textContent = 'Conferindo…';
            var corpo = new URLSearchParams();
            corpo.append('csrf_token', campoCsrf ? campoCsrf.value : '');
            corpo.append('latitude', pos.coords.latitude);
            corpo.append('longitude', pos.coords.longitude);
            corpo.append('precisao', pos.coords.accuracy);
            fetch(botao.getAttribute('data-url'), { method: 'POST', credentials: 'same-origin', body: corpo })
                .then(function (r) {
                    if (r.status === 429) throw new Error('muitas');
                    return r.json();
                })
                .then(function (dados) {
                    if (dados.ok) {
                        mostrar(dados.mensagem, 'ok');
                        texto.textContent = 'Presença confirmada';
                        window.somDeConfirmacao.tocar();
                        setTimeout(function () { window.location.reload(); }, 1500);
                    } else {
                        mostrar(dados.mensagem, 'erro');
                        liberar();
                    }
                })
                .catch(function (e) {
                    mostrar(e && e.message === 'muitas'
                        ? 'Muitas tentativas seguidas. Espere um minuto e tente de novo.'
                        : 'Sem conexão com o servidor. Confira a internet e tente de novo.', 'erro');
                    liberar();
                });
        }

        botao.addEventListener('click', function () {
            if (!window.isSecureContext || !navigator.geolocation) {
                mostrar('Este navegador não informa a localização. Abra o app pelo Safari ou Chrome atualizado.', 'erro');
                return;
            }
            window.somDeConfirmacao.preparar();  // no toque: libera o som no iPhone
            botao.disabled = true;
            texto.textContent = 'Localizando…';
            mostrar('Buscando o sinal do GPS. Se o celular perguntar, toque em “Permitir”.');

            var melhor = null, terminou = false, vigia = null, limite = null;
            function terminar() {
                if (terminou) return;
                terminou = true;
                if (vigia !== null) navigator.geolocation.clearWatch(vigia);
                clearTimeout(limite);
                if (melhor) enviar(melhor);
                else { mostrar('O GPS não respondeu a tempo. Vá para um lugar aberto ou perto de uma janela e tente de novo.', 'erro'); liberar(); }
            }
            vigia = navigator.geolocation.watchPosition(function (pos) {
                if (!melhor || pos.coords.accuracy < melhor.coords.accuracy) melhor = pos;
                if (pos.coords.accuracy <= BOA_PRECISAO) terminar();
            }, function (erro) {
                if (terminou) return;
                if (erro.code === 1) {
                    terminou = true;
                    navigator.geolocation.clearWatch(vigia);
                    clearTimeout(limite);
                    mostrar('O check-in precisa da sua localização, e a permissão foi negada. Para liberar: no iPhone, Ajustes › Privacidade › Serviços de Localização › Safari (ou o app) › “Durante o uso”; no Android, toque no cadeado ao lado do endereço do site › Permissões › Localização.', 'erro');
                    liberar();
                } else if (!melhor && erro.code === 2) {
                    terminou = true;
                    navigator.geolocation.clearWatch(vigia);
                    clearTimeout(limite);
                    mostrar('A localização do celular está desligada ou indisponível. Ligue a localização (GPS) e tente de novo.', 'erro');
                    liberar();
                }
                // Tempo esgotado (code 3) com alguma leitura: usa a melhor que veio.
            }, { enableHighAccuracy: true, timeout: ESPERA_MAXIMA, maximumAge: 0 });
            limite = setTimeout(terminar, ESPERA_MAXIMA);
        });
    });
})();
