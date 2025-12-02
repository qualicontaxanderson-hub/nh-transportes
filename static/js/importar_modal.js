(function(){
  const IMPORT_PAGE_URL = '/pedidos/importar';

  function executeInlineScripts(container) {
    const scripts = container.querySelectorAll('script');
    scripts.forEach((s) => {
      try {
        if (s.src) {
          const script = document.createElement('script');
          script.src = s.src;
          script.async = false;
          document.head.appendChild(script);
        } else {
          try { (0, eval)(s.innerText); } catch(e) { console.error('Erro script inline:', e); }
        }
      } catch (err) { console.error('Erro ao executar script:', err); }
    });
  }

  window.abrirImportacaoPedido = async function() {
    try {
      const res = await fetch(IMPORT_PAGE_URL, { credentials: 'same-origin' });
      if (!res.ok) throw new Error('Falha ao carregar importador: ' + res.status);
      const html = await res.text();

      let container = document.getElementById('modalImportacaoContainer');
      if (!container) {
        container = document.createElement('div');
        container.id = 'modalImportacaoContainer';
        document.body.appendChild(container);
      }
      container.innerHTML = html;
      executeInlineScripts(container);

      // tentar abrir modal (se presente)
      const modalEl = container.querySelector('#modalImportarLista') || container.querySelector('.modal');
      if (modalEl) {
        if (window.bootstrap && bootstrap.Modal) {
          try {
            new bootstrap.Modal(modalEl, {backdrop: 'static'}).show();
          } catch (err) {
            if (window.jQuery) jQuery(modalEl).modal('show');
          }
        } else if (window.jQuery) {
          jQuery(modalEl).modal('show');
        } else {
          modalEl.scrollIntoView({behavior:'smooth'});
        }
      } else {
        container.scrollIntoView({behavior:'smooth'});
      }
    } catch (err) {
      console.error('Erro ao abrir importador via fetch:', err);
      if (confirm('Não foi possível abrir embutido. Abrir em nova aba?')) {
        window.open(IMPORT_PAGE_URL, '_blank');
      }
    }
  };

  console.debug('abrirImportacaoPedido (modal fetch) pronto ->', IMPORT_PAGE_URL);
})();
