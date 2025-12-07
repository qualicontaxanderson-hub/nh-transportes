// JS de cálculos para o formulário de frete.
// Depende de ROTAS (objeto origem|destino -> valor_por_litro) definido no template.

// Fallbacks mínimos caso fretes_fixes.js não carregue
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

function $id(id){ return document.getElementById(id); }

function parseNumberFromField(el) {
  if (!el) return 0;
  var raw = el.value || '';
  raw = String(raw).replace(/[Rr]\$\s?/g, '').trim();
  return desformatarMoeda(raw);
}

function readQuantidade() {
  var manual = $id('quantidade_manual');
  if (manual && manual.value.trim() !== '') {
    return parseNumberFromField(manual) || NaN;
  }
  var sel = $id('quantidade_id');
  if (!sel) return NaN;
  var opt = sel.options[sel.selectedIndex];
  if (!opt) return NaN;
  var q = opt.getAttribute('data-quantidade');
  return parseFloat(q) || NaN;
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

function calcularValorCTe(quantidade) {
  var origem = $id('origem_id') ? $id('origem_id').value : null;
  var destino = ($id('destino_id') && $id('destino_id').value) ? $id('destino_id').value : null;
  if (!origem || !destino) return 0;
  var key = origem + '|' + destino;
  try {
    if (typeof ROTAS !== 'undefined' && ROTAS && ROTAS[key]) return Number(ROTAS[key]) * Number(quantidade || 0);
    // tentar conversões de tipo
    var keys = [origem + '|' + destino, parseInt(origem,10) + '|' + parseInt(destino,10)];
    for (var i=0;i<keys.length;i++){
      if (ROTAS[keys[i]]) return Number(ROTAS[keys[i]]) * Number(quantidade || 0);
    }
  } catch(e){ console.error(e); }
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

// Função principal que recalcula todos os resultados e atualiza o DOM
function calcularTudo() {
  // garantir hidden raw para preços
  ensureHidden('preco_produto_unitario_raw');
  ensureHidden('preco_por_litro_raw');

  // garantir hidden numerics para totais (envio)
  ensureHidden('total_nf_compra_raw');
  ensureHidden('valor_total_frete_raw');
  ensureHidden('valor_cte_raw');
  ensureHidden('comissao_cte_raw');
  ensureHidden('lucro_raw');

  var quantidade = readQuantidade();
  if (isNaN(quantidade) || quantidade <= 0) quantidade = NaN;

  var precoUnit = readPrecoProdutoUnitario();
  var precoPorLitro = readPrecoPorLitroRaw();

  // total NF = quantidade * precoUnit (se existir quantidade), senão apenas precoUnit
  var totalNF = 0;
  if (!isNaN(quantidade)) totalNF = precoUnit * quantidade;
  else totalNF = precoUnit;

  // valor total frete = quantidade * precoPorLitro
  var valorTotalFrete = 0;
  if (!isNaN(quantidade)) valorTotalFrete = precoPorLitro * quantidade;
  else valorTotalFrete = precoPorLitro;

  // valor CTe via rotas
  var valorCTe = calcularValorCTe(quantidade) || 0;

  // comissao motorista - se houver valor manual, usar; caso contrário usar default 0
  var comissaoMotoristaField = $id('comissao_motorista');
  var comissaoMotorista = 0;
  if (comissaoMotoristaField && comissaoMotoristaField.value) comissaoMotorista = desformatarMoeda(comissaoMotoristaField.value);

  // comissao CTe: percentual cliente
  var percentualCte = window.__CLIENTE_PERCENTUAL_CTE || 0;
  var comissaoCte = 0;
  if (percentualCte && percentualCte > 0) {
    comissaoCte = (percentualCte / 100.0) * valorCTe;
  }

  // regra cliente paga frete?
  var clientePaga = !!window.__CLIENTE_PAGA_FRETE;
  if (!clientePaga) {
    precoPorLitro = 0;
    valorTotalFrete = 0;
    comissaoMotorista = 0;
    comissaoCte = 0;
  }

  // lucro = valorTotalFrete - totalNF - comissaoMotorista - comissaoCte - valorCTe
  var lucro = valorTotalFrete - totalNF - comissaoMotorista - comissaoCte - valorCTe;
  if (!clientePaga) {
    lucro = 0 - (comissaoCte + comissaoMotorista);
  }

  // Atualizar campos visuais (formatados)
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

  // Atualizar hidden raws para envio (numeros puros)
  var hPrecoUnit = $id('preco_produto_unitario_raw');
  var hPrecoLitro = $id('preco_por_litro_raw');
  var hTotalNF = $id('total_nf_compra_raw');
  var hValorFrete = $id('valor_total_frete_raw');
  var hValorCTe = $id('valor_cte_raw');
  var hComissaoCte = $id('comissao_cte_raw');
  var hLucro = $id('lucro_raw');

  if (hPrecoUnit) hPrecoUnit.value = (precoUnit || 0);
  if (hPrecoLitro) hPrecoLitro.value = (precoPorLitro || 0);
  if (hTotalNF) hTotalNF.value = (Math.round((totalNF + Number.EPSILON) * 100) / 100);
  if (hValorFrete) hValorFrete.value = (Math.round((valorTotalFrete + Number.EPSILON) * 100) / 100);
  if (hValorCTe) hValorCTe.value = (Math.round((valorCTe + Number.EPSILON) * 100) / 100);
  if (hComissaoCte) hComissaoCte.value = (Math.round((comissaoCte + Number.EPSILON) * 100) / 100);
  if (hLucro) hLucro.value = (Math.round((lucro + Number.EPSILON) * 100) / 100);
}
