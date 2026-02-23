-- Migration: 20260223_add_transfer_fields.sql
-- Adiciona suporte a transferências entre contas no mapeamento de CNPJ.
-- Permite que o sistema aprenda "CNPJ X → transferência para Conta Y".

ALTER TABLE bank_supplier_mapping
    ADD COLUMN IF NOT EXISTS conta_destino_id INT NULL COMMENT 'Para transferências: conta bancária de destino',
    ADD COLUMN IF NOT EXISTS tipo_debito VARCHAR(20) NULL COMMENT 'fornecedor | despesa | transferencia';

-- FK para conta destino (opcional — set null se a conta for excluída)
ALTER TABLE bank_supplier_mapping
    ADD CONSTRAINT IF NOT EXISTS fk_bsm_conta_destino
        FOREIGN KEY (conta_destino_id) REFERENCES bank_accounts(id)
        ON DELETE SET NULL;
