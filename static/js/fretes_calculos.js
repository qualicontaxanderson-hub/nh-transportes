// JS de cálculos para o formulário de frete.
// Implementa as regras de negócio:
// - Total NF = qtd * preco unitario
// - Valor Total Frete = qtd * preco por litro (se cliente paga frete)
// - Valor CTe = (CTE Integral ? Valor Total Frete : qtd * valor_rota(origem|destino))
// - Comissão Motorista = qtd * 0.01 (zera se cliente não paga ou motorista não recebe)
// - Comissão CTe = Valor CTe * 8% (sempre)
// - Lucro = Valor Total Frete - Comissão Motorista - Comissão CTe
// Atualiza hidden *_raw para submissão; não altera layout.

if (typeof desformatarMoeda !== 'function') {
  function desformatarMoeda(input) {
    if (input === null || input === undefined) return 0;
    var s = String(input).trim();
    if (s === '') return 0;
    s = s.replace(/[Rr]\$\s?/, '').trim();
    if (s.indexOf('.') >= 0 && s.indexOf(',') >= 0) {
      s = s.replace(/\./g, '').replace(',', '.');
    } else if (s.indexOf(',') >= 0) {
      s = s.replace(',', '.');
    }
    s = s.replace(/[^0-9\.-]/g, '');
    var n = parseFloat(s);
    return isNaN(n) ? 0 : n;
  }
}

if (typeof formatarMoedaBR !== 'function') {
  function formatarMoedaBR(valor, casas) {
    casas = (typeof casas === 'number') ? casas : 2;
    if (valor === null || valor === undefined) valor = 0;
    var n = Number(valor) || 0;
    var neg = n < 0;
    n = Math.abs(n);
    var inteiro = parseInt(n.toFixed(casas), 10) + '';
    var dec = (n.toFixed(casas) + '').split('.')[1] || '';
    inteiro = inteiro.replace(/\B(?=(\d{3})+(?!\d))/g, '.');
    var s = inteiro + (casas ? ',' + (dec) : '');
    return (neg ? '-' : '') + s;
  }
}

function $id(id) { return document.getElementById(id); }

// Constants for boolean value parsing
// Falsy values: empty, zero, false (English/Portuguese), no (English/Portuguese)
var FALSY_VALUES = ['', '0', 'false', 'nao', 'não', 'no'];

// Helper to parse boolean-like strings (handles True/False, 1/0, yes/no, sim/não, etc.)
// Returns true for any value not in FALSY_VALUES list
function parseBoolean(value) {
  if (typeof value === 'undefined' || value === null) return false;
  var s = String(value).trim().toLowerCase();
  return FALSY_VALUES.indexOf(s) === -1;
}

function parseNumberFromField(el) {
  if (!el) return 0;
  var raw = el.value || '';
  raw = String(raw).replace(/[Rr]\$\s?/g, '').trim();
  return desformatarMoeda(raw);
}

function readQuantidade() {
  var manual = $id('quantidade_manual');
  if (manual && String(manual.value).trim() !== '') {
    var s = String(manual.value).trim();
    // "9.975" => 9975 when no comma present
    if (s.indexOf('.') >= 0 && s.indexOf(',') === -1) {
      var cleaned = s.replace(/\./g, '');
      var v = parseInt(cleaned, 10);
      return isNaN(v) ? NaN : v;
    }
    if (/^\d+$/.test(s)) {
      return parseInt(s, 10);
    }
    var n = desformatarMoeda(s);
    if (isNaN(n)) return NaN;
    return Math.round(n);
  }
  var sel = $id('quantidade_id');
  if (!sel) return NaN;
  var opt = sel.options[sel.selectedIndex];
  if (!opt) return NaN;
  var q = opt.getAttribute('data-quantidade') || opt.getAttribute('data-quantidade-litros') || opt.getAttribute('data-quantidade_litros');
  if (q === null || q === undefined) return NaN;
  // aceitar vírgula como decimal
  q = String(q).replace(',', '.');
  var num = parseFloat(q);
  return isNaN(num) ? NaN : num;
}

function readPrecoProdutoUnitario() {
  var rawHidden = $id('preco_produto_unitario_raw');
  if (rawHidden && rawHidden.value !== undefined && rawHidden.value !== '') {
    var v = parseFloat(rawHidden.value);
    if (!isNaN(v)) return v;
  }
  return parseNumberFromField($id('preco_produto_unitario')) || 0;
}

