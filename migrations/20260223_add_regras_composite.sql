-- Migration: 20260223_add_regras_composite.sql
-- Adiciona suporte a padrão secundário (match composto), cliente_id,
-- e campos de despesa (titulo_id, categoria_id) nas regras de conciliação.

ALTER TABLE bank_conciliacao_regras
    ADD COLUMN IF NOT EXISTS padrao_secundario VARCHAR(200) NULL
        COMMENT 'Segundo padrão: a descrição também deve conter este texto' AFTER padrao_descricao,
    ADD COLUMN IF NOT EXISTS cliente_id INT NULL
        COMMENT 'Para créditos de cobrança: vincula ao cliente específico' AFTER fornecedor_id,
    ADD COLUMN IF NOT EXISTS titulo_id INT NULL
        COMMENT 'Para débitos → despesa: título da despesa' AFTER cliente_id,
    ADD COLUMN IF NOT EXISTS categoria_id INT NULL
        COMMENT 'Para débitos → despesa: categoria da despesa' AFTER titulo_id;

-- FK para clientes (se existir a tabela)
ALTER TABLE bank_conciliacao_regras
    ADD CONSTRAINT IF NOT EXISTS fk_bcr_cliente
        FOREIGN KEY (cliente_id) REFERENCES clientes(id) ON DELETE SET NULL;

ALTER TABLE bank_conciliacao_regras
    ADD CONSTRAINT IF NOT EXISTS fk_bcr_titulo
        FOREIGN KEY (titulo_id) REFERENCES titulos_despesas(id) ON DELETE SET NULL;

ALTER TABLE bank_conciliacao_regras
    ADD CONSTRAINT IF NOT EXISTS fk_bcr_categoria
        FOREIGN KEY (categoria_id) REFERENCES categorias_despesas(id) ON DELETE SET NULL;
