// Utilitários e bindings usados pelo formulário de frete.
// Deve ser carregado antes de fretes_calculos.js

// Converte string formatada para número (aceita formatos BR: "R$ 1.234,56" ou "1.234,56" ou "1234.56")
function desformatarMoeda(input) {
  if (input === null || input === undefined) return 0;
  var s = String(input).trim();
  if (s === '') return 0;
  // remover prefixo R$
  s = s.replace(/[Rr]\$\s?/, '').trim();
  // tratar milhares e decimais
  if (s.indexOf('.') >= 0 && s.indexOf(',') >= 0) {
    s = s.replace(/\./g, '').replace(',', '.');
  } else if (s.indexOf(',') >= 0) {
    s = s.replace(',', '.');
  }
  s = s.replace(/[^0-9\.-]/g, '');
  var n = parseFloat(s);
  return isNaN(n) ? 0 : n;
}

// Formata número para string BR (sem prefixo "R$") — ex: 1234.5 -> "1.234,50"
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

// Aplica formatação ao elemento input passado (R$ X.xxx,xx)
// Se usuário digitar apenas dígitos sem separador, interpretamos como inteiro escalado por 'casas'
// Agora também sincroniza o hidden raw (ex: preco_produto_unitario_raw / preco_por_litro_raw)
function aplicarFormatacaoMonetaria(el, casas) {
  if (!el) return;
  try {
    var rawStr = String(el.value || '').trim();
    var valorNum;
    if (/^\d+$/.test(rawStr)) {
      // somente dígitos -> interpretar como inteiro escalado por casas
      valorNum = parseInt(rawStr, 10) / Math.pow(10, casas);
    } else {
      // entrada com separadores/virgula/dot -> parse normal
      valorNum = desformatarMoeda(rawStr);
    }

    // atualizar valor formatado visível
    el.value = 'R$ ' + formatarMoedaBR(valorNum, casas);

    // sincronizar hidden raw (id + "_raw"), criando se necessário
    try {
      var rawId = el.id + '_raw';
      var rawEl = document.getElementById(rawId);
      if (!rawEl) {
        // tentar anexar ao mesmo form
        var form = el.form || document.querySelector('form');
        if (form) {
          rawEl = document.createElement('input');
          rawEl.type = 'hidden';
          rawEl.id = rawId;
          rawEl.name = rawId;
          form.appendChild(rawEl);
        }
      }
      if (rawEl) {
        // garante valor numérico puro com ponto decimal
        rawEl.value = (Math.round((Number(valorNum || 0) + Number.EPSILON) * 1000) / 1000);
        // para campos com 2 casas, arredondar a 2 casas no raw se preferir:
        if (casas === 2) {
          rawEl.value = (Math.round((Number(valorNum || 0) + Number.EPSILON) * 100) / 100);
        }
      }
    } catch (e) {
      console.error('Erro ao sincronizar hidden raw:', e);
    }

  } catch (e) {
    console.error('aplicarFormatacaoMonetaria error', e);
  }
}

