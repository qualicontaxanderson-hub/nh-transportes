-- Migration: 20260327_fix_fgts_tipo
-- Description: Ensures FGTS rubrica has tipo='IMPOSTO' (not 'DESCONTO').
--   On some production environments FGTS was stored as tipo='DESCONTO',
--   causing it to be subtracted from the employee Total. The correct formula is:
--     Salário + FGTS + Benefícios + Comissão + Encargos - EMPRÉSTIMOS = Total
--   Only EMPRÉSTIMOS should subtract.

UPDATE rubricas
SET tipo = 'IMPOSTO'
WHERE nome = 'FGTS'
  AND tipo = 'DESCONTO';
