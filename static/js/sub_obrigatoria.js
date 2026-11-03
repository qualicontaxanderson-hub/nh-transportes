/* Subcategoria obrigatória (pedido 03/11/2026).
   Se a categoria escolhida TEM subcategoria, o lançamento não pode ficar só
   na categoria — senão as despesas ficam bagunçadas. Este arquivo só marca
   e avisa; cada tela chama NHSub nos pontos em que monta as listas e salva.
   Categoria sem subcategoria continua salvando normal. */
(function () {
  var MARCA = '  ▸ tem subcategoria';
  var css = document.createElement('style');
  css.textContent = 'select.nh-sub-falta{border:2px solid #dc2626!important;background:#fef2f2!important;color:#991b1b}'
    + '.nh-sub-aviso{color:#b91c1c;font-size:11px;font-weight:700;margin-top:2px}';
  document.head.appendChild(css);

  function primeiraVazia(sel) {
    for (var i = 0; i < sel.options.length; i++) if (!sel.options[i].value) return sel.options[i];
    return null;
  }
  function pinta(sel) {
    var falta = sel.dataset.subObrig === '1' && !sel.value;
    sel.classList.toggle('nh-sub-falta', falta);
    // a etiqueta "opcional" da Conciliação vira "obrigatória"
    var campo = sel.closest('.dcampo, .mb-3, .col-md-4, .col-md-6, div');
    var etq = campo ? campo.querySelector('.dopc, .dobr.nh-sub-etq') : null;
    if (etq) {
      if (sel.dataset.subObrig === '1') { etq.className = 'dobr nh-sub-etq'; etq.textContent = 'obrigatória'; }
      else { etq.className = 'dopc'; etq.textContent = 'opcional'; }
    }
  }

  window.NHSub = {
    MARCA: MARCA,
    /* Acrescenta "▸ tem subcategoria" no texto da opção de categoria. */
    marcaCat: function (opt, qtdSubs) {
      if (qtdSubs > 0 && opt.textContent.indexOf(MARCA) < 0) opt.textContent += MARCA;
    },
    /* Chamar DEPOIS de preencher a lista de subcategorias. */
    marcaSub: function (sel) {
      if (!sel) return;
      var tem = false;
      for (var i = 0; i < sel.options.length; i++) if (sel.options[i].value) { tem = true; break; }
      sel.dataset.subObrig = tem ? '1' : '';
      var v = primeiraVazia(sel);
      if (v) {
        if (!v.dataset.nhOrig) v.dataset.nhOrig = v.textContent;
        v.textContent = tem ? '— Escolha a subcategoria (obrigatória) —' : v.dataset.nhOrig;
      }
      if (!sel.dataset.nhSubOuve) {
        sel.dataset.nhSubOuve = '1';
        sel.addEventListener('change', function () { pinta(sel); });
      }
      pinta(sel);
    },
    /* true = categoria tem sub e nenhuma foi escolhida (não pode salvar). */
    falta: function (sel) {
      return !!sel && sel.dataset.subObrig === '1' && !sel.value;
    },
    MSG: 'Esta categoria tem subcategoria — escolha a subcategoria antes de salvar.'
  };
})();
