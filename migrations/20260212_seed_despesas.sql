-- Seed data for expense categories based on requirements
-- Created: 2026-02-12
-- Run this after running 20260212_add_titulos_despesas.sql

-- Get titulo IDs
SET @titulo_operacionais = (SELECT id FROM titulos_despesas WHERE nome = 'DESPESAS OPERACIONAIS');
SET @titulo_impostos = (SELECT id FROM titulos_despesas WHERE nome = 'IMPOSTOS');
SET @titulo_financeiro = (SELECT id FROM titulos_despesas WHERE nome = 'FINANCEIRO');
SET @titulo_posto = (SELECT id FROM titulos_despesas WHERE nome = 'DESPESAS POSTO');
SET @titulo_funcionarios = (SELECT id FROM titulos_despesas WHERE nome = 'FUNCIONÁRIOS');
SET @titulo_veiculos = (SELECT id FROM titulos_despesas WHERE nome = 'VEICULOS EMPRESA');
SET @titulo_caminhoes = (SELECT id FROM titulos_despesas WHERE nome = 'CAMINHÕES');
SET @titulo_investimentos = (SELECT id FROM titulos_despesas WHERE nome = 'INVESTIMENTOS');
SET @titulo_pessoais = (SELECT id FROM titulos_despesas WHERE nome = 'DESPESAS PESSOAIS (MONICA)');

-- DESPESAS OPERACIONAIS (25 items)
INSERT INTO categorias_despesas (titulo_id, nome, ordem, ativo) VALUES
(@titulo_operacionais, 'ADVOGADO', 1, TRUE),
(@titulo_operacionais, 'CONTADOR', 2, TRUE),
(@titulo_operacionais, 'ALUGUEL', 3, TRUE),
(@titulo_operacionais, 'CARTÃO DE CREDITO - SANTANDER', 4, TRUE),
(@titulo_operacionais, 'CARTÃO DE CRÉDITO - CORA', 5, TRUE),
(@titulo_operacionais, 'INTERNET', 6, TRUE),
(@titulo_operacionais, 'ENGENHEIRO', 7, TRUE),
(@titulo_operacionais, 'ENERGIA', 8, TRUE),
(@titulo_operacionais, 'AGUA', 9, TRUE),
(@titulo_operacionais, 'GRAFICA - BOIÃO', 10, TRUE),
(@titulo_operacionais, 'GRAFICA - IDEIAS', 11, TRUE),
(@titulo_operacionais, 'FRETES TERCEIROS', 12, TRUE),
(@titulo_operacionais, 'MATERIAIS DE LIMPEZA', 13, TRUE),
(@titulo_operacionais, 'MATERIAIS ELÉTRICOS', 14, TRUE),
(@titulo_operacionais, 'MATERIAIS DE CONSTRUÇÃO', 15, TRUE),
(@titulo_operacionais, 'SISTEMA - SOFTWARE', 16, TRUE),
(@titulo_operacionais, 'MECANICO', 17, TRUE),
(@titulo_operacionais, 'SERVIÇOS DE ELETRICISTAS', 18, TRUE),
(@titulo_operacionais, 'SERVIÇOS DE PINTURAS', 19, TRUE),
(@titulo_operacionais, 'SERVIÇOS DE REFORMAS', 20, TRUE),
(@titulo_operacionais, 'SERVIÇOS DE SERRALHERIA', 21, TRUE),
(@titulo_operacionais, 'SEGUROS EMPRESARIAIS', 22, TRUE),
(@titulo_operacionais, 'TELEFONE MÓVEL', 23, TRUE),
(@titulo_operacionais, 'PROPAGANDAS', 24, TRUE);

-- IMPOSTOS (12 items)
INSERT INTO categorias_despesas (titulo_id, nome, ordem, ativo) VALUES
(@titulo_impostos, 'IBAMA', 1, TRUE),
(@titulo_impostos, 'FUNAPE', 2, TRUE),
(@titulo_impostos, 'IMPOSTO DE RENDA - IRPJ', 3, TRUE),
(@titulo_impostos, 'CONTRIBUIÇÃO SOCIAL - CSLL', 4, TRUE),
(@titulo_impostos, 'DARE ICMS', 5, TRUE),
(@titulo_impostos, 'TAXAS TESOURO', 6, TRUE),
(@titulo_impostos, 'TAXA TRIBUNAL DE JUSTIÇA', 7, TRUE),
(@titulo_impostos, 'INMETRO', 8, TRUE),
(@titulo_impostos, 'AMBIENTAL', 9, TRUE),
(@titulo_impostos, 'TX MUNICIPAL', 10, TRUE),
(@titulo_impostos, 'IPTU', 11, TRUE),
(@titulo_impostos, 'DAS PREST', 12, TRUE);

