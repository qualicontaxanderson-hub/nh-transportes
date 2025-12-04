// static/js/fretes_calculos.js
// Atualizado: preenche destino a partir do cliente, trata formatos de entrada (inteiros -> decimais),
// esconde somente a coluna do preço por litro e garante cálculo completo (CTe, comissões, lucro).
(function () {
  'use strict';

  function $id(id) { return document.getElementById(id); }

  function parseNumber(value) {
    if (value === null || value === undefined) return NaN;
    if (typeof value === 'number') return value;
    var s = String(value).trim();
    if (s === '') return NaN;
    // remove R$ e espaços
    s = s.replace(/R\$\s*/gi, '').replace(/\s+/g, '');
    // se for apenas dígitos (ex: '3650' ou '10'), retornamos NaN aqui e trataremos fora
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

  // Detecta se o cliente paga frete/comissão, usando atributo data-paga-comissao na option
  function clientePagaFrete() {
    var sel = $id('clientes_id');
    if (!sel) return true;
    var opt = sel.options[sel.selectedIndex];
    if (!opt) return true;
    var paga = opt.getAttribute('data-paga-comissao');
    if (paga === null || paga === undefined) return true;
    return !(paga === '0' || (paga.toLowerCase && paga.toLowerCase() === 'false'));
  }

  // Preenche destino a partir do cliente (usa data-destino-id do option)
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
        // tentar selecionar a opção correspondente (caso exista)
        for (var i = 0; i < destinoSelect.options.length; i++) {
          if (String(destinoSelect.options[i].value) === String(destinoId)) {
            destinoSelect.selectedIndex = i;
            break;
          }
        }
      }
    } catch (e) {
      // não interromper o fluxo se der problema
      console.warn('updateDestinoFromCliente error:', e);
    }
  }

  // Lê quantidade (padrao ou manual)
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

  // Leitura com heurística: aceita entradas sem separador
  function readPrecoProdutoUnitario() {
    // raw hidden tem precedência
    var rawHidden = $id('preco_produto_unitario_raw');
    if (rawHidden && rawHidden.value) {
      var v = parseNumber(rawHidden.value);
      if (!isNaN(v)) return v;
    }
    var inp = $id('preco_produto_unitario');
    if (!inp) return NaN;
    var txt = String(inp.value || '').trim();
    if (/^\d+$/.test(txt)) {
      // se somente dígitos -> interpretar como valor com 3 casas decimais
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
      // se somente dígitos -> interpretar como valor com 2 casas decimais
      return parseInt(txt, 10) / 100.0;
    }
    return parseNumber(txt);
  }

  // calcula CTe a partir do map ROTAS (origem|destino)
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
    // garantir hidden onde necessário
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
    if (!isNaN(valorCTe)) comissaoCTe = Number(valorCTe) * 0.08;

    // Comissão Motorista: se motorista não paga comissão => 0, else Q * 0.01 (somente se cliente paga frete)
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
    else lucro = 0 - Number(comissaoMotorista || 0) - Number(comissaoCTe || 0);

    // Escrever de volta (formatados)
    var inpPrecoUnit = $id('preco_produto_unitario');
    if (inpPrecoUnit) {
      var rawHidden = $id('preco_produto_unitario_raw');
      if (rawHidden && rawHidden.value !== '' && !isNaN(parseNumber(rawHidden.value))) {
        var r = parseNumber(rawHidden.value);
        inpPrecoUnit.value = (isNaN(r) ? formatCurrencyBR(0,3) : formatCurrencyBR(r,3)).replace('R$ ','');
      } else {
        inpPrecoUnit.value = formatCurrencyBR(precoUnit || 0, 3).replace('R$ ','');
        if (rawHidden) rawHidden.value = isNaN(precoUnit) ? 0 : precoUnit;
      }
    }

    var inpPpl = $id('preco_por_litro');
    if (inpPpl) {
      // preencher visível sem o prefixo R$
      inpPpl.value = formatCurrencyBR(precoPorLitroRaw || 0, 2).replace('R$ ','');
      var h = $id('preco_por_litro_raw');
      if (h) h.value = isNaN(precoPorLitroRaw) ? 0 : precoPorLitroRaw;
      // esconder/desabilitar apenas a coluna do preço por litro
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
    // Bind updateDestinoFromCliente before calcularTudo so destino já esteja setado
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
    safeAttach('origem_id', 'change', function () {
      setTimeout(calcularTudo, 10);
    });
    safeAttach('destino_id', 'change', calcularTudo);

    // initial populate destino (on page load)
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
