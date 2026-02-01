-- Migration: Criar cliente especial "SEM PIX"
-- Data: 2026-02-01
-- Descrição: Cria cliente PIX especial para registrar transações onde não há troco PIX (troco = 0)
-- Caso de uso: Cliente paga exatamente o valor (ex: venda 1000, cheque 1000, troco 0)

-- Verificar se já existe cliente "SEM PIX"
-- Se não existir, criar

INSERT INTO clientes_pix (nome_completo, tipo_chave_pix, chave_pix, ativo, criado_em)
SELECT 'SEM PIX', 'SEM_PIX', 'N/A', 1, NOW()
FROM DUAL
WHERE NOT EXISTS (
    SELECT 1 FROM clientes_pix 
    WHERE nome_completo = 'SEM PIX' 
    OR tipo_chave_pix = 'SEM_PIX'
);

-- Nota: Este cliente especial não deve ser excluído ou editado manualmente
-- Ele é usado quando o troco é zero mas ainda assim precisa-se registrar a transação
-- e enviar mensagem no WhatsApp para controle

