// Prova da busca e das pilulas de Clientes PIX, com DOM de verdade.
//
// Sao 264 cadastros: sem busca, achar alguem era rolar no olho. Renderizar o
// HTML nao prova filtro nenhum — todos os cards estao la, e o que muda e quem
// fica escondido depois do clique.
//
//   python prova_troco_pix_clientes.py --html clientes.html
//   npm install jsdom          (numa pasta qualquer, fora do projeto)
//   set NODE_PATH=<aquela pasta>\node_modules
//   node prova_troco_pix_clientes.js clientes.html
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

const partes = ['tpcFiltra\\(bt\\)', 'tpcCabe\\(c\\)', 'tpcAplica\\(\\)']
  .map(a => html.match(new RegExp('function ' + a + '\\{[\\s\\S]*?\\n\\}')));
prova('as funções do filtro estão no arquivo servido', partes.every(Boolean));
if (!partes.every(Boolean)) process.exit(1);

const ctx = new Function('document',
  'var tpcF = "";\n' + partes.map(m => m[0]).join('\n') +
  '\nreturn {filtra: tpcFiltra, aplica: tpcAplica};')(doc);

const cards = [...doc.querySelectorAll('#tpc .lista .c')];
const ativos = cards.filter(c => c.getAttribute('data-ativo') === '1');
const inativos = cards.filter(c => c.getAttribute('data-ativo') === '0');
const semUso = cards.filter(c => c.getAttribute('data-usos') === '0');
const repetidos = cards.filter(c => c.getAttribute('data-rep') === '1');
prova('a tela tem cadastros para provar', cards.length > 100,
      cards.length + ' cards');

function clica(f){
  const bt = doc.querySelector('#tpc .aba[data-f="' + f + '"]');
  if (!bt) return null;
  ctx.filtra(bt);
  return cards.filter(c => !c.hidden);
}

let v = clica('ativo');
prova('"Ativos" mostra só quem está ativo',
      v && v.length === ativos.length
        && v.every(c => c.getAttribute('data-ativo') === '1'),
      'apareceram ' + (v || []).length + ' de ' + ativos.length);

v = clica('off');
prova('"Inativos" mostra só os desativados',
      v && v.length === inativos.length
        && v.every(c => c.getAttribute('data-ativo') === '0'),
      'apareceram ' + (v || []).length + ' de ' + inativos.length);

v = clica('sem');
prova('"Nunca usados" mostra só quem não recebeu troco',
      v && v.length === semUso.length
        && v.every(c => c.getAttribute('data-usos') === '0'),
      'apareceram ' + (v || []).length + ' de ' + semUso.length);

v = clica('rep');
prova('"Nome repetido" mostra só os cadastros com nome igual a outro',
      v && v.length === repetidos.length
        && v.every(c => c.getAttribute('data-rep') === '1'),
      'apareceram ' + (v || []).length + ' de ' + repetidos.length);

v = clica('');
prova('"Todos" traz todo mundo de volta', v && v.length === cards.length,
      'apareceram ' + (v || []).length + ' de ' + cards.length);

// ── a busca: é ela que substitui a rolagem no olho ────────────────────────
const campo = doc.getElementById('tpc-busca');
const alvo = cards.find(c => (c.getAttribute('data-busca') || '').length > 20);
const nome = alvo.querySelector('.c__n').textContent.trim();
campo.value = nome.split(' ')[0].toLowerCase();
ctx.aplica();
let achados = cards.filter(c => !c.hidden);
prova('buscar pelo primeiro nome acha o cadastro', achados.includes(alvo),
      'procurei "' + nome.split(' ')[0] + '" e não achei ' + nome);
prova('e esconde quem não bate', achados.length < cards.length,
      'a busca não filtrou nada');

// buscar pela CHAVE também tem de achar — é o que se tem na mão quando o
// nome está escrito diferente
const comChave = cards.find(c => c.querySelector('.c__k')
  && /\d{6,}/.test(c.querySelector('.c__k').textContent));
const chave = comChave.querySelector('.c__k').textContent.trim();
campo.value = chave.slice(0, 8).toLowerCase();
ctx.aplica();
achados = cards.filter(c => !c.hidden);
prova('buscar pela chave PIX também acha', achados.includes(comChave),
      'procurei "' + chave.slice(0, 8) + '"');

// busca e pílula valem juntas
campo.value = '';
ctx.filtra(doc.querySelector('#tpc .aba[data-f="off"]'));
campo.value = inativos[0].querySelector('.c__n').textContent.trim().split(' ')[0].toLowerCase();
ctx.aplica();
achados = cards.filter(c => !c.hidden);
prova('busca e pílula valem ao mesmo tempo',
      achados.every(c => c.getAttribute('data-ativo') === '0'),
      'apareceu ativo dentro do filtro de inativos');
const conta = doc.getElementById('tpc-conta');
prova('a contagem do rodapé acompanha o que está na tela',
      (conta.textContent || '').indexOf(String(achados.length)) === 0,
      'rodapé: ' + conta.textContent + ' / visíveis: ' + achados.length);

console.log(falhas ? '\n' + falhas + ' FALHA(S)' : '\nTUDO OK');
process.exitCode = falhas ? 1 : 0;
