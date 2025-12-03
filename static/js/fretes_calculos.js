// static/js/fretes_calculos.js
// Versão atualizada: máscara on-the-fly, destino automático, CTe, comissões e lucro
(function () {
  'use strict';

  // ---------- helpers ----------
  function $id(id) { return document.getElementById(id); }

  // parseNumber tolerante (aceita "R$ 1.234,56", "1234.56", "3650")
  function parseNumber(value) {
    if (value === null || value === undefined) return NaN;
    if (typeof value === 'number') return value;
    var s = String(value).trim();
    if (s === '') return NaN;
    s = s.replace(/R\$\s*/gi, '').replace(/\s+/g, '');
    // remove tudo que não seja dígito, vírgula, ponto ou hífen
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

  // format "R$ 1.234,56" with decimals
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

  // máscara on-the-fly tipo: usuário digita dígitos, nós dividimos por 10^decimals
  // ex: decimals=3, digits="3650" -> 3.650
  function attachNumericMask(id, decimals, hiddenId) {
    var el = $id(id);
    if (!el) return;

    // create hidden raw if not present
    if (hiddenId && !$id(hiddenId)) {
      var h = document.createElement('input');
      h.type = 'hidden';
      h.id = hiddenId;
      h.name = hiddenId;
      el.form && el.form.appendChild(h);
    }

    // store raw digits in dataset while typing to preserve cursor behavior
    el.dataset.__digits = '';

    function digitsToNumber(digits) {
      if (!digits) return 0;
      var n = parseInt(digits, 10);
      if (isNaN(n)) return 0;
      return n / Math.pow(10, decimals);
    }

    function formatFromDigits(digits) {
      var value = digitsToNumber(digits);
      return formatCurrencyBR(value, decimals);
    }

    // initialize from existing value (allow formatted or raw)
    function init() {
      var current = el.value || '';
      // try parseNumber first
      var n = parseNumber(current);
      if (!isNaN(n) && n !== 0) {
        var asInt = Math.round(Math.abs(n) * Math.pow(10, decimals));
        el.dataset.__digits = String(asInt);
        el.value = formatFromDigits(el.dataset.__digits);
        if (hiddenId) $id(hiddenId).value = n;
        return;
      }
      el.dataset.__digits = '';
      el.value = current ? formatFromDigits(el.dataset.__digits) : '';
    }

    // on input: accept digits and remove non-digits
    el.addEventListener('input', function (ev) {
      // get only digits from input
      var raw = el.value || '';
      var digits = (raw.match(/\d/g) || []).join('');
      // prevent huge lengths
      if (digits.length > 12) digits = digits.slice(0, 12);
      el.dataset.__digits = digits;
      el.value = formatFromDigits(digits);
      if (hiddenId) {
        var num = digitsToNumber(digits);
        $id(hiddenId).value = isNaN(num) ? 0 : num;
      }
      // recalc on the fly
      setTimeout(calcularTudo, 5);
    }, { passive: true });

    // on blur ensure hidden raw is set (and formatted display)
    el.addEventListener('blur', function () {
      var digits = el.dataset.__digits || '';
      el.value = formatFromDigits(digits);
      if (hiddenId) {
        var num = digitsToNumber(digits);
        $id(hiddenId).value = isNaN(num) ? 0 : num;
      }
      calcularTudo();
    });

    init();
  }

  // read quantidade conforme tipo
  function readQuantidade() {
    var tipo = (document.querySelector('#quantidade_tipo') || {}).value;
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

  // read preco unitario raw (prefer hidden raw)
  function readPrecoProdutoUnitario() {
    var rawHidden = $id('preco_produto_unitario_raw');
    if (rawHidden && rawHidden.value) {
      var raw = parseNumber(rawHidden.value);
      if (!isNaN(raw)) return raw;
    }
    var inp = $id('preco_produto_unitario');
    if (!inp) return NaN;
    // attempt parse visible value
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

  // garantir hidden para campos usados pelo backend
  function ensureHidden(name) {
    if ($id(name)) return;
    var h = document.createElement('input');
    h.type = 'hidden';
    h.id = name;
    h.name = name;
    var form = document.querySelector('form');
    if (form) form.appendChild(h);
  }

  // calcula valor cte baseado em ROTAS (origem|destino)
  function calcularValorCTe(quantidade) {
    var origem = $id('origem_id') ? $id('origem_id').value : null;
    var destino = ($id('clientes_id') && $id('clientes_id').selectedIndex >= 0) ? (function(){
      // preferir destino_id_hidden (preenchido a partir do cliente)
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
    // Valor CTe = quantidade * tarifa_por_litro (rotas table stores valor_por_litro)
    if (isNaN(quantidade) || quantidade <= 0) return 0;
    return Number(quantidade) * Number(tarifa);
  }

  // função principal de cálculo
  function calcularTudo() {
    // garantir hidden inputs esperados pelo backend (se não existirem, criá-los)
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

    // Valor Total Frete = Q * precoPorLitroRaw
    var valorTotalFrete = NaN;
    if (!isNaN(quantidade)) valorTotalFrete = precoPorLitroRaw * quantidade;
    else valorTotalFrete = precoPorLitroRaw;

    // Valor CTe via ROTAS
    var valorCTe = calcularValorCTe(quantidade);

    // Comissão CTe = 8% sobre valorCTe
    var comissaoCTe = 0;
    if (!isNaN(valorCTe)) comissaoCTe = valorCTe * 0.08;

    // Comissão Motorista: rule:
    // if motorista.data-paga-comissao == "0" => 0
    // else => Q * 0.01
    var comissaoMotorista = 0;
    var motoristaSel = $id('motoristas_id');
    if (motoristaSel) {
      var opt = motoristaSel.options[motoristaSel.selectedIndex];
      if (opt) {
        var paga = opt.getAttribute('data-paga-comissao');
        if (paga === '0' || paga === 'false' || paga === 'False' || paga === '0.0') {
          comissaoMotorista = 0;
        } else {
          if (!isNaN(quantidade)) comissaoMotorista = quantidade * 0.01;
          else comissaoMotorista = 0;
        }
      }
    }

    // Lucro = ValorTotalFrete - ComissãoMotorista - ComissãoCTe
    var lucro = 0;
    if (!isNaN(valorTotalFrete)) lucro = Number(valorTotalFrete) - Number(comissaoMotorista || 0) - Number(comissaoCTe || 0);

    // Escrever de volta nos campos (visuais formatados e hidden raw)
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
    } else {
      if ($id('preco_produto_unitario_raw') == null && typeof precoUnit !== 'undefined') {
        ensureHidden('preco_produto_unitario_raw');
        $id('preco_produto_unitario_raw').value = precoUnit;
      }
    }

    var inpPpl = $id('preco_por_litro');
    if (inpPpl) {
      inpPpl.value = formatCurrencyBR(precoPorLitroRaw || 0, 2);
      var h = $id('preco_por_litro_raw');
      if (h) h.value = isNaN(precoPorLitroRaw) ? 0 : precoPorLitroRaw;
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

    // ensure hidden fields used by backend exist and are populated
    try {
      ensureHidden('valor_cte');
      ensureHidden('comissao_cte');
      ensureHidden('comissao_motorista');
      ensureHidden('total_nf_compra');
      ensureHidden('valor_total_frete');
      ensureHidden('lucro');

      if ($id('valor_cte')) {
        var hv = $id('valor_cte');
        if (hv && hv.tagName.toLowerCase() === 'input' && hv.type === 'text') {
          // nothing
        } else {
          var h = document.createElement('input');
          h.type = 'hidden';
          h.id = 'valor_cte_raw';
          h.name = 'valor_cte';
          var frm = document.querySelector('form');
          frm && frm.appendChild(h);
        }
      }
    } catch (e) {
      console.error('Erro ao garantir hidden fields:', e);
    }
  }

  // Atualiza destino a partir do cliente selecionado (marca select destino e atualiza destino_id_hidden)
  function updateDestinoFromCliente() {
    var clientesSelect = $id('clientes_id');
    var destinoSelect = $id('destino_id');
    var destinoHidden = $id('destino_id_hidden');
    if (!clientesSelect || !destinoHidden) return;

    var selectedOption = clientesSelect.options[clientesSelect.selectedIndex];
    var destId = selectedOption ? selectedOption.getAttribute('data-destino-id') : null;
    if (!destId) {
      if (destinoSelect) { destinoSelect.value = ''; destinoSelect.disabled = true; }
      destinoHidden.value = '';
      return;
    }
    if (destinoSelect) {
      var opt = destinoSelect.querySelector('option[value="' + destId + '"]');
      if (opt) {
        destinoSelect.value = destId;
        destinoSelect.disabled = true;
      } else {
        var newOpt = document.createElement('option');
        newOpt.value = destId;
        var nome = selectedOption.getAttribute('data-destino-nome') || 'Destino do cliente';
        newOpt.text = nome;
        destinoSelect.insertBefore(newOpt, destinoSelect.firstChild);
        destinoSelect.value = destId;
        destinoSelect.disabled = true;
      }
    }
    destinoHidden.value = destId;
  }

  // attach events
  function safeAttach(id, evt, fn) {
    var el = $id(id);
    if (el) el.addEventListener(evt, fn);
  }

  function initBindings() {
    // Masks: preco unitario (3 casas) and preco por litro (2 casas)
    attachNumericMask('preco_produto_unitario', 3, 'preco_produto_unitario_raw');
    attachNumericMask('preco_por_litro', 2, 'preco_por_litro_raw');

    // quantidade changes
    safeAttach('quantidade_tipo', 'change', function () {
      var tipo = ($id('quantidade_tipo') || {}).value;
      if (tipo === 'personalizada') {
        var d = $id('div_quantidade_personalizada');
        if (d) d.style.display = '';
        var dpad = $id('div_quantidade_padrao');
        if (dpad) dpad.style.display = 'none';
      } else {
        var d = $id('div_quantidade_personalizada');
        if (d) d.style.display = 'none';
        var dpad = $id('div_quantidade_padrao');
        if (dpad) dpad.style.display = '';
      }
      calcularTudo();
    });
    safeAttach('quantidade_id', 'change', calcularTudo);
    safeAttach('quantidade_manual', 'input', function () { calcularTudo(); });

    // motorista / cliente / origem changes
    safeAttach('motoristas_id', 'change', calcularTudo);
    safeAttach('clientes_id', 'change', function () {
      setTimeout(function(){ updateDestinoFromCliente(); calcularTudo(); }, 40);
    });
    safeAttach('origem_id', 'change', function(){ calcularTudo(); });

    safeAttach('destino_id', 'change', function(){ calcularTudo(); });

    // initialize destino from current cliente selection
    updateDestinoFromCliente();

    // initial calc
    calcularTudo();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initBindings);
  } else {
    initBindings();
  }
})();
