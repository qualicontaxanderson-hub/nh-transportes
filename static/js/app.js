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

  // CONVERSÃO AUTOMÁTICA PARA MAIÚSCULAS
  // Converte automaticamente campos de texto para maiúsculas (exceto email, password, textarea)
  var textInputs = document.querySelectorAll('input[type="text"], input:not([type])');
  textInputs.forEach(function(input) {
    // Ignora campos que não devem ser convertidos
    var excludeNames = ['email', 'password', 'senha', 'observacao', 'observacoes'];
    var excludeTypes = ['email', 'password', 'url'];
    
    var inputName = (input.name || '').toLowerCase();
    var inputType = (input.type || '').toLowerCase();
    
    // Verifica se o campo deve ser excluído
    var shouldExclude = excludeTypes.includes(inputType) || 
                        excludeNames.some(function(name) { return inputName.includes(name); });
    
    if (!shouldExclude) {
      // Converte para maiúsculas ao digitar
      input.addEventListener('input', function(e) {
        var start = e.target.selectionStart;
        var end = e.target.selectionEnd;
        e.target.value = e.target.value.toUpperCase();
        e.target.setSelectionRange(start, end);
      });
      
      // Garante conversão ao sair do campo
      input.addEventListener('blur', function(e) {
        e.target.value = e.target.value.toUpperCase();
      });
    }
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
