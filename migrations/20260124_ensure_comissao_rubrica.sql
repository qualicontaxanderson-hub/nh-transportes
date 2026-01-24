-- Migration to ensure Comissão rubrica exists
-- This is a safe migration that will only insert if the rubrica doesn't exist
-- Run this if the Comissão column is not appearing in the employee payroll form

INSERT INTO `rubricas` (`nome`, `descricao`, `tipo`, `percentualouvalorfixo`, `ativo`, `ordem`) 
VALUES ('Comissão', 'Comissão sobre vendas/fretes', 'BENEFICIO', 'VALOR_FIXO', 1, 10)
ON DUPLICATE KEY UPDATE 
    descricao = 'Comissão sobre vendas/fretes',
    tipo = 'BENEFICIO',
    ativo = 1,
    ordem = 10;
