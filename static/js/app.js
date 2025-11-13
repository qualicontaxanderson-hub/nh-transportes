```javascript
document.addEventListener('DOMContentLoaded', function() {
    // Máscara CNPJ
    const cnpjInputs = document.querySelectorAll('input[name="cnpj"]');
    cnpjInputs.forEach(input => {
        input.addEventListener('input', function(e) {
            let value = e.target.value.replace(/\D/g, '');
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
    const telInputs = document.querySelectorAll('input[name="telefone"]');
    telInputs.forEach(input => {
        input.addEventListener('input', function(e) {
            let value = e.target.value.replace(/\D/g, '');
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
    const cepInputs = document.querySelectorAll('input[name="cep"]');
    cepInputs.forEach(input => {
        input.addEventListener('input', function(e) {
            let value = e.target.value.replace(/\D/g, '');
            if (value.length <= 8) {
                value = value.replace(/^(\d{5})(\d)/, '$1-$2');
            }
            e.target.value = value;
        });
    });
});
```

---
