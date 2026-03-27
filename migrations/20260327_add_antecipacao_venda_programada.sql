-- ================================================
-- Migration: Add ANTECIPAÇÃO CLIENTE receita type and VENDA PROGRAMADA comprovação type
-- Date: 2026-03-27
-- ================================================

-- 1. Add ANTECIPAÇÃO CLIENTE to tipos_receita_caixa (MANUAL type)
INSERT INTO tipos_receita_caixa (nome, tipo, ativo)
SELECT 'ANTECIPAÇÃO CLIENTE', 'MANUAL', 1
WHERE NOT EXISTS (
    SELECT 1 FROM tipos_receita_caixa WHERE nome = 'ANTECIPAÇÃO CLIENTE'
);

-- 2. Extend formas_pagamento_caixa.tipo ENUM to include VENDA_PROGRAMADA
ALTER TABLE formas_pagamento_caixa
    MODIFY COLUMN tipo ENUM(
        'DEPOSITO_ESPECIE',
        'DEPOSITO_CHEQUE_VISTA',
        'DEPOSITO_CHEQUE_PRAZO',
        'PIX',
        'PRAZO',
        'CARTAO',
        'RETIRADA_PAGAMENTO',
        'VENDA_PROGRAMADA'
    ) NULL;

-- 3. Add VENDA PROGRAMADA to formas_pagamento_caixa
INSERT IGNORE INTO formas_pagamento_caixa (nome, tipo, ativo)
SELECT 'VENDA PROGRAMADA', 'VENDA_PROGRAMADA', TRUE
WHERE NOT EXISTS (
    SELECT 1 FROM formas_pagamento_caixa WHERE tipo = 'VENDA_PROGRAMADA'
);

-- ================================================
-- End of Migration
-- ================================================
