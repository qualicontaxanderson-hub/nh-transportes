-- Migration to add 'tipo' column to existing formas_pagamento_caixa table
-- This allows compatibility with systems that already have the table created
-- Created: 2026-01-25

-- Check if the column doesn't exist before adding it
-- Note: This uses a procedure to conditionally add the column

DELIMITER $$

CREATE PROCEDURE add_tipo_column_if_not_exists()
BEGIN
    -- Check if tipo column exists
    IF NOT EXISTS (
        SELECT 1 
        FROM information_schema.COLUMNS 
        WHERE TABLE_SCHEMA = DATABASE()
        AND TABLE_NAME = 'formas_pagamento_caixa' 
        AND COLUMN_NAME = 'tipo'
    ) THEN
        -- Add tipo column with default value
        ALTER TABLE `formas_pagamento_caixa` 
        ADD COLUMN `tipo` ENUM(
            'DEPOSITO_ESPECIE', 
            'DEPOSITO_CHEQUE_VISTA', 
            'DEPOSITO_CHEQUE_PRAZO', 
            'PIX', 
            'PRAZO', 
            'CARTAO', 
            'RETIRADA_PAGAMENTO'
        ) NULL AFTER `nome`;
        
        -- Add index for tipo column
        ALTER TABLE `formas_pagamento_caixa`
        ADD INDEX `idx_formas_pagamento_tipo` (`tipo`);
    END IF;
END$$

DELIMITER ;

-- Execute the procedure
CALL add_tipo_column_if_not_exists();

-- Drop the procedure after use
DROP PROCEDURE IF EXISTS add_tipo_column_if_not_exists;

-- Optional: Update existing records with sensible defaults based on nome
-- You can customize these mappings based on your existing data
UPDATE `formas_pagamento_caixa` 
SET `tipo` = CASE
    WHEN LOWER(nome) LIKE '%espécie%' OR LOWER(nome) LIKE '%dinheiro%' THEN 'DEPOSITO_ESPECIE'
    WHEN LOWER(nome) LIKE '%cheque%vista%' THEN 'DEPOSITO_CHEQUE_VISTA'
    WHEN LOWER(nome) LIKE '%cheque%prazo%' THEN 'DEPOSITO_CHEQUE_PRAZO'
    WHEN LOWER(nome) LIKE '%pix%' THEN 'PIX'
    WHEN LOWER(nome) LIKE '%prazo%' THEN 'PRAZO'
    WHEN LOWER(nome) LIKE '%cartão%' OR LOWER(nome) LIKE '%cartao%' THEN 'CARTAO'
    WHEN LOWER(nome) LIKE '%retirada%' OR LOWER(nome) LIKE '%pagamento%' THEN 'RETIRADA_PAGAMENTO'
    ELSE NULL
END
WHERE `tipo` IS NULL;
