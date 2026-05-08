-- Adiciona as quantidades 9.000 litros e 12.000 litros na tabela de quantidades
-- usada nos pedidos e fretes, caso ainda não existam.

INSERT IGNORE INTO quantidades (valor, descricao)
VALUES (9000, '9.000 litros');

INSERT IGNORE INTO quantidades (valor, descricao)
VALUES (12000, '12.000 litros');