-- FINANCEIRO (8 items)
INSERT INTO categorias_despesas (titulo_id, nome, ordem, ativo) VALUES
(@titulo_financeiro, 'CESTA DE RELACIONAMENTO - SICREDI', 1, TRUE),
(@titulo_financeiro, 'BOLETOS', 2, TRUE),
(@titulo_financeiro, 'TARIFA BANCÁRIA - SANTANDER', 3, TRUE),
(@titulo_financeiro, 'TARIFA PIX - SANTANDER', 4, TRUE),
(@titulo_financeiro, 'CARTÃO DE DEBITO - SICREDI', 5, TRUE),
(@titulo_financeiro, 'CARTÃO DE CREDITO - SICREDI', 6, TRUE),
(@titulo_financeiro, 'CARTÃO DE CREDITO - SICREDI ANTECIPAÇÃO', 7, TRUE),
(@titulo_financeiro, 'IOF SANTANDER', 8, TRUE);

-- DESPESAS POSTO (8 items)
INSERT INTO categorias_despesas (titulo_id, nome, ordem, ativo) VALUES
(@titulo_posto, 'MATERIAIS DE ESCRITÓRIO', 1, TRUE),
(@titulo_posto, 'MATERIAIS ELETRICOS', 2, TRUE),
(@titulo_posto, 'MANUTENÇÃO DIVERSAS', 3, TRUE),
(@titulo_posto, 'FUNCIONÁRIOS POSTO', 4, TRUE),
(@titulo_posto, 'MATERIAIS LIMPEZA', 5, TRUE),
(@titulo_posto, 'DESPESAS POP', 6, TRUE),
(@titulo_posto, 'SOBRAS DE CAIXA', 7, TRUE),
(@titulo_posto, 'FALTA DE CAIXA', 8, TRUE);

-- FUNCIONÁRIOS (7 items - note: some will integrate with existing system)
INSERT INTO categorias_despesas (titulo_id, nome, ordem, ativo) VALUES
(@titulo_funcionarios, 'FGTS', 1, TRUE),
(@titulo_funcionarios, 'VALE ALIMENTAÇÃO', 2, TRUE),
(@titulo_funcionarios, 'BENEFICIO SOCIAL', 3, TRUE),
(@titulo_funcionarios, 'ODONTO BENEFICIO SOCIAL', 4, TRUE),
(@titulo_funcionarios, 'FUNCIONÁRIOS', 5, TRUE),
(@titulo_funcionarios, 'FÉRIAS', 6, TRUE),
(@titulo_funcionarios, 'UNIFORMES', 7, TRUE);

-- VEICULOS EMPRESA (6 items with subcategories)
INSERT INTO categorias_despesas (titulo_id, nome, ordem, ativo) VALUES
(@titulo_veiculos, 'FIORINO', 1, TRUE),
(@titulo_veiculos, 'POP', 2, TRUE);

-- Get categoria IDs for subcategories
SET @cat_fiorino = (SELECT id FROM categorias_despesas WHERE nome = 'FIORINO' AND titulo_id = @titulo_veiculos);
SET @cat_pop = (SELECT id FROM categorias_despesas WHERE nome = 'POP' AND titulo_id = @titulo_veiculos);

-- FIORINO subcategories
INSERT INTO subcategorias_despesas (categoria_id, nome, ordem, ativo) VALUES
(@cat_fiorino, 'DOCUMENTOS IPVA/MULTA', 1, TRUE),
(@cat_fiorino, 'ABASTECIMENTOS', 2, TRUE),
(@cat_fiorino, 'MANUTENÇÃO', 3, TRUE);

-- POP subcategories
INSERT INTO subcategorias_despesas (categoria_id, nome, ordem, ativo) VALUES
(@cat_pop, 'DOCUMENTOS IPVA/MULTA', 1, TRUE),
(@cat_pop, 'ABASTECIMENTOS', 2, TRUE),
(@cat_pop, 'MANUTENÇÃO', 3, TRUE);

-- CAMINHÕES (2 trucks with 15 categories each)
INSERT INTO categorias_despesas (titulo_id, nome, ordem, ativo) VALUES
(@titulo_caminhoes, 'VEICULO CARRETA MODELO SCANIA R500', 1, TRUE),
(@titulo_caminhoes, 'VEICULO TRUCK MODELO ACTROS 1620', 2, TRUE);

