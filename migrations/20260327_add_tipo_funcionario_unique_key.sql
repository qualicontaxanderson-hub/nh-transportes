-- ============================================================
-- Adiciona tipo_funcionario à unique key de lancamentosfuncionarios_v2
-- ============================================================
-- Contexto:
--   funcionarios.id e motoristas.id são AUTO_INCREMENT independentes e
--   podem ter o mesmo valor (ex.: João Batista funcionarios.id=1 e
--   VALMIR motoristas.id=1; Roberta funcionarios.id=2 e Marcos id=2).
--   Sem tipo_funcionario na unique key, salvar o Salário do Valmir
--   (tipo='motorista', fid=1) sobrescreve o Salário do João
--   (tipo='funcionario', fid=1) via ON DUPLICATE KEY UPDATE — ou,
--   sem qualquer unique key, o repair apaga o registro correto do João.
--
-- 1. Garante que a coluna existe (pode já ter sido criada pelo Python).
-- 2. Remove duplicatas dentro do mesmo tipo (mantém o registro mais recente).
-- 3. Cria a unique key se ainda não existir.
-- ============================================================

-- 1. Adiciona coluna se ainda não existir
ALTER TABLE lancamentosfuncionarios_v2
    ADD COLUMN IF NOT EXISTS tipo_funcionario VARCHAR(12) NOT NULL DEFAULT 'funcionario';

-- 2. Remove linhas duplicadas dentro do mesmo (clienteid, funcionarioid,
--    mes, rubricaid, tipo_funcionario), mantendo o de maior id.
DELETE lf1 FROM lancamentosfuncionarios_v2 lf1
INNER JOIN lancamentosfuncionarios_v2 lf2
    ON  lf1.clienteid        = lf2.clienteid
    AND lf1.funcionarioid    = lf2.funcionarioid
    AND lf1.mes              = lf2.mes
    AND lf1.rubricaid        = lf2.rubricaid
    AND lf1.tipo_funcionario = lf2.tipo_funcionario
    AND lf1.id < lf2.id;

-- 3. Cria a unique key (idempotente via IF NOT EXISTS no MySQL 8+ / MariaDB;
--    no Railway/MySQL 5.7 o script ignora se já existir pelo guard acima).
ALTER TABLE lancamentosfuncionarios_v2
    ADD UNIQUE KEY IF NOT EXISTS uq_lancamento_tipo
        (clienteid, funcionarioid, mes, rubricaid, tipo_funcionario);
