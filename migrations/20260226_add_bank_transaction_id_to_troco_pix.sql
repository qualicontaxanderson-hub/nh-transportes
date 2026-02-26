-- Migration: Adicionar coluna bank_transaction_id na tabela troco_pix
-- Data: 2026-02-26
-- Descrição: Vincula Troco PIX a transações bancárias para conciliação
--            entre a tela /banco/conciliar e /troco_pix/

ALTER TABLE troco_pix
  ADD COLUMN bank_transaction_id INT NULL
    COMMENT 'Transação bancária vinculada (conciliação bancária do Troco PIX)';

CREATE INDEX idx_troco_pix_bank_tx ON troco_pix (bank_transaction_id);
