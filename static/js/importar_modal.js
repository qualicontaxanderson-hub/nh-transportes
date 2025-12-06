(function(){
  const IMPORT_PAGE_URL = '/pedidos/importar';

  // Executa scripts inline e externos; retorna Promise que resolve quando todos os externos carregarem
  function executeScriptsAndWait(container) {
    const scripts = Array.from(container.querySelectorAll('script'));
    const externalPromises = [];

    scripts.forEach((s) => {
      try {
        if (s.src) {
          const scriptEl = document.createElement('script');
          scriptEl.src = s.src;
          scriptEl.async = false;
          const p = new Promise((resolve) => {
            scriptEl.onload = () => resolve();
            scriptEl.onerror = () => {
              console.error('Falha ao carregar script externo:', s.src);
              resolve();
            };
          });
          externalPromises.push(p);
          document.head.appendChild(scriptEl);
        } else {
          try {
            (0, eval)(s.innerText);
          } catch (err) {
            console.error('Erro script inline:', err);
          }
        }
      } catch (err) {
        console.error('Erro ao processar script tag:', err);
      }
    });

    return Promise.all(externalPromises);
  }

  function fallbackInitModal(container) {
    try {
      const modalEl = container.querySelector('#modalImportarPedido') || container.querySelector('.modal');
      if (!modalEl) return;

      function formatBR2(v){
        if (v === null || v === undefined) return '0,00';
        const n = Number(v) || 0;
        const neg = n < 0;
        const abs = Math.abs(n).toFixed(2);
        const parts = abs.split('.');
        let inteiro = parts[0];
        const dec = parts[1];
        inteiro = inteiro.replace(/\B(?=(\d{3})+(?!\d))/g, '.');
        return (neg ? '-' : '') + inteiro + ',' + dec;
      }
      function desformat(v){
        if (!v) return 0;
        return parseFloat(String(v).replace(/\./g,'').replace(',', '.')) || 0;
      }

      function aplicarBlurPrecoLitro(input){
        if (!input) return;
        input.addEventListener('blur', function(){
          try {
            const raw = String(input.value || '').trim();
            const onlyDigits = raw.replace(/\D/g, '');
            const hasSeparator = raw.indexOf(',') >= 0 || raw.indexOf('.') >= 0;
            let valueToUse = 0;
            if (onlyDigits && !hasSeparator) {
              valueToUse = parseInt(onlyDigits,10) / 100.0;
            } else {
              valueToUse = desformat(raw);
            }
            input.value = formatBR2(valueToUse);
          } catch (err) {
            console.error('fallback blur preco litro error', err);
          }
          input.dispatchEvent(new Event('change', { bubbles: true }));
        });
      }

      const inputs = Array.from(container.querySelectorAll('.campo-preco-litro'));
      inputs.forEach(i => {
        aplicarBlurPrecoLitro(i);
        i.addEventListener('input', function(){ i.dispatchEvent(new Event('change', { bubbles: true })); });
      });

    } catch(err){
      console.error('fallbackInitModal error', err);
    }
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

      await executeScriptsAndWait(container);

      if (window.initImportModal && typeof window.initImportModal === 'function') {
        try {
          window.initImportModal();
        } catch (err) {
          console.error('Erro ao chamar initImportModal:', err);
        }
      } else {
        try {
          fallbackInitModal(container);
        } catch (err) {
          console.error('Erro no fallbackInitModal:', err);
        }
      }

      const modalEl = container.querySelector('#modalImportarPedido') || container.querySelector('.modal');
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
