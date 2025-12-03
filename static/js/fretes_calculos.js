// static/js/fretes_calculos.js
// Lógica de cálculo para o formulário de fretes
(function () {
  'use strict';

  /* ---------- Helpers de formatação/parse ---------- */

  // Converte string de entrada para Number
  // Aceita formatos: "R$ 1.234,56", "1234.56", "1.234", "3650", "3,650"
  function parseNumber(value) {
    if (value === null || value === undefined) return NaN;
    if (typeof value === 'number') return value;
    var s = String(value).trim();
    if (s === '') return NaN;
    // remove R$, espaços e sinais extras
    s = s.replace(/R\$\s*/gi, '').replace(/\s+/g, '');
    // se tem letra, invalid
    if (/[^\d.,-]/.test(s)) {
      // remove tudo que não seja dígito, vírgula, ponto ou hífen
      s = s.replace(/[^\d\.,-]/g, '');
    }
    // se contém ',' e '.', decidir qual é decimal:
    // regra simples: se última ocorrência for ',', usaremos ',' como decimal
    var lastComma = s.lastIndexOf(',');
    var lastDot = s.lastIndexOf('.');
    if (lastComma > -1 && lastDot > -1) {
      if (lastComma > lastDot) {
        // '.' são milhares, remove-os; ',' decimal -> replace ','->'.'
        s = s.replace(/\./g, '').replace(',', '.');
      } else {
        // ',' são milhares, remove-os; '.' decimal -> keep '.'
        s = s.replace(/,/g, '');
      }
    } else if (lastComma > -1 && lastDot === -1) {
      // só vírgula: assume vírgula decimal -> replace ','->'.'
      s = s.replace(/\./g, '').replace(',', '.');
    } else {
      // só ponto(s) ou nenhum: remove milhares (dots) e keep dot as decimal
      // caso "1.234" pode ser milhar ou decimal; aqui assumimos milhar quando não há outros separadores
      // para permitir usuário digitar "3650" -> fica 3650
      s = s.replace(/,/g, '');
    }

    var n = parseFloat(s);
    return isNaN(n) ? NaN : n;
  }

  // Formata número para "R$ X.xxx,yy" (decimals = 2, 3...)
  function formatCurrencyBR(value, decimals) {
    if (value === null || value === undefined || isNaN(value)) {
      return 'R$ 0' + (decimals ? (',' + '0'.repeat(decimals)) : '');
    }
    var neg = value < 0;
    var n = Math.abs(Number(value) || 0).toFixed(decimals);
    var parts = n.split('.');
    var intPart = parts[0];
    var decPart = parts[1] || '';
    // add thousands dot
    intPart = intPart.replace(/\B(?=(\d{3})+(?!\d))/g, '.');
    return (neg ? '-R$ ' : 'R$ ') + intPart + (decimals ? (',' + decPart) : '');
  }

  /* ---------- Element getters ---------- */
  function $id(id) { return document.getElementById(id); }

  /* ---------- Cálculos principais ---------- */
  function readQuantidade() {
    var tipo = (document.querySelector('#quantidade_tipo') || {}).value;
    if (!tipo) tipo = 'padrao';
    if (tipo === 'personalizada') {
      var manual = $id('quantidade_manual');
      if (!manual) return NaN;
      // Usuário é instruído a usar ponto como separador de milhar (ex: 9.975)
      // parseNumber já lida com isso
      return parseNumber(manual.value);
    } else {
      var sel = $id('quantidade_id');
      if (!sel) return NaN;
      var opt = sel.options[sel.selectedIndex];
      if (!opt) return NaN;
      // atributo data-quantidade no option contém valor numérico
      var q = opt.getAttribute('data-quantidade');
      return parseNumber(q);
    }
  }

  function readPrecoProdutoUnitario() {
    // tenta ler o hidden raw primeiro se existir e for numérico
    var rawHidden = $id('preco_produto_unitario_raw');
    if (rawHidden && rawHidden.value) {
      var raw = parseNumber(rawHidden.value);
      if (!isNaN(raw) && raw !== 0) return raw;
    }
    // senão parseia o campo de exibição
    var inp = $id('preco_produto_unitario');
    if (!inp) return NaN;
    return parseNumber(inp.value);
  }

  function updatePrecoProdutoHidden(rawValue) {
    var rawHidden = $id('preco_produto_unitario_raw');
    if (!rawHidden) return;
    rawHidden.value = isNaN(rawValue) ? 0 : Number(rawValue);
  }

  function calcularTudo() {
    var precoUnit = readPrecoProdutoUnitario(); // número
    var quantidade = readQuantidade(); // número em litros
    // seguranca: se precoUnit for NaN, set 0
    if (isNaN(precoUnit)) precoUnit = 0;
    if (isNaN(quantidade) || quantidade === 0) quantidade = NaN;

    // calcula preco por litro (precoUnit dividido pela quantidade)
    var precoPorLitro = NaN;
    if (!isNaN(quantidade) && quantidade > 0) {
      precoPorLitro = precoUnit / quantidade;
    }

    // total NF de compra: assumimos precoUnit * quantidade (se não houver quantidade, usa precoUnit)
    var totalNF = NaN;
    if (!isNaN(quantidade) && quantidade > 0) {
      totalNF = precoUnit * quantidade;
    } else {
      totalNF = precoUnit;
    }

    // valor_total_frete: por enquanto usa totalNF (adapte se tiver outros acréscimos)
    var valorTotalFrete = totalNF;

    // comissão motorista: usa data-percentual do motorista selecionado
    var comissaoMotorista = NaN;
    var motoristaSel = $id('motoristas_id');
    if (motoristaSel) {
      var opt = motoristaSel.options[motoristaSel.selectedIndex];
      if (opt) {
        var percentual = parseNumber(opt.getAttribute('data-percentual') || opt.getAttribute('data-percentual'.toLowerCase()));
        if (!isNaN(percentual) && !isNaN(valorTotalFrete)) {
          comissaoMotorista = valorTotalFrete * (percentual / 100);
        }
      }
    }

    // Escrever de volta nos campos formatados
    // preco_produto_unitario: exibir com 3 casas decimais (padrao do template)
    var inpPrecoUnit = $id('preco_produto_unitario');
    if (inpPrecoUnit) {
      inpPrecoUnit.value = formatCurrencyBR(precoUnit, 3);
    }
    // sempre atualizar o hidden raw
    updatePrecoProdutoHidden(precoUnit);

    var inpPrecoPorLitro = $id('preco_por_litro');
    if (inpPrecoPorLitro) {
      inpPrecoPorLitro.value = formatCurrencyBR(precoPorLitro || 0, 2);
    }

    var inpTotalNF = $id('total_nf_compra');
    if (inpTotalNF) {
      inpTotalNF.value = formatCurrencyBR(totalNF || 0, 2);
    }

    var inpValorTotalFrete = $id('valor_total_frete');
    if (inpValorTotalFrete) {
      inpValorTotalFrete.value = formatCurrencyBR(valorTotalFrete || 0, 2);
    }

    var inpComissao = $id('comissao_motorista');
    if (inpComissao) {
      inpComissao.value = formatCurrencyBR(comissaoMotorista || 0, 2);
    }
  }

  /* ---------- Eventos ---------- */
  function safeAttach(id, evt, fn) {
    var el = $id(id);
    if (el) el.addEventListener(evt, fn);
  }

  function initBindings() {
    // quando usuário muda o tipo de quantidade
    safeAttach('quantidade_tipo', 'change', function () {
      // mostrar/ocultar os divs correspondentes (existem no template)
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

    // mudança de quantidade (select)
    safeAttach('quantidade_id', 'change', calcularTudo);
    // input manual de quantidade
    safeAttach('quantidade_manual', 'input', function () {
      // permitir digitação (ex: 9.975)
      calcularTudo();
    });

    // preco produto unitario (input formatado) - atualizar ao blur e ao input
    var precoInp = $id('preco_produto_unitario');
    if (precoInp) {
      precoInp.addEventListener('blur', function () {
        // parse value typed and recalc
        var n = parseNumber(precoInp.value);
        if (isNaN(n)) n = 0;
        updatePrecoProdutoHidden(n);
        calcularTudo();
      });
      precoInp.addEventListener('input', function () {
        // não formatar em cada tecla para não atrapalhar digitação, apenas recalcular "on the fly"
        // se desejar formatação imediata, pode-se aplicar máscara aqui
      });
    }

    // motoristas muda percentual de comissao
    safeAttach('motoristas_id', 'change', calcularTudo);

    // clientes muda -> possivelmente altera destino (já temos outro script), mas recalc
    safeAttach('clientes_id', 'change', function () {
      // slight delay so destino script can run first if present
      setTimeout(calcularTudo, 120);
    });

    // quando a página carrega, calcular com os valores atuais
    calcularTudo();
  }

  // inicializa no DOMContentLoaded
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initBindings);
  } else {
    initBindings();
  }

})();
