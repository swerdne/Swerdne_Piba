/* Deixa o CSS do Tailwind v4 legivel por navegadores antigos (Android 11 com
 * Chrome 80-87, iPhone com iOS 14+) sem mudar nada nos atuais.
 *
 * Por que: o Tailwind v4 gera tudo dentro de @layer (Chrome 99+). Um Chrome 83
 * nao entende @layer e descarta o bloco inteiro -- o app abria sem estilo
 * nenhum e os icones SVG (que dependem de w-5/h-5) ficavam gigantes.
 *
 * Roda depois do tailwindcss em `npm run build:css` e reescreve o style.css:
 *  - @layer: desembrulhado na mesma ordem (as regras soltas do input.css ja
 *    vem depois de todas as camadas, entao continuam vencendo os empates);
 *  - oklch()/oklab(): cor rgb de reserva antes (preset-env);
 *  - inset: top/right/bottom/left (preset-env);
 *  - :where()/:is(): copia expandida so pra quem nao entende :where()
 *    (@supports not selector(:where(a))), sem mexer na especificidade dos atuais;
 *  - @property (Chrome 85+): os valores iniciais das variaveis --tw-* vao num
 *    bloco so pra quem nao entende :where() -- sem eles sombra/anel/transform
 *    viram valor invalido;
 *  - translate/scale/rotate soltos (Chrome 104+): transform equivalente so
 *    pra quem nao entende `translate:` (@supports not (translate:0));
 *  - dvh/svh: 100vh de reserva antes;
 *  - gap em flexbox (Chrome 84+): margens em html.sem-gap-flex (classe posta
 *    pelo base.html quando o navegador nao tem gap em flex).
 */
const fs = require("fs");
const path = require("path");
const postcss = require("postcss");
const presetEnv = require("postcss-preset-env");

const ARQUIVO = path.join(__dirname, "..", "app", "static", "css", "style.css");
const ALVOS = ["chrome >= 80", "android >= 80", "ios_saf >= 14", "safari >= 14", "firefox >= 78", "edge >= 88"];
const SO_ANTIGOS = "not selector(:where(a))"; // Chrome < 88, Safari < 14

function desembrulharCamadas() {
  return {
    postcssPlugin: "desembrulhar-camadas",
    Once(raiz) {
      raiz.walkAtRules("layer", (regra) => {
        if (regra.nodes && regra.nodes.length) regra.replaceWith(regra.nodes);
        else regra.remove();
      });
    },
  };
}

function valoresIniciaisDasPropriedades() {
  return {
    postcssPlugin: "valores-iniciais-property",
    Once(raiz) {
      const decls = [];
      raiz.walkAtRules("property", (regra) => {
        let inicial = null;
        regra.walkDecls("initial-value", (d) => { inicial = d.value; });
        decls.push(postcss.decl({ prop: regra.params.trim(), value: inicial === null ? "initial" : inicial }));
      });
      if (!decls.length) return;
      const bloco = postcss.atRule({ name: "supports", params: SO_ANTIGOS });
      const regra = postcss.rule({ selector: "*,::before,::after,::backdrop" });
      decls.forEach((d) => regra.append(d));
      bloco.append(regra);
      // Logo no comeco: as classes do Tailwind (que vem depois) sobrepoem.
      raiz.prepend(bloco);
    },
  };
}

