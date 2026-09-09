// Prova de que o botao de mover ABRE o painel -- com DOM de verdade.
//
// O defeito: entre a linha do frete e o painel entrou o bloco de edicao
// (05/09/2026), e o JS procurava o painel como irmao IMEDIATO da linha. O
// botao ficou mudo em toda carga aberta, sem erro nenhum no console.
//
// Renderizar o template nao acusaria: o painel esta no HTML, escondido. So
// clicando se ve. Por isso este teste usa jsdom e chama a funcao que esta no
// proprio arquivo servido, extraida do <script> inline.
//
//   python prova_frete_terceiro.py --html tela.html
//   npm install jsdom          (numa pasta qualquer, fora do projeto)
//   set NODE_PATH=<aquela pasta>\node_modules
//   node prova_mover_abre.js tela.html
//
const fs = require('fs');
const { JSDOM } = require('jsdom');
const html = fs.readFileSync(process.argv[2], 'utf8');
const dom = new JSDOM(html);
const doc = dom.window.document;
global.document = doc;

// A funcao provada e a do proprio arquivo, extraida do <script> inline.
const m = html.match(/function pfnAbreMover\(botao, freteId\)\{[\s\S]*?\n\}/);
if (!m) { console.log('FALHA  nao achei pfnAbreMover no HTML'); process.exit(1); }
const pfnAbreMover = new Function('document', m[0] + '; return pfnAbreMover;')(doc);

let falhas = 0;
function prova(t, ok, d){ console.log((ok?'OK    ':'FALHA ')+t); if(!ok){ if(d)console.log('        '+d); falhas++; } }

const botoes = [...doc.querySelectorAll('.fr__mv')];
prova('a tela tem botao de mover para provar', botoes.length > 0, botoes.length+' botoes');

// Todo painel comeca escondido.
prova('todo painel de mover comeca escondido',
      [...doc.querySelectorAll('.mv')].every(e => e.hasAttribute('hidden')));

// Clicar abre o painel DAQUELE frete.
let abriu = 0, certo = 0;
for (const b of botoes) {
  pfnAbreMover(b);
  const linha = b.closest('.fr');
  // o painel esperado: o primeiro .mv depois desta linha
  let esperado = linha.nextElementSibling;
  while (esperado && !esperado.classList.contains('mv')) esperado = esperado.nextElementSibling;
  const abertos = [...doc.querySelectorAll('.mv')].filter(e => !e.hasAttribute('hidden'));
  if (abertos.length === 1) abriu++;
  if (abertos.length === 1 && abertos[0] === esperado) certo++;
  pfnAbreMover(b);   // fecha, para o proximo clique comecar limpo
}
prova('clicar abre o painel (era isso que nao acontecia)', abriu === botoes.length,
      abriu+' de '+botoes.length+' abriram');
prova('abre o painel DO PROPRIO frete, nao o de outro', certo === botoes.length,
      certo+' de '+botoes.length+' certos');

// Clicar de novo fecha.
pfnAbreMover(botoes[0]); pfnAbreMover(botoes[0]);
prova('clicar de novo fecha',
      [...doc.querySelectorAll('.mv')].every(e => e.hasAttribute('hidden')));

// E entre a linha e o painel ha mesmo outro bloco -- a razao do defeito.
const linha0 = botoes[0].closest('.fr');
prova('entre a linha e o painel existe outro bloco (a causa)',
      linha0.nextElementSibling && !linha0.nextElementSibling.classList.contains('mv'),
      'vizinho imediato: '+(linha0.nextElementSibling||{}).className);

// O destino novo esta na lista.
const ops = [...doc.querySelectorAll('.mv__d option')].map(o => o.textContent.trim());
prova('a lista de destinos oferece o caminhao de fora',
      ops.some(t => t === 'Terceiro'), 'opcoes: '+JSON.stringify(ops.slice(0,6)));

console.log(falhas ? '\n'+falhas+' FALHA(S)' : '\nTUDO OK');
process.exit(falhas ? 1 : 0);
