/* Prova da chave entre os dois modelos aprovados — Claro e Escuro.
 *
 * A tela e provada em Python; o que nao da para provar de la e o CLIQUE:
 * se a classe entra no lugar certo, se a chave acende o botao certo, e se a
 * escolha sobrevive a recarregar a pagina. E o ponto de escorregar e esse
 * ultimo: o script que aplica o tema roda no meio do corpo, antes do painel
 * existir. Se ele procurasse o elemento errado, a tela nasceria clara e so
 * viraria escura depois — a piscada que se quis evitar.
 *
 *   node prova_lucro_tema.js caminho/da/tela.html
 *
 * Sem argumento, usa a saida que a prova em Python guarda.
 */
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const alvo = process.argv[2] || path.join(__dirname, '_lucro_migrado.html');
if (!fs.existsSync(alvo)) {
  console.error('Nao achei %s — rode antes:\n  python prova_lucro_migrado.py --html %s',
                alvo, alvo);
  process.exit(2);
}
const html = fs.readFileSync(alvo, 'utf8');

const falhas = [];
function prova(titulo, ok, detalhe) {
  console.log('%s %s', ok ? 'OK    ' : 'FALHA ', titulo);
  if (!ok) {
    if (detalhe) console.log('        ' + detalhe);
    falhas.push(titulo);
  }
}

/* Um navegador de mentira com localStorage de verdade, para a escolha poder
 * sobreviver de uma carga para a outra. */
function abrir(guardado) {
  const dom = new JSDOM(html, { runScripts: 'dangerously' });
  const loja = {};
  if (guardado) loja['lpm_tema'] = guardado;
  Object.defineProperty(dom.window, 'localStorage', {
    configurable: true,
    value: {
      getItem: (k) => (k in loja ? loja[k] : null),
      setItem: (k, v) => { loja[k] = String(v); },
      removeItem: (k) => { delete loja[k]; },
    },
  });
  return { dom, loja };
}

/* O script embutido ja rodou com o localStorage padrao do jsdom (vazio), que
 * e o caso "primeira visita". Para os outros casos, reexecuta-se o mesmo
 * codigo da pagina — nao uma copia dele. */
function rodarScripts(dom) {
  const d = dom.window.document;
  d.querySelectorAll('script').forEach((s) => {
    if (s.src) return;
    try { dom.window.eval(s.textContent); } catch (e) { /* ignora */ }
  });
}

// ── a chave existe, com os dois modelos ──────────────────────────────────
{
  const { dom } = abrir(null);
  const d = dom.window.document;
  const bts = d.querySelectorAll('#lpm .tema button');
  prova('a chave oferece os dois modelos', bts.length === 2,
        'achei ' + bts.length + ' botao(oes)');
  const nomes = Array.from(bts).map((b) => b.getAttribute('data-tema'));
  prova('e eles sao o claro e o escuro',
        nomes.indexOf('claro') >= 0 && nomes.indexOf('escuro') >= 0,
        JSON.stringify(nomes));
  prova('sem nada guardado, abre no claro',
        !d.getElementById('lpm').classList.contains('escuro'));
  prova('e o botao aceso e o do claro',
        d.querySelector('#lpm .tema button[data-tema="claro"]').classList.contains('on') &&
        !d.querySelector('#lpm .tema button[data-tema="escuro"]').classList.contains('on'));
}

// ── clicar escurece de verdade, e guarda ─────────────────────────────────
{
  const { dom, loja } = abrir(null);
  const d = dom.window.document;
  rodarScripts(dom);
  d.querySelector('#lpm .tema button[data-tema="escuro"]').click();
  prova('clicar em Escuro escurece o painel',
        d.getElementById('lpm').classList.contains('escuro'));
  prova('e acende o botao certo',
        d.querySelector('#lpm .tema button[data-tema="escuro"]').classList.contains('on') &&
        !d.querySelector('#lpm .tema button[data-tema="claro"]').classList.contains('on'));
  prova('a escolha fica guardada no navegador', loja['lpm_tema'] === 'escuro',
        'guardou ' + JSON.stringify(loja['lpm_tema']));

  d.querySelector('#lpm .tema button[data-tema="claro"]').click();
  prova('e voltar para o Claro desfaz',
        !d.getElementById('lpm').classList.contains('escuro') &&
        loja['lpm_tema'] === 'claro');
}

// ── o que importa: abrir de novo ja vem escuro, sem piscar ───────────────
{
  const { dom } = abrir('escuro');
  const d = dom.window.document;
  // so o script de dentro do corpo — o que roda ANTES do painel existir
  const dentro = Array.from(d.querySelectorAll('#lpm > script'));
  prova('o tema e aplicado por um script dentro do #lpm, antes do painel',
        dentro.length === 1,
        'achei ' + dentro.length + ' script(s) dentro do #lpm');
  if (dentro.length === 1) {
    dom.window.eval(dentro[0].textContent);
    prova('quem escolheu escuro reabre no escuro',
          d.getElementById('lpm').classList.contains('escuro'));
    const painel = d.querySelector('#lpm .painel');
    prova('e a classe esta no ancestral do painel, entao ele ja nasce escuro',
          !!painel && d.getElementById('lpm').contains(painel));
  }
  rodarScripts(dom);
  prova('a chave reabre mostrando o escuro como o que esta valendo',
        d.querySelector('#lpm .tema button[data-tema="escuro"]').classList.contains('on'));
}

// ── um navegador que proibe localStorage nao pode derrubar a tela ────────
{
  const dom = new JSDOM(html, { runScripts: 'dangerously' });
  Object.defineProperty(dom.window, 'localStorage', {
    configurable: true,
    get() { throw new Error('bloqueado'); },
  });
  let quebrou = false;
  try {
    rodarScripts(dom);
    dom.window.document
      .querySelector('#lpm .tema button[data-tema="escuro"]').click();
  } catch (e) { quebrou = true; }
  prova('com o armazenamento bloqueado, a chave ainda funciona', !quebrou);
  prova('e o painel escurece do mesmo jeito',
        dom.window.document.getElementById('lpm').classList.contains('escuro'));
}

// ── a cor de cada combustivel viaja no elemento, nao na regra ────────────
{
  const { dom } = abrir(null);
  const d = dom.window.document;
  const linhas = d.querySelectorAll('#lpm .rk');
  prova('cada combustivel leva as duas cores dele', linhas.length > 0 &&
        Array.from(linhas).every((l) => {
          const st = l.getAttribute('style') || '';
          return st.indexOf('--c:') >= 0 && st.indexOf('--c2:') >= 0;
        }),
        'sem as duas, a barra sumiria no fundo escuro');
}

console.log('\n%s', falhas.length
  ? falhas.length + ' FALHA(S): ' + falhas.join('; ')
  : 'TUDO OK');
process.exit(falhas.length ? 1 : 0);
