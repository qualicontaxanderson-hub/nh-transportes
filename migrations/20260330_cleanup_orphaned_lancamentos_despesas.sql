-- Migration: 20260330_cleanup_orphaned_lancamentos_despesas.sql
--
-- Problema: o código antigo de reverter_conciliacao / reverter_conciliacao_lote /
-- excluir_transacao usava:
--
--   UPDATE lancamentos_despesas SET bank_transaction_id = NULL
--   WHERE bank_transaction_id = <tx_id>
--
-- Em vez de DELETE.  Isso deixava o registro original vivo (com
-- bank_transaction_id = NULL), e quando o usuário reconciliava com outra
-- categoria um NOVO registro era criado — resultando em duplicatas no
-- conf_despesas (ex.: FIORINO MANUTENÇÃO R$ 1.400 e DESP. COM CLIENTES -
-- ERROS R$ 1.400 ambos aparecendo para a mesma transação).
--
-- O código foi corrigido para usar DELETE (commit 8f2c997).  Esta migration
-- limpa os registros-fantasma que já existem no banco de dados.
--
-- Critério de identificação (conservador):
--   - bank_transaction_id IS NULL   (o FK foi zerado pelo código antigo)
--   - Existe outro registro na mesma tabela com:
--       * bank_transaction_id IS NOT NULL  (o registro "correto" pós-reconciliação)
--       * mesma data, cliente_id, valor e fornecedor
--
-- O campo `fornecedor` é preenchido automaticamente com a descrição da
-- transação bancária (ex.: "PAGAMENTO PIX-PEB 18864706000167 JEAN CARLOS..."),
-- tornando a coincidência acidental praticamente impossível.
--
-- Segurança: apenas registros que NÃO têm bank_transaction_id E que possuem
-- um duplicata exata linkada a uma transação bancária são removidos.
-- Lançamentos manuais (sem fornecedor ou sem duplicata) não são afetados.
--
-- Execute no Railway / produção após o deploy do código corrigido.

-- Pré-visualização (opcional — rode antes do DELETE para confirmar):
-- SELECT ld_old.*
-- FROM lancamentos_despesas ld_old
-- WHERE ld_old.bank_transaction_id IS NULL
--   AND ld_old.fornecedor IS NOT NULL
--   AND EXISTS (
--       SELECT 1
--       FROM lancamentos_despesas ld_new
--       WHERE ld_new.bank_transaction_id IS NOT NULL
--         AND ld_new.data        = ld_old.data
--         AND ld_new.cliente_id  <=> ld_old.cliente_id
--         AND ld_new.valor       = ld_old.valor
--         AND ld_new.fornecedor  = ld_old.fornecedor
--         AND ld_new.id         <> ld_old.id
--   );

DELETE FROM lancamentos_despesas
WHERE id IN (
    SELECT id FROM (
        SELECT ld_old.id
        FROM lancamentos_despesas ld_old
        WHERE ld_old.bank_transaction_id IS NULL
          AND ld_old.fornecedor IS NOT NULL
          AND EXISTS (
              SELECT 1
              FROM lancamentos_despesas ld_new
              WHERE ld_new.bank_transaction_id IS NOT NULL
                AND ld_new.data        = ld_old.data
                AND ld_new.cliente_id  <=> ld_old.cliente_id
                AND ld_new.valor       = ld_old.valor
                AND ld_new.fornecedor  = ld_old.fornecedor
                AND ld_new.id         <> ld_old.id
          )
    ) AS ld_to_delete
);
