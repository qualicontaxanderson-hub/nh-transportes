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
// pfnAbreMover chama pfnMvDestino ao abrir, entao as duas vem juntas.
const mDest = html.match(/function pfnMvDestino\(sel\)\{[\s\S]*?\n\}/);
const pfnAbreMover = new Function('document',
    m[0] + '\n' + (mDest ? mDest[0] : 'function pfnMvDestino(){}') +
    '; return pfnAbreMover;')(doc);

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

// ── quem levou: so aparece quando o destino e o caminhao de fora ───────────
const fn2 = html.match(/function pfnMvDestino\(sel\)\{[\s\S]*?\n\}/);
prova('pfnMvDestino existe no arquivo servido', !!fn2);
if (fn2) {
  const pfnMvDestino = new Function('document', fn2[0] + '; return pfnMvDestino;')(doc);
  const cx = doc.querySelector('.mv');
  const dest = cx.querySelector('.mv__d'), quem = cx.querySelector('.mv__q');
  prova('o painel tem o campo de quem levou', !!quem);
  if (quem) {
    const idExt = dest.getAttribute('data-terceiro');
    const nosso = [...dest.options].find(o => !o.value.startsWith(idExt + ':'));
    dest.value = nosso.value; pfnMvDestino(dest);
    prova('caminhao nosso nao pergunta quem levou', quem.hidden,
          'destino: ' + nosso.textContent);
    const fora = [...dest.options].find(o => o.value.startsWith(idExt + ':'));
    dest.value = fora.value; pfnMvDestino(dest);
    prova('caminhao de fora pergunta quem levou', !quem.hidden,
          'destino: ' + fora.textContent);
    prova('a pergunta comeca sem resposta escolhida', quem.value === '');
  }
}

// ── mover sem escolher quem levou nao chega a sair da tela ─────────────────
const fn3 = html.match(/function pfnMover\(botao, freteId\)\{[\s\S]*?\n\}/);
if (fn3) {
  const avisos = [], enviados = [];
  const pfnMover = new Function('document', 'alert', 'pfnEnvia',
      fn3[0] + '; return pfnMover;')(doc, m => avisos.push(m),
      (b, url, dados) => enviados.push(dados));
  const cx = doc.querySelector('.mv');
  const dest = cx.querySelector('.mv__d'), quem = cx.querySelector('.mv__q');
  const idExt = dest.getAttribute('data-terceiro');
  dest.value = [...dest.options].find(o => o.value.startsWith(idExt + ':')).value;
  quem.hidden = false; quem.value = '';
  pfnMover(cx.querySelector('.bd__b--sim'), 999);
  prova('sem escolher quem levou, avisa e nao envia',
        enviados.length === 0 && avisos.length === 1,
        'avisos: ' + JSON.stringify(avisos));
  const t = [...quem.options].find(o => o.value);
  quem.value = t.value;
  pfnMover(cx.querySelector('.bd__b--sim'), 999);
  prova('com a transportadora escolhida, e ela que vai no motorista',
        enviados.length === 1 && String(enviados[0].motorista_id) === t.value,
        'enviado: ' + JSON.stringify(enviados));
}

// ── o painel da carga inteira, no cartao ───────────────────────────────────
const fnCarga = html.match(/function pfnAbreMoverCarga\(botao\)\{[\s\S]*?\n\}/);
prova('pfnAbreMoverCarga existe no arquivo servido', !!fnCarga);
if (fnCarga && mDest) {
  const abreCarga = new Function('document',
      fnCarga[0] + '\n' + mDest[0] + '; return pfnAbreMoverCarga;')(doc);
  const bt = [...doc.querySelectorAll('.bd__b')].find(
      b => /Mudar dia ou caminh/.test(b.textContent));
  prova('o cartao da carga tem o botao de mudar dia', !!bt);
  if (bt) {
    const painel = doc.querySelector('.mvc');
    prova('o painel da carga comeca escondido', painel.hasAttribute('hidden'));
    abreCarga(bt);
    prova('o botao abre o painel da carga', !painel.hidden);
    prova('o painel da carga tem data e caminhao',
          !!painel.querySelector('.mv__dt') && !!painel.querySelector('.mv__d'));
    prova('a data ja vem preenchida com o dia da carga',
          /^\d{4}-\d{2}-\d{2}$/.test(painel.querySelector('.mv__dt').value),
          'valor: ' + painel.querySelector('.mv__dt').value);
    prova('o caminhao da propria carga vem escolhido',
          !!painel.querySelector('.mv__d option[selected]'));
  }
}

// ── trocar a data recarrega a lista daquele dia ────────────────────────────
const fnData = html.match(/function pfnMvData\(inp\)\{[\s\S]*?\n\}/);
prova('pfnMvData existe no arquivo servido', !!fnData);
if (fnData && mDest) {
  let pedido = null;
  const fakeFetch = (url) => {
    pedido = url;
    return Promise.resolve({ json: () => Promise.resolve({
      ok: true, data: '2026-12-25', terceiro_id: 5,
      destinos: [{v: 9, m: 3, label: 'R900'}, {v: 5, m: 0, label: 'Terceiro'}]
    })});
  };
  const pfnMvData = new Function('document', 'fetch', 'alert',
      fnData[0] + '\n' + mDest[0] + '; return pfnMvData;')(doc, fakeFetch, () => {});
  const painel = doc.querySelector('.mv');
  const dt = painel.querySelector('.mv__dt'), sel = painel.querySelector('.mv__d');
  dt.value = '2026-12-25';
  pfnMvData(dt);
  // o preenchimento e assincrono: espera a volta do fetch antes de conferir
  return new Promise(r => setTimeout(r, 0)).then(() => {
    prova('a troca de data pergunta pelos caminhoes DAQUELE dia',
          /\/ped-frete-novo\/destinos\?data=2026-12-25/.test(pedido || ''),
          'pediu: ' + pedido);
    const labels = [...sel.options].map(o => o.textContent);
    prova('a lista de caminhoes vira a do dia novo',
          labels.join(',') === 'R900,Terceiro', 'ficou: ' + labels.join(','));
    fim();
  });
}

fim();
function fim(){
console.log(falhas ? '\n'+falhas+' FALHA(S)' : '\nTUDO OK');
process.exitCode = falhas ? 1 : 0;
}
