-- Adiciona coluna cliente_id nas tabelas ARLA para suporte multi-cliente
-- Data: 2026-01-21

-- Adiciona cliente_id na tabela arla_compras
ALTER TABLE arla_compras 
ADD COLUMN cliente_id INT NULL,
ADD FOREIGN KEY (cliente_id) REFERENCES clientes(id);

-- Adiciona cliente_id na tabela arla_lancamentos
ALTER TABLE arla_lancamentos 
ADD COLUMN cliente_id INT NULL,
ADD FOREIGN KEY (cliente_id) REFERENCES clientes(id);

-- Adiciona cliente_id na tabela arla_saldo_inicial
ALTER TABLE arla_saldo_inicial 
ADD COLUMN cliente_id INT NULL,
ADD FOREIGN KEY (cliente_id) REFERENCES clientes(id);

-- Adiciona cliente_id na tabela arla_precos_venda
ALTER TABLE arla_precos_venda 
ADD COLUMN cliente_id INT NULL,
ADD FOREIGN KEY (cliente_id) REFERENCES clientes(id);

-- Atualiza registros existentes com cliente_id = 1 (cliente padrão atual)
UPDATE arla_compras SET cliente_id = 1 WHERE cliente_id IS NULL;
UPDATE arla_lancamentos SET cliente_id = 1 WHERE cliente_id IS NULL;
UPDATE arla_saldo_inicial SET cliente_id = 1 WHERE cliente_id IS NULL;
UPDATE arla_precos_venda SET cliente_id = 1 WHERE cliente_id IS NULL;

-- Torna a coluna NOT NULL após atualizar os registros existentes
ALTER TABLE arla_compras MODIFY COLUMN cliente_id INT NOT NULL;
ALTER TABLE arla_lancamentos MODIFY COLUMN cliente_id INT NOT NULL;
ALTER TABLE arla_saldo_inicial MODIFY COLUMN cliente_id INT NOT NULL;
ALTER TABLE arla_precos_venda MODIFY COLUMN cliente_id INT NOT NULL;
