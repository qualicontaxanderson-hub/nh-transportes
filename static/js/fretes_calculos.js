// JS de cálculos para o formulário de frete.
// Depende de ROTAS (objeto origem|destino -> valor_por_litro) definido no template.

function $id(id){ return document.getElementById(id); }

function parseNumberFromField(el, casasDefault) {
  if (!el) return 0;
  var raw = el.value || '';
  // remove R$ e espaços
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
  if (rawHidden && rawHidden.value) {
    var v = parseFloat(rawHidden.value);
    if (!isNaN(v)) return v;
  }
  return parseNumberFromField($id('preco_produto_unitario')) || 0;
}

function readPrecoPorLitroRaw() {
  var rawHidden = $id('preco_por_litro_raw');
  if (rawHidden && rawHidden.value) {
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
  ensureHidden('preco_produto_unitario_raw');
  ensureHidden('preco_por_litro_raw');

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

  // comissao CTe: se cliente tem percentual global (window.__CLIENTE_PERCENTUAL_CTE), usa sobre valorCTe ou valorTotalFrete conforme regra.
  var percentualCte = window.__CLIENTE_PERCENTUAL_CTE || 0;
  var comissaoCte = 0;
  if (percentualCte && percentualCte > 0) {
    // regra: percentual sobre o valor do CTe ou sobre valorTotalFrete -> escolher acorde ao seu negócio; aqui usamos sobre valorCTe
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
  // caso cliente não pague, manter regra negativa conforme backend
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

  // Atualizar hidden raws para envio
  var hPrecoUnit = $id('preco_produto_unitario_raw');
  var hPrecoLitro = $id('preco_por_litro_raw');
  var hTotalNF = $id('total_nf_compra');
  var hValorFrete = $id('valor_total_frete');
  var hValorCTe = $id('valor_cte');
  var hComissaoCte = $id('comissao_cte');
  var hLucro = $id('lucro');

  if (hPrecoUnit) hPrecoUnit.value = (precoUnit || 0);
  if (hPrecoLitro) hPrecoLitro.value = (precoPorLitro || 0);
  // note: total_nf_compra and others are visible formatted; if you want hidden numeric fields add them similarly
}