function initFretesFixes() {
  var elPrecoProduto = document.getElementById('preco_produto_unitario');
  var elPrecoPorLitro = document.getElementById('preco_por_litro');
  var elComissaoMotorista = document.getElementById('comissao_motorista');

  if (elPrecoProduto) {
    aplicarFormatacaoMonetaria(elPrecoProduto, 3);
    
    // Auto-select all on focus to allow easy overwrite
    elPrecoProduto.addEventListener('focus', function(){
      this.select();
    });
    
    elPrecoProduto.addEventListener('blur', function(){
      aplicarFormatacaoMonetaria(this, 3);
      try{ if (typeof calcularTudo==='function') calcularTudo(); }catch(e){}
    });
    
    // Allow typing digits directly - format will apply on blur
    elPrecoProduto.addEventListener('keydown', function(e){
      // If user starts typing a digit, clear the field first (unless already typing)
      if (/^\d$/.test(e.key) && this.value && this.selectionStart === this.selectionEnd) {
        // Only if we're at the formatted value (starts with R$)
        if (this.value.indexOf('R$') === 0) {
          this.value = '';
        }
      }
    });
  }

  if (elPrecoPorLitro) {
    aplicarFormatacaoMonetaria(elPrecoPorLitro, 2);
    
    // Auto-select all on focus to allow easy overwrite
    elPrecoPorLitro.addEventListener('focus', function(){
      this.select();
    });
    
    elPrecoPorLitro.addEventListener('blur', function(){
      aplicarFormatacaoMonetaria(this, 2);
      try{ if (typeof calcularTudo==='function') calcularTudo(); }catch(e){}
    });
    
    // Allow typing digits directly - format will apply on blur
    elPrecoPorLitro.addEventListener('keydown', function(e){
      // If user starts typing a digit, clear the field first (unless already typing)
      if (/^\d$/.test(e.key) && this.value && this.selectionStart === this.selectionEnd) {
        // Only if we're at the formatted value (starts with R$)
        if (this.value.indexOf('R$') === 0) {
          this.value = '';
        }
      }
    });
  }

  if (elComissaoMotorista) {
    aplicarFormatacaoMonetaria(elComissaoMotorista, 2);
    elComissaoMotorista.addEventListener('blur', function(){
      aplicarFormatacaoMonetaria(this, 2);
      try{ if (typeof calcularTudo==='function') calcularTudo(); }catch(e){}
    });
  }

  // quantidade manual/listbox toggle
  var qTipo = document.getElementById('quantidade_tipo');
  var divPadrao = document.getElementById('div_quantidade_padrao');
  var divManual = document.getElementById('div_quantidade_personalizada');
  if (qTipo && divPadrao && divManual) {
    function aplicarTipo() {
      if (qTipo.value === 'personalizada') {
        divPadrao.style.display = 'none';
        divManual.style.display = '';
      } else {
        divPadrao.style.display = '';
        divManual.style.display = 'none';
      }
      try{ if (typeof calcularTudo==='function') calcularTudo(); }catch(e){}
    }
    qTipo.addEventListener('change', aplicarTipo);
    aplicarTipo();
  }

  var selQuantidade = document.getElementById('quantidade_id');
  var qtdManual = document.getElementById('quantidade_manual');
  if (selQuantidade) selQuantidade.addEventListener('change', function(){ try{ if (typeof calcularTudo==='function') calcularTudo(); }catch(e){} });
  if (qtdManual) qtdManual.addEventListener('blur', function(){ try{ if (typeof calcularTudo==='function') calcularTudo(); }catch(e){} });

  var origemEl = document.getElementById('origem_id');
  var destinoEl = document.getElementById('destino_id');
  var motoristaEl = document.getElementById('motoristas_id');
  if (origemEl) origemEl.addEventListener('change', function(){ try{ if (typeof calcularTudo==='function') calcularTudo(); }catch(e){} });
  if (destinoEl) destinoEl.addEventListener('change', function(){ try{ if (typeof calcularTudo==='function') calcularTudo(); }catch(e){} });
  if (motoristaEl) motoristaEl.addEventListener('change', function(){ try{ if (typeof calcularTudo==='function') calcularTudo(); }catch(e){} });

  // --- novo: bind para cliente -> preencher destino e variáveis do cliente
  var clienteSel = document.getElementById('clientes_id');
  if (clienteSel) {
    function aplicarCliente() {
      var idx = clienteSel.selectedIndex;
      if (idx < 0) return;
      var opt = clienteSel.options[idx];
      var destinoId = opt.getAttribute('data-destino-id') || opt.getAttribute('data-destino') || '';
      var pagaComissao = opt.getAttribute('data-paga-comissao');
      var percentualCte = opt.getAttribute('data-percentual-cte') || opt.getAttribute('data-percentual_cte') || '0';
      var cteIntegral = opt.getAttribute('data-cte-integral') || opt.getAttribute('data-cte_integral') || '0';

      // definir variáveis usadas nos cálculos
      // Use parseBoolean utility function with consistent FALSY_VALUES
      var parseFn = window.parseBoolean || function(val) {
        if (typeof val === 'undefined' || val === null) return false;
        var s = String(val).trim().toLowerCase();
        // Matches FALSY_VALUES in fretes_calculos.js
        var falsyVals = ['', '0', 'false', 'nao', 'não', 'no'];
        return falsyVals.indexOf(s) === -1;
      };
      
      window.__CLIENTE_PAGA_FRETE = parseFn(pagaComissao);

      window.__CLIENTE_PERCENTUAL_CTE = parseFloat(percentualCte) || 0;
      window.__CLIENTE_CTE_INTEGRAL = (String(cteIntegral) === '1' || String(cteIntegral).toLowerCase() === 'true');

      // preencher destino (select e hidden)
      var destHidden = document.getElementById('destino_id_hidden');
      var destSel = document.getElementById('destino_id');
      if (destSel) {
        try {
          destSel.value = destinoId || '';
        } catch (e) { /* ignore */ }
      }
      if (destHidden) destHidden.value = destinoId || '';

      // recalcular tudo
      try { if (typeof calcularTudo === 'function') calcularTudo(); } catch(e){}
    }

    clienteSel.addEventListener('change', aplicarCliente);

    // disparar uma vez para o valor já selecionado ao carregar
    try { aplicarCliente(); } catch(e){}
  }
}

// expor no escopo global
window.desformatarMoeda = desformatarMoeda;
window.formatarMoedaBR = formatarMoedaBR;
window.initFretesFixes = initFretesFixes;

// Inicializador automático: aplica máscaras e dispara cálculo inicial quando DOM pronto
document.addEventListener('DOMContentLoaded', function(){
  try {
    if (typeof initFretesFixes === 'function') initFretesFixes();
  } catch (e) { console.error('initFretesFixes erro', e); }

  try {
    if (typeof calcularTudo === 'function') calcularTudo();
  } catch (e) { /* calcularTudo pode estar definido depois se scripts carregarem em ordem inesperada */ }
});