-- Get categoria IDs for truck subcategories
SET @cat_scania = (SELECT id FROM categorias_despesas WHERE nome = 'VEICULO CARRETA MODELO SCANIA R500');
SET @cat_actros = (SELECT id FROM categorias_despesas WHERE nome = 'VEICULO TRUCK MODELO ACTROS 1620');

-- SCANIA R500 subcategories (15 items)
INSERT INTO subcategorias_despesas (categoria_id, nome, ordem, ativo) VALUES
(@cat_scania, 'FATURAMENTO DO VEICULOS', 1, TRUE),
(@cat_scania, 'MOTORISTA', 2, TRUE),
(@cat_scania, 'MOTORISTA ADICIONAL', 3, TRUE),
(@cat_scania, 'COMISSÃO DO MOTORISTA', 4, TRUE),
(@cat_scania, 'FGTS', 5, TRUE),
(@cat_scania, 'VALE ALIMENTAÇÃO', 6, TRUE),
(@cat_scania, 'BENEFICIO SOCIAL', 7, TRUE),
(@cat_scania, 'ODONTO BENEFICIO SOCIAL', 8, TRUE),
(@cat_scania, 'COMISSÃO CT-e', 9, TRUE),
(@cat_scania, 'COMBUSTIVEL', 10, TRUE),
(@cat_scania, 'PEDAGIOS', 11, TRUE),
(@cat_scania, 'SASCAR', 12, TRUE),
(@cat_scania, 'DOCUMENTOS CAMINHÃO', 13, TRUE),
(@cat_scania, 'MULTAS', 14, TRUE),
(@cat_scania, 'MANUTENÇÃO CAMINHÃO', 15, TRUE),
(@cat_scania, 'PEÇAS CAMINHÃO', 16, TRUE),
(@cat_scania, 'PNEUS', 17, TRUE),
(@cat_scania, 'LAVAJATO', 18, TRUE),
(@cat_scania, 'SEGURO', 19, TRUE);

-- ACTROS 1620 subcategories (15 items - same as SCANIA)
INSERT INTO subcategorias_despesas (categoria_id, nome, ordem, ativo) VALUES
(@cat_actros, 'FATURAMENTO DO VEICULOS', 1, TRUE),
(@cat_actros, 'MOTORISTA', 2, TRUE),
(@cat_actros, 'MOTORISTA ADICIONAL', 3, TRUE),
(@cat_actros, 'COMISSÃO DO MOTORISTA', 4, TRUE),
(@cat_actros, 'FGTS', 5, TRUE),
(@cat_actros, 'VALE ALIMENTAÇÃO', 6, TRUE),
(@cat_actros, 'BENEFICIO SOCIAL', 7, TRUE),
(@cat_actros, 'ODONTO BENEFICIO SOCIAL', 8, TRUE),
(@cat_actros, 'COMISSÃO CT-e', 9, TRUE),
(@cat_actros, 'COMBUSTIVEL', 10, TRUE),
(@cat_actros, 'PEDAGIOS', 11, TRUE),
(@cat_actros, 'SASCAR', 12, TRUE),
(@cat_actros, 'DOCUMENTOS CAMINHÃO', 13, TRUE),
(@cat_actros, 'MULTAS', 14, TRUE),
(@cat_actros, 'MANUTENÇÃO CAMINHÃO', 15, TRUE),
(@cat_actros, 'PEÇAS CAMINHÃO', 16, TRUE),
(@cat_actros, 'PNEUS', 17, TRUE),
(@cat_actros, 'LAVAJATO', 18, TRUE),
(@cat_actros, 'SEGURO', 19, TRUE);

-- INVESTIMENTOS (4 items)
INSERT INTO categorias_despesas (titulo_id, nome, ordem, ativo) VALUES
(@titulo_investimentos, 'INTEGRALIZAÇÃO CAPITAL - SICREDI', 1, TRUE),
(@titulo_investimentos, 'CONSÓRCIO - SANTANDER', 2, TRUE),
(@titulo_investimentos, 'APLICAÇÃO DE FUNDOS - SICREDI', 3, TRUE),
(@titulo_investimentos, '(-) RESGATE DE FUNDOS - SICREDI', 4, TRUE);

