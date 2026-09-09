// Prova das pilulas do Troco PIX com DOM de verdade: com troco, sem troco,
// conciliadas, nao conciliadas.
//
// Renderizar o HTML nao prova filtro: os cards estao todos la, e o que muda e
// quem fica escondido depois do clique. Aqui a funcao provada e a que o
// arquivo servido carrega, extraida do <script> inline.
//
//   python prova_troco_pix_layout.py --html pix.html
//   npm install jsdom          (numa pasta qualquer, fora do projeto)
//   set NODE_PATH=<aquela pasta>\node_modules
//   node prova_troco_pix_pilulas.js pix.html
//
const fs = require('fs');
const { JSDOM } = require('jsdom');
const html = fs.readFileSync(process.argv[2], 'utf8');
const doc = new JSDOM(html).window.document;

let falhas = 0;
function prova(t, ok, d){
  console.log((ok ? 'OK    ' : 'FALHA ') + t);
  if (!ok) { if (d) console.log('        ' + d); falhas++; }
}

// as tres funcoes do filtro vem juntas: tpxFiltra chama tpxAplica, que chama
// tpxCabe
const partes = ['tpxFiltra\\(bt\\)', 'tpxCabe\\(c\\)', 'tpxAplica\\(\\)']
  .map(a => html.match(new RegExp('function ' + a + '\\{[\\s\\S]*?\\n\\}')));
prova('as funcoes do filtro estao no arquivo servido', partes.every(Boolean));
if (!partes.every(Boolean)) { process.exit(1); }

const ctx = new Function('document',
  'var tpxF = "";\n' + partes.map(m => m[0]).join('\n') +
  '\nreturn {filtra: tpxFiltra, aplica: tpxAplica};')(doc);

const cards = [...doc.querySelectorAll('#tpx .lista .c')];
const comTroco = cards.filter(c => c.getAttribute('data-troco') === '1');
const semTroco = cards.filter(c => c.getAttribute('data-troco') === '0');
const conciliadas = comTroco.filter(c => c.getAttribute('data-conc') === '1');
prova('a tela tem cards com e sem troco para provar',
      comTroco.length > 0 && semTroco.length > 0,
      comTroco.length + ' com troco, ' + semTroco.length + ' sem');

function clica(f){
  const bt = doc.querySelector('#tpx .aba[data-f="' + f + '"]');
  if (!bt) return null;
  ctx.filtra(bt);
  return cards.filter(c => !c.hidden);
}

let v = clica('com');
prova('"Com troco" mostra so quem tem troco',
      v && v.length === comTroco.length && v.every(c => c.getAttribute('data-troco') === '1'),
      'apareceram ' + (v || []).length + ' de ' + comTroco.length);

v = clica('sem');
prova('"Sem troco" mostra so quem nao tem',
      v && v.length === semTroco.length && v.every(c => c.getAttribute('data-troco') === '0'),
      'apareceram ' + (v || []).length + ' de ' + semTroco.length);

v = clica('conc');
prova('"Conciliadas" mostra so quem tem troco E esta conciliado',
      v && v.length === conciliadas.length
        && v.every(c => c.getAttribute('data-conc') === '1'),
      'apareceram ' + (v || []).length + ' de ' + conciliadas.length);

v = clica('nconc');
prova('"Não conciliadas" nao arrasta as sem troco',
      v && v.every(c => c.getAttribute('data-troco') === '1'
                     && c.getAttribute('data-conc') === '0')
        && v.length === comTroco.length - conciliadas.length,
      'apareceram ' + (v || []).length + ' de ' +
      (comTroco.length - conciliadas.length));

v = clica('');
prova('"Todas" traz todo mundo de volta', v && v.length === cards.length,
      'apareceram ' + (v || []).length + ' de ' + cards.length);

// busca e pilula andam juntas
const campo = doc.getElementById('tpx-busca');
const alvo = semTroco[0].getAttribute('data-busca').split(' ')[0];
campo.value = alvo;
ctx.filtra(doc.querySelector('#tpx .aba[data-f="com"]'));
const visiveis = cards.filter(c => !c.hidden);
prova('busca e pilula valem ao mesmo tempo',
      visiveis.every(c => c.getAttribute('data-troco') === '1'
        && (c.getAttribute('data-busca') || '').includes(alvo)),
      'apareceu card que nao atende as duas');
const conta = doc.getElementById('tpx-conta');
prova('a contagem do rodape acompanha o que esta na tela',
      (conta.textContent || '').indexOf(String(visiveis.length)) === 0,
      'rodape: ' + conta.textContent + ' / visiveis: ' + visiveis.length);

console.log(falhas ? '\n' + falhas + ' FALHA(S)' : '\nTUDO OK');
process.exitCode = falhas ? 1 : 0;
