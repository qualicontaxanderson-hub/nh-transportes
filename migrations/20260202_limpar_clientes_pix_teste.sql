-- Migration: Limpar clientes PIX de teste
-- Data: 02/02/2026
-- Descrição: Remove clientes PIX que foram criados apenas para teste
--            Mantém apenas o cliente "SEM PIX" (id=5) que é necessário para o sistema

-- IDs a excluir:
-- ID 1: ANDERSON ANTUNES VIEIRA (ativo=1) - teste
-- ID 2: ANDERSON ANTUNES VIEIRA (ativo=0) - teste duplicado inativo
-- ID 6: QUALICONTAX ASSESSORIA CONTABIL LTDA (ativo=0) - teste
-- ID 7: AUTO POSYO (ativo=1) - teste (com erro no nome)
-- ID 8: MONICA VIEIRA (ativo=1) - teste

-- Manter:
-- ID 5: SEM PIX - cliente especial necessário para transações sem PIX

-- IMPORTANTE: Verificar se existem transações vinculadas a estes clientes antes de excluir
-- Se houver transações, considerar apenas desativar (ativo=0) ao invés de excluir

-- Verificar se existem transações vinculadas
SELECT 
    tpc.id,
    tpc.nome_completo,
    COUNT(tp.id) as total_transacoes
FROM troco_pix_clientes tpc
LEFT JOIN troco_pix tp ON tp.troco_pix_cliente_id = tpc.id
WHERE tpc.id IN (1, 2, 6, 7, 8)
GROUP BY tpc.id, tpc.nome_completo;

-- Se não houver transações vinculadas, excluir
DELETE FROM troco_pix_clientes 
WHERE id IN (1, 2, 6, 7, 8)
  AND id NOT IN (SELECT DISTINCT troco_pix_cliente_id FROM troco_pix WHERE troco_pix_cliente_id IS NOT NULL);

-- Se houver transações vinculadas, apenas desativar
UPDATE troco_pix_clientes 
SET ativo = 0, 
    atualizado_em = NOW()
WHERE id IN (1, 2, 6, 7, 8)
  AND id IN (SELECT DISTINCT troco_pix_cliente_id FROM troco_pix WHERE troco_pix_cliente_id IS NOT NULL);

-- Verificar resultado final (deve mostrar apenas o cliente SEM PIX e outros clientes válidos)
SELECT 
    id, 
    nome_completo, 
    tipo_chave_pix, 
    chave_pix, 
    ativo,
    criado_em
FROM troco_pix_clientes 
WHERE ativo = 1
ORDER BY id;
