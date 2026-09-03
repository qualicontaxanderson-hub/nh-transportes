-- Preco da mercadoria com QUATRO casas decimais.
--
-- A tela do PED/FRETE ja aceitava tres casas, mas a coluna era DECIMAL(10,2):
-- o operador digitava 5,362 e o banco guardava 5,36. O frete 2787 (03/09/2026)
-- e o flagrante -- preco 5.36 com total_nf_compra 53.620,00, que so fecha com
-- 5,362. Ou seja, a terceira casa vinha sendo perdida calada desde sempre, e o
-- total passava a nao bater com preco x litros.
--
-- Agora vao QUATRO casas, que e o que a distribuidora pratica (5,3629).
--
-- Alargar a escala NAO perde dado: 5.36 vira 5.3600. E cabe com folga --
-- DECIMAL(10,4) chega a 999.999,9999 e o maior preco do banco e 7,44
-- (conferido em 03/09/2026, 2.223 fretes e 1.730 itens de pedido).
--
-- As duas colunas mudam juntas de proposito: `pedidos_itens.preco_unitario`
-- recebe o MESMO numero que `fretes.preco_produto_unitario` na mesma gravacao,
-- e uma com 4 casas e a outra com 3 fariam as duas telas discordarem.
ALTER TABLE fretes         MODIFY preco_produto_unitario DECIMAL(10,4) NOT NULL;
ALTER TABLE pedidos_itens  MODIFY preco_unitario         DECIMAL(10,4) NOT NULL