function readPrecoPorLitroRaw() {
  var rawHidden = $id('preco_por_litro_raw');
  if (rawHidden && rawHidden.value !== undefined && rawHidden.value !== '') {
    var v = parseFloat(rawHidden.value);
    if (!isNaN(v)) return v;
  }
  return parseNumberFromField($id('preco_por_litro')) || 0;
}

// Helper function to read destino value (prefers hidden field over disabled select)
function readDestinoId() {
  var hidden = $id('destino_id_hidden');
  if (hidden && hidden.value) return hidden.value;
  var visible = $id('destino_id');
  if (visible && visible.value) return visible.value;
  return null;
}

function calcularValorCTeViaRotas(quantidade) {
  var origem = $id('origem_id') ? $id('origem_id').value : null;
  var destino = readDestinoId();
  
  console.log('[DEBUG CTe] origem:', origem, 'destino:', destino, 'quantidade:', quantidade);
  console.log('[DEBUG CTe] ROTAS:', typeof ROTAS !== 'undefined' ? ROTAS : 'undefined');
  
  if (!origem || !destino) {
    console.log('[DEBUG CTe] Missing origem or destino, returning 0');
    return 0;
  }
  
  var key = origem + '|' + destino;
  console.log('[DEBUG CTe] Key:', key);
  
  try {
    if (typeof ROTAS !== 'undefined' && ROTAS && ROTAS[key]) {
      var result = Number(ROTAS[key]) * Number(quantidade || 0);
      console.log('[DEBUG CTe] Found route in ROTAS[' + key + '] =', ROTAS[key], 'result:', result);
      return result;
    }
    // try numeric-key fallback
    var keys = [origem + '|' + destino, parseInt(origem,10) + '|' + parseInt(destino,10)];
    for (var i = 0; i < keys.length; i++) {
      if (ROTAS[keys[i]]) {
        var result = Number(ROTAS[keys[i]]) * Number(quantidade || 0);
        console.log('[DEBUG CTe] Found route in ROTAS[' + keys[i] + '] =', ROTAS[keys[i]], 'result:', result);
        return result;
      }
    }
    console.log('[DEBUG CTe] No route found in ROTAS for any key variant');
  } catch (e) { 
    console.error('[DEBUG CTe] Error:', e); 
  }
  return 0;
}

function ensureHidden(name) {
  if ($id(name)) return;
  var h = document.createElement('input');
  h.type = 'hidden';
  h.id = name;
  h.name = name;
  var form = document.querySelector('form');
  if (form) form.appendChild(h);
}

