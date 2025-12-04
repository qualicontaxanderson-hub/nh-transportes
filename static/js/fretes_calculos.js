// static/js/fretes_calculos.js
// Atualizado: aplica regra "cliente não paga frete" na página Novo/Editar
(function () {
  'use strict';

  function $id(id) { return document.getElementById(id); }

  function parseNumber(value) {
    if (value === null || value === undefined) return NaN;
    if (typeof value === 'number') return value;
    var s = String(value).trim();
    if (s === '') return NaN;
    s = s.replace(/R\$\s*/gi, '').replace(/\s+/g, '');
    s = s.replace(/[^\d\.,-]/g, '');
    var lastComma = s.lastIndexOf(',');
    var lastDot = s.lastIndexOf('.');
    if (lastComma > -1 && lastDot > -1) {
      if (lastComma > lastDot) {
        s = s.replace(/\./g, '').replace(',', '.');
      } else {
        s = s.replace(/,/g, '');
      }
    } else if (lastComma > -1 && lastDot === -1) {
      s = s.replace(/\./g, '').replace(',', '.');
    } else {
      s = s.replace(/,/g, '');
    }
    var n = parseFloat(s);
    return isNaN(n) ? NaN : n;
  }

  function formatCurrencyBR(value, decimals) {
    if (value === null || value === undefined || isNaN(value)) {
      return 'R$ ' + (decimals ? ('0,' + '0'.repeat(decimals)) : '0');
    }
    var neg = value < 0;
    var n = Math.abs(Number(value) || 0).toFixed(decimals);
    var parts = n.split('.');
    var intPart = parts[0];
    var decPart = parts[1] || '';
    intPart = intPart.replace(/\B(?=(\d{3})+(?!\d))/g, '.');
    return (neg ? '-R$ ' : 'R$ ') + intPart + (decimals ? (',' + decPart) : '');
  }

  // helper to read whether client pays freight
  function clientePagaFrete() {
    var sel = $id('clientes_id');
    if (!sel) return true; // default: pays
    var opt = sel.options[sel.selectedIndex];
    if (!opt) return true;
    var paga = opt.getAttribute('data-paga-comissao'); // attribute used in templates
    if (paga === null || paga === undefined) return true;
    // consider '0','false','False' as false
    return !(paga === '0' || paga.toLowerCase && paga.toLowerCase() === 'false');
  }

  // read quantidade
  function readQuantidade() {
    var tipo = ($id('quantidade_tipo') || {}).value;
    if (!tipo) tipo = 'padrao';
    if (tipo === 'personalizada') {
      var manual = $id('quantidade_manual');
      if (!manual) return NaN;
      return parseNumber(manual.value);
    } else {
      var sel = $id('quantidade_id');
      if (!sel) return NaN;
      var opt = sel.options[sel.selectedIndex];
      if (!opt) return NaN;
      var q = opt.getAttribute('data-quantidade');
      return parseNumber(q);
    }
  }

  function readPrecoProdutoUnitario() {
    var rawHidden = $id('preco_produto_unitario_raw');
    if (rawHidden && rawHidden.value) {
      var raw = parseNumber(rawHidden.value);
      if (!isNaN(raw)) return raw;
    }
    var inp = $id('preco_produto_unitario');
    if (!inp) return NaN;
    return parseNumber(inp.value);
  }

  function readPrecoPorLitroRaw() {
    var rawHidden = $id('preco_por_litro_raw');
    if (rawHidden && rawHidden.value) {
      var raw = parseNumber(rawHidden.value);
      if (!isNaN(raw)) return raw;
    }
    var inp = $id('preco_por_litro');
    if (!inp) return NaN;
    return parseNumber(inp.value);
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

  function calcularValorCTe(quantidade) {
    var origem = $id('origem_id') ? $id('origem_id').value : null;
    var destino = ($id('clientes_id') && $id('clientes_id').selectedIndex >= 0) ? (function(){
      var hid = $id('destino_id_hidden');
      if (hid && hid.value) return hid.value;
      return ($id('destino_id') ? $id('destino_id').value : null);
    })() : null;
    if (!origem || !destino) return 0;
    var key = origem + '|' + destino;
    var tarifa = 0;
    try {
      if (typeof ROTAS !== 'undefined' && ROTAS && ROTAS[key]) tarifa = Number(ROTAS[key]) || 0;
    } catch (e) { tarifa = 0; }
    if (isNaN(quantidade) || quantidade <= 0) return 0;
    return Number(quantidade) * Number(tarifa);
  }

  function calcularTudo() {
    ensureHidden('preco_por_litro_raw');

    var quantidade = readQuantidade();
    if (isNaN(quantidade) || quantidade <= 0) quantidade = NaN;

    var precoUnit = readPrecoProdutoUnitario();
    if (isNaN(precoUnit)) precoUnit = 0;

    var precoPorLitroRaw = readPrecoPorLitroRaw();
    if (isNaN(precoPorLitroRaw)) precoPorLitroRaw = 0;

    // Total NF Compra = Q * precoUnit
    var totalNF = NaN;
    if (!isNaN(quantidade)) totalNF = precoUnit * quantidade;
    else totalNF = precoUnit;

    // Detectar se cliente paga frete
    var clientePaga = clientePagaFrete();

    // Valor Total Frete = Q * precoPorLitro (apenas se cliente paga)
    var valorTotalFrete = NaN;
    if (!clientePaga) {
      valorTotalFrete = 0;
      precoPorLitroRaw = 0;
    } else {
      if (!isNaN(quantidade)) valorTotalFrete = precoPorLitroRaw * quantidade;
      else valorTotalFrete = precoPorLitroRaw;
    }

    // Valor CTe via ROTAS (independente do cliente pagar ou não)
    var valorCTe = calcularValorCTe(quantidade);

    // Comissão CTe = 8% sobre valorCTe
    var comissaoCTe = 0;
    if (!isNaN(valorCTe)) comissaoCTe = valorCTe * 0.08;

    // Comissão Motorista: se motorista não paga comissão => 0, else Q * 0.01
    var comissaoMotorista = 0;
    var motoristaSel = $id('motoristas_id');
    if (motoristaSel) {
      var opt = motoristaSel.options[motoristaSel.selectedIndex];
      if (opt) {
        var paga = opt.getAttribute('data-paga-comissao');
        if (paga === '0' || paga === 'false' || paga === 'False' || paga === '0.0') {
          comissaoMotorista = 0;
        } else {
          if (!isNaN(quantidade) && clientePaga) comissaoMotorista = quantidade * 0.01;
          else comissaoMotorista = 0;
        }
      }
    }

    // Lucro = ValorTotalFrete - ComissãoMotorista - ComissãoCTe
    var lucro = 0;
    if (!isNaN(valorTotalFrete)) lucro = Number(valorTotalFrete) - Number(comissaoMotorista || 0) - Number(comissaoCTe || 0);
    else lucro = 0;

    // Escrever de volta
    var inpPrecoUnit = $id('preco_produto_unitario');
    if (inpPrecoUnit) {
      var rawHidden = $id('preco_produto_unitario_raw');
      if (rawHidden && (rawHidden.value !== '' && rawHidden.value !== null && !isNaN(parseNumber(rawHidden.value)))) {
        var r = parseNumber(rawHidden.value);
        inpPrecoUnit.value = formatCurrencyBR(isNaN(r) ? 0 : r, 3);
      } else {
        inpPrecoUnit.value = formatCurrencyBR(precoUnit || 0, 3);
        if (rawHidden) rawHidden.value = isNaN(precoUnit) ? 0 : precoUnit;
      }
    }

    var inpPpl = $id('preco_por_litro');
    if (inpPpl) {
      inpPpl.value = formatCurrencyBR(precoPorLitroRaw || 0, 2);
      var h = $id('preco_por_litro_raw');
      if (h) h.value = isNaN(precoPorLitroRaw) ? 0 : precoPorLitroRaw;
      // esconder/desabilitar se cliente não paga
      var container = inpPpl.closest('.row') || inpPpl.parentElement;
      if (!clientePaga) {
        inpPpl.readOnly = true;
        if (container) container.style.display = 'none';
      } else {
        inpPpl.readOnly = false;
        if (container) container.style.display = '';
      }
    }

    var inpTotalNF = $id('total_nf_compra');
    if (inpTotalNF) inpTotalNF.value = formatCurrencyBR(totalNF || 0, 2);

    var inpVTF = $id('valor_total_frete');
    if (inpVTF) inpVTF.value = formatCurrencyBR(valorTotalFrete || 0, 2);

    var inpComMotor = $id('comissao_motorista');
    if (inpComMotor) inpComMotor.value = formatCurrencyBR(comissaoMotorista || 0, 2);

    var inpCTe = $id('valor_cte');
    if (inpCTe) inpCTe.value = formatCurrencyBR(valorCTe || 0, 2);

    var inpComCTe = $id('comissao_cte');
    if (inpComCTe) inpComCTe.value = formatCurrencyBR(comissaoCTe || 0, 2);

    var inpLucro = $id('lucro');
    if (inpLucro) inpLucro.value = formatCurrencyBR(lucro || 0, 2);

    // ensure hidden fields exist
    try {
      ensureHidden('valor_cte');
      ensureHidden('comissao_cte');
      ensureHidden('comissao_motorista');
      ensureHidden('total_nf_compra');
      ensureHidden('valor_total_frete');
      ensureHidden('lucro');

      var hcte = $id('valor_cte_raw');
      if (!hcte) {
        var h = document.createElement('input');
        h.type = 'hidden';
        h.id = 'valor_cte_raw';
        h.name = 'valor_cte';
        var frm = document.querySelector('form');
        frm && frm.appendChild(h);
      }
    } catch (e) {
      console.error('Erro ao garantir hidden fields:', e);
    }
  }

  // events
  function safeAttach(id, evt, fn) {
    var el = $id(id);
    if (el) el.addEventListener(evt, fn);
  }

  function initBindings() {
    // attach masks if present
    // (you might still want the attachNumericMask function from the prior version;
    // for brevity, this file assumes simple formatted inputs)
    safeAttach('quantidade_tipo', 'change', calcularTudo);
    safeAttach('quantidade_id', 'change', calcularTudo);
    safeAttach('quantidade_manual', 'input', calcularTudo);
    safeAttach('motoristas_id', 'change', calcularTudo);
    safeAttach('clientes_id', 'change', function () {
      // small delay to let updateDestinoFromCliente run if exists elsewhere
      setTimeout(calcularTudo, 50);
    });
    safeAttach('origem_id', 'change', calcularTudo);
    safeAttach('destino_id', 'change', calcularTudo);

    // initial calc
    calcularTudo();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initBindings);
  } else {
    initBindings();
  }
})();