function copiaSemWhere() {
  return {
    postcssPlugin: "copia-sem-where",
    Once(raiz) {
      raiz.walkRules((regra) => {
        if (!/:(where|is)\(/.test(regra.selector)) return;
        if (regra.parent && regra.parent.type === "atrule" && regra.parent.params === SO_ANTIGOS) return;
        if (regra.parent && regra.parent.type === "atrule" && regra.parent.name === "keyframes") return;
        const seletores = expandir(regra.selector);
        if (!seletores) return;
        const copia = regra.clone({ selector: seletores.join(",") });
        const bloco = postcss.atRule({ name: "supports", params: SO_ANTIGOS });
        bloco.append(copia);
        regra.after(bloco);
      });
    },
  };
}

// Abre :where(a,b) / :is(a,b) em seletores separados. Devolve null se nao
// conseguir (parenteses estranhos) -- ai a regra fica so pros atuais.
function expandir(seletor) {
  const partes = dividirVirgulas(seletor);
  const saida = [];
  for (const parte of partes) {
    const abertos = abrir(parte.trim());
    if (!abertos) return null;
    saida.push(...abertos);
  }
  if (saida.length > 64) return null;
  return saida;
}

function dividirVirgulas(texto) {
  const partes = [];
  let nivel = 0, atual = "";
  for (const c of texto) {
    if (c === "(") nivel++;
    if (c === ")") nivel--;
    if (c === "," && nivel === 0) { partes.push(atual); atual = ""; continue; }
    atual += c;
  }
  partes.push(atual);
  return partes;
}

function abrir(seletor) {
  const m = /:(where|is)\(/.exec(seletor);
  if (!m) return [seletor];
  const inicio = m.index + m[0].length;
  let nivel = 1, i = inicio;
  for (; i < seletor.length && nivel > 0; i++) {
    if (seletor[i] === "(") nivel++;
    if (seletor[i] === ")") nivel--;
  }
  if (nivel !== 0) return null;
  const dentro = seletor.slice(inicio, i - 1);
  const antes = seletor.slice(0, m.index);
  const depois = seletor.slice(i);
  const resultado = [];
  for (const alternativa of dividirVirgulas(dentro)) {
    const resto = abrir(antes + alternativa.trim() + depois);
    if (!resto) return null;
    resultado.push(...resto);
  }
  return resultado;
}

function transformSolto() {
  const FUNCOES = { translate: "translate", scale: "scale", rotate: "rotate" };
  return {
    postcssPlugin: "transform-solto",
    Once(raiz) {
      raiz.walkDecls(/^(translate|scale|rotate)$/, (d) => {
        if (d.value === "none") return;
        const regra = d.parent;
        if (!regra || regra.type !== "rule") return;
        const args = d.prop === "rotate" ? d.value : d.value.trim().split(/\s+(?![^(]*\))/).join(", ");
        const bloco = postcss.atRule({ name: "supports", params: `not (${d.prop}:0)` });
        bloco.append(postcss.rule({ selector: regra.selector }).append(postcss.decl({ prop: "transform", value: `${FUNCOES[d.prop]}(${args})` })));
        regra.after(bloco);
      });
    },
  };
}

function reservaVh() {
  return {
    postcssPlugin: "reserva-vh",
    Declaration(d) {
      if (!/\d(dvh|svh|lvh)\b/.test(d.value) || d.__reserva) return;
      const prev = d.prev();
      if (prev && prev.type === "decl" && prev.prop === d.prop) return;
      d.__reserva = true;
      d.before(postcss.decl({ prop: d.prop, value: d.value.replace(/(dvh|svh|lvh)\b/g, "vh") }));
    },
  };
}

function gapEmFlex() {
  return {
    postcssPlugin: "gap-em-flex",
    OnceExit(raiz) {
      const novas = [];
      raiz.walkRules((regra) => {
        const m = /^\.(gap(?:-[xy])?-[\w.\\[\]]+)$/.exec(regra.selector);
        const pai = regra.parent;
        if (!m || !pai || !(pai.type === "root" || (pai.type === "atrule" && pai.name === "layer"))) return;
        let valorX = null, valorY = null;
        regra.walkDecls((d) => {
          if (d.prop === "gap") { const [a, b] = d.value.split(/\s+(?![^(]*\))/); valorY = a; valorX = b || a; }
          if (d.prop === "column-gap") valorX = d.value;
          if (d.prop === "row-gap") valorY = d.value;
        });
        const sel = regra.selector;
        const base = `.sem-gap-flex :is(.flex,.inline-flex)${sel}`;
        if (valorX) novas.push(postcss.rule({ selector: expandir(`${base}:not(.flex-col)>*+*`).join(",") }).append({ prop: "margin-left", value: valorX }));
        if (valorY) novas.push(postcss.rule({ selector: expandir(`${base}.flex-col>*+*`).join(",") }).append({ prop: "margin-top", value: valorY }));
      });
      novas.forEach((r) => raiz.append(r));
    },
  };
}

const css = fs.readFileSync(ARQUIVO, "utf8");
postcss([
  desembrulharCamadas(),
  valoresIniciaisDasPropriedades(),
  copiaSemWhere(),
  transformSolto(),
  reservaVh(),
  gapEmFlex(),
  presetEnv({
    browsers: ALVOS,
    stage: false,
    features: {
      "cascade-layers": false,
      "oklab-function": { preserve: true },
      "logical-properties-and-values": true,
      "nesting-rules": true,
      "is-pseudo-class": false,
    },
    autoprefixer: { grid: false },
  }),
])
  .process(css, { from: ARQUIVO, to: ARQUIVO })
  .then((resultado) => {
    resultado.warnings().forEach((w) => console.warn(w.toString()));
    fs.writeFileSync(ARQUIVO, resultado.css);
    console.log(`css-compat: ${ARQUIVO} (${(resultado.css.length / 1024).toFixed(1)} KB)`);
  });