function calcularTudo() {
  ensureHidden('preco_produto_unitario_raw');
  ensureHidden('preco_por_litro_raw');

  ensureHidden('total_nf_compra_raw');
  ensureHidden('valor_total_frete_raw');
  ensureHidden('valor_cte_raw');
  ensureHidden('comissao_cte_raw');
  ensureHidden('lucro_raw');
  ensureHidden('comissao_motorista_raw');

  var quantidade = readQuantidade();
  if (isNaN(quantidade) || quantidade <= 0) quantidade = NaN;

  var precoUnit = readPrecoProdutoUnitario();
  var precoPorLitro = readPrecoPorLitroRaw();

  // Total NF
  var totalNF = 0;
  if (!isNaN(quantidade)) totalNF = precoUnit * quantidade;
  else totalNF = precoUnit;

  // Valor Total Frete (faturado ao cliente)
  var valorTotalFrete = 0;
  if (!isNaN(quantidade)) valorTotalFrete = precoPorLitro * quantidade;
  else valorTotalFrete = precoPorLitro;

  // client flags from fretes_fixes.js
  var clientePaga = !!window.__CLIENTE_PAGA_FRETE;
  var cteIntegral = !!window.__CLIENTE_CTE_INTEGRAL;

  // if client doesn't pay frete, faturamento é zero
  if (!clientePaga) {
    valorTotalFrete = 0;
  }

  // Valor CTe
  var valorCTe = 0;
  console.log('[DEBUG] cteIntegral:', cteIntegral, 'clientePaga:', clientePaga);
  if (cteIntegral) {
    // CTE integral = valorTotalFrete (which may be 0 if client doesn't pay)
    valorCTe = valorTotalFrete;
    console.log('[DEBUG] CTe Integral mode: valorCTe = valorTotalFrete =', valorCTe);
  } else {
    // rota-based, independent of client pay flag (operational value)
    valorCTe = calcularValorCTeViaRotas(quantidade) || 0;
    console.log('[DEBUG] CTe Normal mode: valorCTe =', valorCTe);
  }

  // Comissão Motorista (sempre calculada pela regra)
  var comissaoMotorista = 0;

  // verificar se motorista recebe comissão (motorista option data-paga-comissao)
  var motoristaSel = $id('motoristas_id');
  var motoristaRecebeComissao = true;
  if (motoristaSel) {
    var mOpt = motoristaSel.options[motoristaSel.selectedIndex];
    if (mOpt) {
      var pagaAttr = mOpt.getAttribute('data-paga-comissao');
      motoristaRecebeComissao = parseBoolean(pagaAttr);
      // Fallback: check percentual attribute if paga-comissao not set
      if (typeof pagaAttr === 'undefined' || pagaAttr === null) {
        var mPercentAttr = mOpt.getAttribute('data-percentual') || mOpt.getAttribute('data-percentual-comissao') || mOpt.getAttribute('data-percentual_comissao');
        if (typeof mPercentAttr !== 'undefined' && mPercentAttr !== null && String(mPercentAttr).trim() !== '') {
          var p = parseFloat(String(mPercentAttr).replace(',', '.'));
          motoristaRecebeComissao = !isNaN(p) && p > 0;
        }
      }
    }
  }

  if (clientePaga && motoristaRecebeComissao && !isNaN(quantidade)) {
    comissaoMotorista = quantidade * 0.01;
  } else {
    comissaoMotorista = 0;
  }

  // Comissão CTe = 8% do valorCTe (sempre)
  var comissaoCte = 0;
  comissaoCte = 0.08 * Number(valorCTe || 0);
  console.log('[DEBUG] Comissão CTe = 8% of', valorCTe, '=', comissaoCte);

  // Lucro
  var lucro = 0;
  if (!clientePaga) {
    // Business rule: when client doesn't pay frete, lucro displayed must be 0.00
    lucro = 0;
  } else {
    lucro = valorTotalFrete - comissaoMotorista - comissaoCte;
  }

  // Update visual fields
  var elTotalNF = $id('total_nf_compra');
  var elValorFrete = $id('valor_total_frete');
  var elValorCTe = $id('valor_cte');
  var elComissaoMotorista = $id('comissao_motorista');
  var elComissaoCte = $id('comissao_cte');
  var elLucro = $id('lucro');

  if (elTotalNF) elTotalNF.value = 'R$ ' + formatarMoedaBR(totalNF, 2);
  if (elValorFrete) elValorFrete.value = 'R$ ' + formatarMoedaBR(valorTotalFrete, 2);
  if (elValorCTe) elValorCTe.value = 'R$ ' + formatarMoedaBR(valorCTe, 2);
  if (elComissaoMotorista) elComissaoMotorista.value = 'R$ ' + formatarMoedaBR(comissaoMotorista, 2);
  if (elComissaoCte) elComissaoCte.value = 'R$ ' + formatarMoedaBR(comissaoCte, 2);
  if (elLucro) elLucro.value = 'R$ ' + formatarMoedaBR(lucro, 2);

  // Update hidden raws
  var hPrecoUnit = $id('preco_produto_unitario_raw');
  var hPrecoLitro = $id('preco_por_litro_raw');
  var hTotalNF = $id('total_nf_compra_raw');
  var hValorFrete = $id('valor_total_frete_raw');
  var hValorCTe = $id('valor_cte_raw');
  var hComissaoCte = $id('comissao_cte_raw');
  var hLucro = $id('lucro_raw');
  var hComissaoMotorista = $id('comissao_motorista_raw') || $id('comissao_motorista');

  if (hPrecoUnit) hPrecoUnit.value = (precoUnit || 0);
  if (hPrecoLitro) hPrecoLitro.value = (precoPorLitro || 0);
  if (hTotalNF) hTotalNF.value = (Math.round((totalNF + Number.EPSILON) * 100) / 100);
  if (hValorFrete) hValorFrete.value = (Math.round((valorTotalFrete + Number.EPSILON) * 100) / 100);
  if (hValorCTe) hValorCTe.value = (Math.round((valorCTe + Number.EPSILON) * 100) / 100);
  if (hComissaoCte) hComissaoCte.value = (Math.round((comissaoCte + Number.EPSILON) * 100) / 100);
  if (hLucro) hLucro.value = (Math.round((lucro + Number.EPSILON) * 100) / 100);
  if (hComissaoMotorista) hComissaoMotorista.value = (Math.round((comissaoMotorista + Number.EPSILON) * 100) / 100);
}

// Expose calcularTudo and utility functions globally
window.calcularTudo = calcularTudo;
window.parseBoolean = parseBoolean;
