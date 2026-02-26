-- ============================================================
-- Migration: 20260226_transferencia_credito_support.sql
-- Suporte a Transferência Bancária no lado Crédito da conciliação.
--
-- CONTEXTO
-- --------
-- Quando o Banco Sicredi envia dinheiro para o Banco Cora, o sistema
-- já conciliava o DÉBITO no Sicredi como "transferência entre contas".
-- Agora o CRÉDITO correspondente no Cora também precisa aparecer na
-- fila de conciliação como "Transferência Recebida", para que o usuário
-- possa simplesmente confirmar com um clique.
--
-- ALTERAÇÕES NECESSÁRIAS NO BANCO
-- ---------------------------------
-- 1. bank_transactions.tipo_conciliacao  (VARCHAR 20, NULL)
--    Já criada em 20260224_add_tipo_conciliacao.sql.
--    Valor utilizado por esta funcionalidade: 'transferencia'.
--    O código grava 'transferencia' tanto no DÉBITO de origem quanto
--    no CRÉDITO de destino, permitindo que a tela identifique os dois
--    lados da mesma operação.
--
-- 2. bank_supplier_mapping.tipo_debito  (VARCHAR 20, NULL)
--    Já criada em 20260223_add_transfer_fields.sql.
--    Valor utilizado: 'transferencia'.
--    Quando o usuário concilia um DÉBITO como transferência, o sistema
--    grava 'transferencia' nesta coluna junto ao CNPJ do banco
--    destinatário. Na próxima importação do extrato do Cora, qualquer
--    CRÉDITO cujo CNPJ bata com esse mapeamento é automaticamente
--    identificado como "Transferência Recebida" e exibe o botão
--    "Aprovar Receb." com 1 clique.
--
-- 3. bank_supplier_mapping.conta_destino_id  (INT, NULL, FK bank_accounts)
--    Já criada em 20260223_add_transfer_fields.sql.
--    Armazena qual conta bancária recebe o dinheiro quando o CNPJ é
--    identificado como destino de transferência. Permite sugerir
--    automaticamente a conta na próxima vez.
--
-- RESUMO: Nenhuma coluna nova precisa ser criada para esta
-- funcionalidade. As três colunas acima já existem nas migrations
-- anteriores. Este arquivo serve como checklist de verificação e
-- registro histórico da mudança funcional.
-- ============================================================

-- ---------------------------------------------------------------
-- VERIFICAÇÃO (idempotente): confirma que as colunas existem.
-- Execute no Railway para garantir que as migrations anteriores
-- foram aplicadas corretamente.
-- ---------------------------------------------------------------

-- 1. tipo_conciliacao em bank_transactions
SELECT
    CASE
        WHEN COUNT(*) > 0 THEN 'OK: bank_transactions.tipo_conciliacao existe'
        ELSE 'ERRO: falta a coluna bank_transactions.tipo_conciliacao — execute 20260224_add_tipo_conciliacao.sql'
    END AS verificacao_tipo_conciliacao
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME   = 'bank_transactions'
  AND COLUMN_NAME  = 'tipo_conciliacao';

-- 2. tipo_debito em bank_supplier_mapping
SELECT
    CASE
        WHEN COUNT(*) > 0 THEN 'OK: bank_supplier_mapping.tipo_debito existe'
        ELSE 'ERRO: falta a coluna bank_supplier_mapping.tipo_debito — execute 20260223_add_transfer_fields.sql'
    END AS verificacao_tipo_debito
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME   = 'bank_supplier_mapping'
  AND COLUMN_NAME  = 'tipo_debito';

-- 3. conta_destino_id em bank_supplier_mapping
SELECT
    CASE
        WHEN COUNT(*) > 0 THEN 'OK: bank_supplier_mapping.conta_destino_id existe'
        ELSE 'ERRO: falta a coluna bank_supplier_mapping.conta_destino_id — execute 20260223_add_transfer_fields.sql'
    END AS verificacao_conta_destino_id
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME   = 'bank_supplier_mapping'
  AND COLUMN_NAME  = 'conta_destino_id';

-- ---------------------------------------------------------------
-- CORREÇÃO OPCIONAL: CREDITs sintéticos antigos que foram gravados
-- como 'conciliado' diretamente (comportamento anterior) podem ser
-- reabertas para 'pendente' + tipo_conciliacao='transferencia' para
-- que apareçam na fila e possam ser confirmadas pelo usuário.
--
-- ATENÇÃO: Execute manualmente apenas se desejar reprocessar
-- transferências antigas. Comente o bloco se não for necessário.
-- ---------------------------------------------------------------

/*
UPDATE bank_transactions
SET    status            = 'pendente',
       tipo_conciliacao  = 'transferencia',
       conciliado_em     = NULL,
       conciliado_por    = NULL
WHERE  tipo              = 'CREDIT'
  AND  descricao         LIKE 'TRANSFERENCIA RECEBIDA -%'
  AND  status            = 'conciliado'
  AND  (tipo_conciliacao IS NULL OR tipo_conciliacao = 'transferencia');
*/

SELECT 'Migration 20260226_transferencia_credito_support verificada com sucesso.' AS resultado;