-- DESPESAS PESSOAIS (MONICA) (15+ items with subcategories)
INSERT INTO categorias_despesas (titulo_id, nome, ordem, ativo) VALUES
(@titulo_pessoais, 'CARTÃO CARREFOUR', 1, TRUE),
(@titulo_pessoais, 'CARTÃO NUBANK', 2, TRUE),
(@titulo_pessoais, 'MARIA HELENA', 3, TRUE),
(@titulo_pessoais, 'RODRIGO', 4, TRUE),
(@titulo_pessoais, 'ABASTECIMENTOS', 5, TRUE),
(@titulo_pessoais, 'UNIMED', 6, TRUE),
(@titulo_pessoais, 'FACULDADE', 7, TRUE),
(@titulo_pessoais, 'COLÉGIO - DRUMMOND', 8, TRUE),
(@titulo_pessoais, 'SÃO SIMÃO', 9, TRUE),
(@titulo_pessoais, 'ANAPOLIS', 10, TRUE),
(@titulo_pessoais, 'CASA GOIATUBA', 11, TRUE),
(@titulo_pessoais, 'MORRINHOS RECANTO DAS ARARAS', 12, TRUE),
(@titulo_pessoais, 'BR-153', 13, TRUE),
(@titulo_pessoais, 'VEICULO COMMANDER', 14, TRUE),
(@titulo_pessoais, 'VEICULO F-250', 15, TRUE),
(@titulo_pessoais, 'DIVERSOS', 16, TRUE);

-- Get categoria IDs for personal expense subcategories
SET @cat_sao_simao = (SELECT id FROM categorias_despesas WHERE nome = 'SÃO SIMÃO' AND titulo_id = @titulo_pessoais);
SET @cat_anapolis = (SELECT id FROM categorias_despesas WHERE nome = 'ANAPOLIS' AND titulo_id = @titulo_pessoais);
SET @cat_goiatuba = (SELECT id FROM categorias_despesas WHERE nome = 'CASA GOIATUBA' AND titulo_id = @titulo_pessoais);
SET @cat_morrinhos = (SELECT id FROM categorias_despesas WHERE nome = 'MORRINHOS RECANTO DAS ARARAS' AND titulo_id = @titulo_pessoais);
SET @cat_br153 = (SELECT id FROM categorias_despesas WHERE nome = 'BR-153' AND titulo_id = @titulo_pessoais);
SET @cat_commander = (SELECT id FROM categorias_despesas WHERE nome = 'VEICULO COMMANDER' AND titulo_id = @titulo_pessoais);
SET @cat_f250 = (SELECT id FROM categorias_despesas WHERE nome = 'VEICULO F-250' AND titulo_id = @titulo_pessoais);
SET @cat_diversos = (SELECT id FROM categorias_despesas WHERE nome = 'DIVERSOS' AND titulo_id = @titulo_pessoais);

-- Subcategories for properties (PARCELA and IPTU)
INSERT INTO subcategorias_despesas (categoria_id, nome, ordem, ativo) VALUES
(@cat_sao_simao, 'PARCELA', 1, TRUE),
(@cat_sao_simao, 'IPTU', 2, TRUE),
(@cat_anapolis, 'PARCELA', 1, TRUE),
(@cat_anapolis, 'IPTU', 2, TRUE),
(@cat_goiatuba, 'PARCELA', 1, TRUE),
(@cat_goiatuba, 'IPTU', 2, TRUE),
(@cat_morrinhos, 'PARCELA', 1, TRUE),
(@cat_morrinhos, 'IPTU', 2, TRUE),
(@cat_br153, 'PARCELA', 1, TRUE),
(@cat_br153, 'IPTU', 2, TRUE);

-- Subcategories for vehicles (IPVA, SEGURO, DESPACHANTE, ABASTECIMENTO)
INSERT INTO subcategorias_despesas (categoria_id, nome, ordem, ativo) VALUES
(@cat_commander, 'IPVA', 1, TRUE),
(@cat_commander, 'SEGURO', 2, TRUE),
(@cat_commander, 'DESPACHANTE', 3, TRUE),
(@cat_commander, 'ABASTECIMENTO', 4, TRUE),
(@cat_f250, 'IPVA', 1, TRUE),
(@cat_f250, 'SEGURO', 2, TRUE),
(@cat_f250, 'DESPACHANTE', 3, TRUE),
(@cat_f250, 'ABASTECIMENTO', 4, TRUE);

-- Subcategories for DIVERSOS
INSERT INTO subcategorias_despesas (categoria_id, nome, ordem, ativo) VALUES
(@cat_diversos, 'VESTIMENTA', 1, TRUE);
