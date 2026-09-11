// Prova do layout de tela grande aprovado: Pista A (grade de cartoes) e
// Lancamento A (duas colunas mais a conta parada a direita).
//
// O que se prova aqui e o que o HTML entrega: a coluna lateral existe, o JS
// da tela alimenta cada numero dela, e o celular nao foi tocado — todas as
// regras novas vivem dentro de @media (min-width:992px).
//
//   python prova_troco_pix_pista.py --html pista.html
//   python prova_troco_pix_novo.py  --html novo.html
//   npm install jsdom          (numa pasta qualquer, fora do projeto)
//   set NODE_PATH=<aquela pasta>\node_modules
//   node prova_troco_pix_web.js pista.html novo.html
//
const fs = require('fs');
const { JSDOM } = require('jsdom');

let falhas = 0;
function prova(t, ok, d){
  console.log((ok ? 'OK    ' : 'FALHA ') + t);
  if (!ok) { if (d) console.log('        ' + d); falhas++; }
}

// ── Pista A: a lista vira grade, e so na tela grande ──────────────────────
const pista = fs.readFileSync(process.argv[2], 'utf8');
const mediaPista = pista.match(/@media \(min-width:992px\)\{([\s\S]*?)\n  \}/);
prova('a Pista tem um bloco só para a tela grande', !!mediaPista);
if (mediaPista) {
  const css = mediaPista[1];
  prova('a lista vira grade de cartões',
        /#tpp \.lista\{[^}]*display:grid/.test(css)
        && /grid-template-columns:repeat\(auto-fill/.test(css),
        'não achei a grade');
  prova('os cartões se fecham com borda e sombra',
        /#tpp \.c\{[^}]*border:1px solid var\(--borda\)/.test(css));
  prova('o valor do troco ganha corpo no cartão',
        /#tpp \.val__v\{[^}]*font-size:1\.3rem/.test(css));
  prova('o botão de lançar deixa de ter a largura do monitor',
        /#tpp \.novo\{[^}]*max-width/.test(css));
}
// o que vale para todo tamanho nao pode ter virado desktop-only
const pistaDoc = new JSDOM(pista).window.document;
prova('o HTML da Pista continua o mesmo (nenhum wrapper novo)',
      pistaDoc.querySelectorAll('#tpp .lista > .c').length > 0
      && pistaDoc.querySelectorAll('#tpp .colunas').length === 0,
      'apareceu estrutura nova na Pista — a mudança era só de CSS');

// ── Lancamento A: duas colunas + a conta parada ───────────────────────────
const novo = fs.readFileSync(process.argv[3], 'utf8');
const doc = new JSDOM(novo).window.document;

prova('o formulário está dividido em colunas',
      doc.querySelectorAll('#tpn .colunas > .col').length === 2,
      doc.querySelectorAll('#tpn .colunas > .col').length + ' colunas');
const blocos = [...doc.querySelectorAll('#tpn .col .bloco')];
prova('os seis blocos continuam no formulário', blocos.length === 6,
      blocos.length + ' blocos');
// no celular a ordem tem de ser a de hoje: onde/quando, cheque, venda, troco,
// quem recebe, quem atendeu
const ordem = blocos.map(b => (b.querySelector('.bloco__t') || {}).textContent || '')
                    .map(t => t.trim().toLowerCase());
prova('e na ordem de sempre, que é a que o celular mostra',
      /onde e quando/.test(ordem[0]) && /cheque/.test(ordem[1])
      && /comprou/.test(ordem[2]) && /troco volta/.test(ordem[3])
      && /recebe/.test(ordem[4]) && /atendeu/.test(ordem[5]),
      JSON.stringify(ordem));

const lado = doc.querySelector('#tpn .lado');
prova('existe a coluna da conta', !!lado);
if (lado) {
  prova('ela mostra o troco por PIX em destaque', !!lado.querySelector('#tpn-lado-v'));
  prova('abre a conta parcela por parcela',
        ['tpn-l-cheque', 'tpn-l-venda', 'tpn-l-din', 'tpn-l-cred']
          .every(id => !!lado.querySelector('#' + id)));
  prova('traz quem recebe, para conferir a chave sem procurar',
        !!lado.querySelector('#tpn-lado-k'));
  prova('e o botão de lançar mora nela',
        !!lado.querySelector('button[type="submit"]'));
}

// ── o JS alimenta a coluna: a conta certa, não um número parado ───────────
const fns = ['tpnFmt\\(v\\)', 'tpnCru\\(txt\\)', 'tpnTexto\\(id, txt\\)',
             'tpnValor\\(id\\)', 'tpnConta\\(\\)']
  .map(a => novo.match(new RegExp('function ' + a + '\\{[\\s\\S]*?\\n\\}')));
prova('as funções da conta estão no arquivo servido', fns.every(Boolean));
if (fns.every(Boolean)) {
  const ctx = new Function('document',
    fns.map(m => m[0]).join('\n') + '\nreturn tpnConta;')(doc);

  function poe(id, v){
    const e = doc.getElementById(id);
    e.setAttribute('data-raw-value', String(v));
  }
  // cheque 1.805,49 − venda 805,51 − 0 − 0  =  999,98 (o caso do print)
  poe('cheque_valor', 1805.49);
  poe('venda_abastecimento', 805.51);
  poe('venda_arla', 0);
  poe('venda_produtos', 0);
  poe('troco_especie', 0);
  poe('troco_credito_vda_programada', 0);
  const pix = ctx();
  prova('a conta dá o mesmo troco do lançamento real (R$ 999,98)',
        Math.abs(pix - 999.98) < 0.005, 'deu ' + pix);
  prova('a coluna mostra esse valor',
        doc.getElementById('tpn-lado-v').textContent === 'R$ 999,98',
        'mostrou ' + doc.getElementById('tpn-lado-v').textContent);
  prova('e as parcelas da conta, com o sinal certo',
        doc.getElementById('tpn-l-cheque').textContent === 'R$ 1.805,49'
        && doc.getElementById('tpn-l-venda').textContent === '− R$ 805,51',
        doc.getElementById('tpn-l-cheque').textContent + ' / ' +
        doc.getElementById('tpn-l-venda').textContent);

  // troco negativo: a coluna avisa junto com o resto da tela
  poe('venda_abastecimento', 5000);
  ctx();
  prova('troco negativo pinta a coluna de vermelho e explica',
        doc.getElementById('tpn-lado-cx').className.indexOf('ruim') >= 0
        && /não cobre/.test(doc.getElementById('tpn-lado-c').textContent),
        'classe: ' + doc.getElementById('tpn-lado-cx').className);
}

// ── o celular não foi tocado ──────────────────────────────────────────────
const forasDaMedia = novo
  .replace(/@media \(min-width:992px\)\{[\s\S]*?\n  \}/g, '')
  .match(/#tpn \.(lado__bt|colunas|lc)\{/g);
prova('nenhuma regra da tela grande escapou para fora do @media',
      !forasDaMedia, 'escaparam: ' + forasDaMedia);
prova('a coluna da conta nasce escondida (é o celular que manda no padrão)',
      /#tpn \.lado\{ display:none; \}/.test(novo));
prova('no celular o rodapé fixo continua sendo o que mostra o troco',
      /#tpn \.rodape\{ position:fixed/.test(novo));

console.log(falhas ? '\n' + falhas + ' FALHA(S)' : '\nTUDO OK');
process.exitCode = falhas ? 1 : 0;
