// static/js/fretes_calculos.js
// Atualizado: aceita entradas rápidas (3650 -> 3,650; 10 -> 0,10),
// preenche destino do cliente, e garante cálculo completo de totais/CTe/comissões/lucro.
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

  function formatCurrencyBRNumber(value, decimals) {
    if (value === null || value === undefined || isNaN(value)) {
      var zero = (decimals === 3) ? '0,000' : (decimals === 2 ? '0,00' : '0');
      return zero;
    }
    var neg = value < 0;
    var n = Math.abs(Number(value) || 0).toFixed(decimals);
    var parts = n.split('.');
    var intPart = parts[0];
    var decPart = parts[1] || '';
    intPart = intPart.replace(/\B(?=(\d{3})+(?!\d))/g, '.');
    return (neg ? '-' : '') + intPart + (decimals ? (',' + decPart) : '');
  }

  function formatCurrencyBR(value, decimals) {
    return 'R$ ' + formatCurrencyBRNumber(value, decimals);
  }

  function clientePagaFrete() {
    var sel = $id('clientes_id');
    if (!sel) return true;
    var opt = sel.options[sel.selectedIndex];
    if (!opt) return true;
    var paga = opt.getAttribute('data-paga-comissao');
    if (paga === null || paga === undefined) return true;
    return !(paga === '0' || (paga.toLowerCase && paga.toLowerCase() === 'false'));
  }

  function clienteCTeIntegral() {
    var sel = $id('clientes_id');
    if (!sel) return false;
    var opt = sel.options[sel.selectedIndex];
    if (!opt) return false;
    var cte = opt.getAttribute('data-cte-integral');
    if (cte === null || cte === undefined) return false;
    return (cte === '1' || cte.toLowerCase() === 'true' || cte === 'true');
  }

  function updateDestinoFromCliente() {
    try {
      var sel = $id('clientes_id');
      if (!sel) return;
      var opt = sel.options[sel.selectedIndex];
      if (!opt) return;
      var destinoId = opt.getAttribute('data-destino-id');
      var destinoHidden = $id('destino_id_hidden');
      var destinoSelect = $id('destino_id');
      if (destinoHidden) destinoHidden.value = destinoId || '';
      if (destinoSelect && destinoId) {
        for (var i = 0; i < destinoSelect.options.length; i++) {
          if (String(destinoSelect.options[i].value) === String(destinoId)) {
            destinoSelect.selectedIndex = i;
            break;
          }
        }
      }
    } catch (e) {
      console.warn('updateDestinoFromCliente error:', e);
    }
  }

  function readQuantidade() {
    var tipoEl = $id('quantidade_tipo');
    var tipo = tipoEl ? tipoEl.value : 'padrao';
    if (tipo === 'personalizada') {
      var manual = $id('quantidade_manual');
      if (!manual) return NaN;
      return parseNumber(manual.value) || NaN;
    } else {
      var sel = $id('quantidade_id');
      if (!sel) return NaN;
      var opt = sel.options[sel.selectedIndex];
      if (!opt) return NaN;
      var q = opt.getAttribute('data-quantidade');
      return parseNumber(q) || NaN;
    }
  }

  function readPrecoProdutoUnitario() {
    var rawHidden = $id('preco_produto_unitario_raw');
    if (rawHidden && rawHidden.value) {
      var v = parseNumber(rawHidden.value);
      if (!isNaN(v)) return v;
    }
    var inp = $id('preco_produto_unitario');
    if (!inp) return NaN;
    var txt = String(inp.value || '').trim();
    if (/^\d+$/.test(txt)) {
      return parseInt(txt, 10) / 1000.0;
    }
    return parseNumber(txt);
  }

  function readPrecoPorLitroRaw() {
    var rawHidden = $id('preco_por_litro_raw');
    if (rawHidden && rawHidden.value) {
      var v = parseNumber(rawHidden.value);
      if (!isNaN(v)) return v;
    }
    var inp = $id('preco_por_litro');
    if (!inp) return NaN;
    var txt = String(inp.value || '').trim();
    if (/^\d+$/.test(txt)) {
      return parseInt(txt, 10) / 100.0;
    }
    return parseNumber(txt);
  }

  function calcularValorCTe(quantidade) {
    var origem = $id('origem_id') ? $id('origem_id').value : null;
    var destino = ($id('destino_id_hidden') && $id('destino_id_hidden').value) ? $id('destino_id_hidden').value : ($id('destino_id') ? $id('destino_id').value : null);
    if (!origem || !destino) return 0;
    var key = origem + '|' + destino;
    var tarifa = 0;
    try {
      if (typeof ROTAS !== 'undefined' && ROTAS && ROTAS[key]) tarifa = Number(ROTAS[key]) || 0;
    } catch (e) { tarifa = 0; }
    if (isNaN(quantidade) || quantidade <= 0) return 0;
    return Number(quantidade) * Number(tarifa);
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

    var quantidade = readQuantidade();
    if (isNaN(quantidade) || quantidade <= 0) quantidade = NaN;

    var precoUnit = readPrecoProdutoUnitario();
    if (isNaN(precoUnit)) precoUnit = 0;

    var precoPorLitroRaw = readPrecoPorLitroRaw();
    if (isNaN(precoPorLitroRaw)) precoPorLitroRaw = 0;

    var totalNF = NaN;
    if (!isNaN(quantidade)) totalNF = precoUnit * quantidade;
    else totalNF = precoUnit;

    var clientePaga = clientePagaFrete();
    var clienteCTEInt = clienteCTeIntegral();

    var valorTotalFrete = NaN;
    if (!clientePaga) {
      valorTotalFrete = 0;
      precoPorLitroRaw = 0;
    } else {
      if (!isNaN(quantidade)) valorTotalFrete = precoPorLitroRaw * quantidade;
      else valorTotalFrete = precoPorLitroRaw;
    }

    var valorCTe = 0;
    if (clienteCTEInt) {
      // CTe integral: valor_cte = valor_total_frete (se cliente paga frete), ou 0 se cliente não paga
      valorCTe = clientePaga ? (Number(valorTotalFrete) || 0) : 0;
    } else {
      valorCTe = calcularValorCTe(quantidade);
    }

    var comissaoCTe = 0;
    if (!isNaN(valorCTe)) comissaoCTe = Number(valorCTe) * 0.08;

    var comissaoMotorista = 0;
    var motoristaSel = $id('motoristas_id');
    if (motoristaSel) {
      var opt = motoristaSel.options[motoristaSel.selectedIndex];
      if (opt) {
        var paga = opt.getAttribute('data-paga-comissao');
        if (paga === '0' || paga === 'false' || paga === 'False' || paga === '0.0') {
          comissaoMotorista = 0;
        } else {
          if (!isNaN(quantidade) && clientePaga) comissaoMotorista = Math.round((quantidade * 0.01) * 100) / 100;
          else comissaoMotorista = 0;
        }
      }
    }

    var lucro = 0;
    if (!clientePaga) {
      // regra de negocio: se cliente não paga frete, lucro deve ser 0
      lucro = 0;
    } else {
      lucro = Number(valorTotalFrete || 0) - Number(comissaoMotorista || 0) - Number(comissaoCTe || 0);
      lucro = Math.round(lucro * 100) / 100;
    }

    // escrever de volta
    var inpPrecoUnit = $id('preco_produto_unitario');
    if (inpPrecoUnit) {
      var rawHidden = $id('preco_produto_unitario_raw');
      if (rawHidden && rawHidden.value !== '' && !isNaN(parseNumber(rawHidden.value))) {
        var r = parseNumber(rawHidden.value);
        inpPrecoUnit.value = formatCurrencyBRNumber(r,3);
      } else {
        inpPrecoUnit.value = formatCurrencyBRNumber(precoUnit || 0, 3);
        if (rawHidden) rawHidden.value = isNaN(precoUnit) ? 0 : precoUnit;
      }
    }

    var inpPpl = $id('preco_por_litro');
    if (inpPpl) {
      inpPpl.value = formatCurrencyBRNumber(precoPorLitroRaw || 0, 2);
      var h = $id('preco_por_litro_raw');
      if (h) h.value = isNaN(precoPorLitroRaw) ? 0 : precoPorLitroRaw;
      var container = inpPpl.closest('[class*="col-"]') || inpPpl.parentElement;
      if (!clientePaga) {
        inpPpl.readOnly = true;
        if (container) container.style.display = 'none';
      } else {
        inpPpl.readOnly = false;
        if (container) container.style.display = '';
      }
    }

    var inpTotalNF = $id('total_nf_compra');
    if (inpTotalNF) inpTotalNF.value = formatCurrencyBRNumber(totalNF || 0, 2);

    var inpVTF = $id('valor_total_frete');
    if (inpVTF) inpVTF.value = formatCurrencyBRNumber(valorTotalFrete || 0, 2);

    var inpComMotor = $id('comissao_motorista');
    if (inpComMotor) inpComMotor.value = formatCurrencyBRNumber(comissaoMotorista || 0, 2);

    var inpCTe = $id('valor_cte');
    if (inpCTe) inpCTe.value = formatCurrencyBRNumber(valorCTe || 0, 2);

    var inpComCTe = $id('comissao_cte');
    if (inpComCTe) inpComCTe.value = formatCurrencyBRNumber(comissaoCTe || 0, 2);

    var inpLucro = $id('lucro');
    if (inpLucro) inpLucro.value = formatCurrencyBRNumber(lucro || 0, 2);

    // garantir hidden fields existentes
    try {
      ensureHidden('valor_cte');
      ensureHidden('comissao_cte');
      ensureHidden('comissao_motorista');
      ensureHidden('total_nf_compra');
      ensureHidden('valor_total_frete');
      ensureHidden('lucro');
    } catch (e) {
      console.error('Erro ao garantir hidden fields:', e);
    }
  }

  function safeAttach(id, evt, fn) {
    var el = $id(id);
    if (el) el.addEventListener(evt, fn);
  }

  function initBindings() {
    safeAttach('clientes_id', 'change', function () {
      setTimeout(function () {
        updateDestinoFromCliente();
        calcularTudo();
      }, 60);
    });

    safeAttach('quantidade_tipo', 'change', calcularTudo);
    safeAttach('quantidade_id', 'change', calcularTudo);
    safeAttach('quantidade_manual', 'input', calcularTudo);
    safeAttach('motoristas_id', 'change', calcularTudo);
    safeAttach('origem_id', 'change', function () { setTimeout(calcularTudo, 10); });
    safeAttach('destino_id', 'change', calcularTudo);

    updateDestinoFromCliente();
    calcularTudo();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initBindings);
  } else {
    initBindings();
  }
})();
