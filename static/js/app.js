document.addEventListener('DOMContentLoaded', function() {

  // Máscara CNPJ
  var cnpjInputs = document.querySelectorAll('input[name="cnpj"]');
  cnpjInputs.forEach(function(input) {
    input.addEventListener('input', function(e) {
      var value = e.target.value.replace(/\D/g, '');
      if (value.length <= 14) {
        value = value.replace(/^(\d{2})(\d)/, '$1.$2');
        value = value.replace(/^(\d{2})\.(\d{3})(\d)/, '$1.$2.$3');
        value = value.replace(/\.(\d{3})(\d)/, '.$1/$2');
        value = value.replace(/(\d{4})(\d)/, '$1-$2');
      }
      e.target.value = value;
    });
  });

  // Máscara Telefone
  var telInputs = document.querySelectorAll('input[name="telefone"]');
  telInputs.forEach(function(input) {
    input.addEventListener('input', function(e) {
      var value = e.target.value.replace(/\D/g, '');
      if (value.length <= 11) {
        if (value.length === 11) {
          value = value.replace(/^(\d{2})(\d{5})(\d{4})/, '($1) $2-$3');
        } else if (value.length === 10) {
          value = value.replace(/^(\d{2})(\d{4})(\d{4})/, '($1) $2-$3');
        }
      }
      e.target.value = value;
    });
  });

  // Máscara CEP
  var cepInputs = document.querySelectorAll('input[name="cep"]');
  cepInputs.forEach(function(input) {
    input.addEventListener('input', function(e) {
      var value = e.target.value.replace(/\D/g, '');
      if (value.length <= 8) {
        value = value.replace(/^(\d{5})(\d)/, '$1-$2');
      }
      e.target.value = value;
    });
  });

  // TRAVA DE CLIQUE EM FORMULÁRIOS
  var forms = document.querySelectorAll('form');

  forms.forEach(function(form) {
    form.addEventListener('submit', function () {
      // Se o formulário tiver a classe js-sem-trava, não faz nada
      if (form.classList.contains('js-sem-trava')) {
        return;
      }

      var submits = form.querySelectorAll('button[type="submit"], input[type="submit"]');

      submits.forEach(function(btn) {
        // Guarda o texto original (se quiser usar no futuro)
        if (!btn.dataset.originalText) {
          btn.dataset.originalText = btn.innerText || btn.value;
        }

        btn.disabled = true;

        if (btn.tagName === 'BUTTON') {
          btn.innerText = 'Salvando...';
        } else if (btn.tagName === 'INPUT') {
          btn.value = 'Salvando...';
        }
      });
    });
  });

});
