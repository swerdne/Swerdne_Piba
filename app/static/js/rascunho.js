// Rascunho automatico de formularios: enquanto a pessoa edita (e ate clicar
// em Salvar), o conteudo fica guardado NESTE aparelho (localStorage). Se a
// pagina recarregar -- salvou outra aba, trocou de tom, fechou sem querer --
// o texto volta sozinho, com aviso e opcao de descartar.
//
// Uso: <form data-guardar-rascunho="chave-unica"> com, dentro dele,
// [data-rascunho-status] (texto "falta salvar") e opcionalmente
// [data-rascunho-restaurado] (aviso escondido com botao [data-rascunho-descartar]).
// Quem altera um campo via JS deve disparar o evento "input" nele.
(function () {
    var PREFIXO = 'tybenson:rascunho:';

    function ler(chave) {
        try { return JSON.parse(localStorage.getItem(PREFIXO + chave) || 'null'); } catch (e) { return null; }
    }
    function gravar(chave, dados) {
        try { localStorage.setItem(PREFIXO + chave, JSON.stringify(dados)); } catch (e) { /* sem storage: so nao guarda */ }
    }
    function apagar(chave) {
        try { localStorage.removeItem(PREFIXO + chave); } catch (e) { /* idem */ }
    }

    function campos(form) {
        return Array.prototype.filter.call(form.elements, function (c) {
            return c.name && c.name !== 'csrf_token' && /^(INPUT|TEXTAREA|SELECT)$/.test(c.tagName) &&
                c.type !== 'submit' && c.type !== 'button' && c.type !== 'file';
        });
    }
    function valores(form) {
        var v = {};
        campos(form).forEach(function (c) { v[c.name] = c.type === 'checkbox' ? c.checked : c.value; });
        return v;
    }
    function aplicar(form, v) {
        campos(form).forEach(function (c) {
            if (!(c.name in v)) return;
            if (c.type === 'checkbox') c.checked = !!v[c.name]; else c.value = v[c.name];
        });
    }
    function iguais(a, b) {
        var normal = function (t) { return typeof t === 'string' ? t.replace(/\r\n/g, '\n').replace(/^\n/, '') : t; };
        return Object.keys(a).every(function (k) { return normal(a[k]) === normal(b[k]); });
    }

    document.querySelectorAll('form[data-guardar-rascunho]').forEach(function (form) {
        var chave = form.getAttribute('data-guardar-rascunho');
        var salvos = valores(form);  // o que veio do servidor
        var status = form.querySelector('[data-rascunho-status]');
        var restaurado = form.querySelector('[data-rascunho-restaurado]');

        function marcar(pendente) {
            if (status) status.classList.toggle('hidden', !pendente);
            form.dispatchEvent(new CustomEvent('rascunho:estado', { detail: { pendente: pendente } }));
        }

        var guardado = ler(chave);
        if (guardado && guardado.valores && !iguais(guardado.valores, salvos)) {
            aplicar(form, guardado.valores);
            form.dispatchEvent(new CustomEvent('rascunho:restaurado', { detail: guardado.valores }));
            if (restaurado) restaurado.classList.remove('hidden');
            marcar(true);
        } else if (guardado) {
            apagar(chave);  // igual ao salvo: nao ha o que restaurar
        }

        var espera;
        function guardar() {
            var atuais = valores(form);
            if (iguais(atuais, salvos)) {
                apagar(chave);
                marcar(false);
            } else {
                gravar(chave, { valores: atuais, em: Date.now() });
                marcar(true);
            }
        }
        form.addEventListener('input', function () { clearTimeout(espera); espera = setTimeout(guardar, 300); });
        form.addEventListener('change', guardar);

        // Salvou: o servidor passa a ter esse conteudo, o rascunho sai.
        form.addEventListener('submit', function () { clearTimeout(espera); apagar(chave); });

        var descartar = form.querySelector('[data-rascunho-descartar]');
        if (descartar) {
            // Recarrega em vez de recompor os campos na mao: assim qualquer
            // estado derivado (ex: o tom do transpositor) volta certinho.
            descartar.addEventListener('click', function () {
                apagar(chave);
                location.reload();
            });
        }
    });
})();
