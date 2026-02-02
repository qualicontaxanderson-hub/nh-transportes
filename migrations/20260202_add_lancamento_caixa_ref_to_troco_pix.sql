-- Migration: Adicionar referência de lancamento_caixa_id na tabela troco_pix
-- Data: 2026-02-02
-- Descrição: Permite vincular cada Troco PIX com um lançamento de caixa automático

-- Adicionar coluna lancamento_caixa_id
ALTER TABLE troco_pix 
ADD COLUMN lancamento_caixa_id INT NULL AFTER status,
ADD CONSTRAINT fk_troco_pix_lancamento_caixa 
  FOREIGN KEY (lancamento_caixa_id) 
  REFERENCES lancamentos_caixa(id) 
  ON DELETE SET NULL;

-- Adicionar índice para melhorar performance
CREATE INDEX idx_troco_pix_lancamento_caixa ON troco_pix(lancamento_caixa_id);

-- Comentário explicativo
ALTER TABLE troco_pix 
COMMENT = 'Tabela de solicitações de Troco PIX com integração automática ao Fechamento de Caixa';
