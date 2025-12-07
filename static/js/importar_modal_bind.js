// Liga o botão #btn_importar_pedido à função abrirImportacaoPedido definida em importar_modal.js
document.addEventListener('DOMContentLoaded', function() {
  var btn = document.getElementById('btn_importar_pedido');
  if (!btn) return;
  btn.addEventListener('click', function (e) {
    e.preventDefault();
    if (typeof window.abrirImportacaoPedido === 'function') {
      try { window.abrirImportacaoPedido(); } catch (err) { console.error(err); alert('Erro ao abrir importador'); }
    } else {
      var s = document.createElement('script');
      s.src = '/static/js/importar_modal.js';
      s.onload = function() {
        try { if (typeof window.abrirImportacaoPedido === 'function') window.abrirImportacaoPedido(); else alert('Importador indisponível'); } catch(e){ console.error(e); alert('Erro ao abrir importador'); }
      };
      s.onerror = function() { alert('Importador indisponível'); };
      document.head.appendChild(s);
    }
  }, false);
});
