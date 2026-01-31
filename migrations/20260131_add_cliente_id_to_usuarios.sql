-- Migration: Adicionar cliente_id na tabela usuarios
-- Data: 2026-01-31
-- Descrição: Associa usuários PISTA a seus postos para isolamento de dados
-- Autor: GitHub Copilot Agent

-- Adicionar coluna cliente_id
ALTER TABLE usuarios 
ADD COLUMN cliente_id INT NULL 
COMMENT 'Posto associado (para usuários PISTA - isolamento de dados)';

-- Adicionar foreign key para garantir integridade referencial
ALTER TABLE usuarios 
ADD CONSTRAINT fk_usuarios_cliente 
FOREIGN KEY (cliente_id) REFERENCES clientes(id)
ON DELETE SET NULL
ON UPDATE CASCADE;

-- Adicionar índice para melhorar performance de queries filtradas
ALTER TABLE usuarios 
ADD INDEX idx_usuarios_cliente (cliente_id);

-- Atualizar comentário da tabela
ALTER TABLE usuarios 
COMMENT = 'Usuários do sistema com níveis de acesso (ADMIN/PISTA) e postos associados';

-- Verificação: Listar estrutura atualizada (comentar após executar)
-- SHOW COLUMNS FROM usuarios;

/*
INSTRUÇÕES DE USO:

1. Executar esta migration no banco de dados de produção

2. Após executar, criar usuários PISTA por posto:
   Exemplo:
   - Usuário: NH_GBTA
   - Senha: 1234 (ou senha segura)
   - Nível: PISTA
   - cliente_id: (ID do POSTO NOVO HORIZONTE GOIATUBA LTDA)

3. Para cada posto que precisar de acesso:
   INSERT INTO usuarios (username, nome_completo, nivel, cliente_id, ativo, senha_hash)
   VALUES ('NH_GBTA', 'NH Goiatuba', 'PISTA', (SELECT id FROM clientes WHERE razao_social LIKE '%GOIATUBA%'), 1, 'hash_aqui');

4. Verificar isolamento:
   - Login com usuário PISTA deve ver apenas transações do seu posto
   - Login com ADMIN deve ver todas as transações

ROLLBACK (se necessário):
-- ALTER TABLE usuarios DROP FOREIGN KEY fk_usuarios_cliente;
-- ALTER TABLE usuarios DROP INDEX idx_usuarios_cliente;
-- ALTER TABLE usuarios DROP COLUMN cliente_id;
*/
