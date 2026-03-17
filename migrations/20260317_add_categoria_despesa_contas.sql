-- Migration: 20260317_add_categoria_despesa_contas.sql
-- Tabela de vínculo entre categorias de despesas e contas contábeis por empresa.
-- Cada empresa possui o seu próprio Plano de Contas (grupo_contabil_id em clientes),
-- portanto o vínculo conta contábil ↔ categoria é sempre por empresa.
-- Idempotente (usa IF NOT EXISTS).

CREATE TABLE IF NOT EXISTS categoria_despesa_contas (
    id               INT          AUTO_INCREMENT PRIMARY KEY,
    categoria_id     INT          NOT NULL COMMENT 'Categoria de despesa',
    cliente_id       INT          NOT NULL COMMENT 'Empresa (posto/cliente) dona do vínculo',
    conta_contabil_id INT         NULL      COMMENT 'Conta do Plano de Contas Contábil da empresa',
    UNIQUE KEY uq_cdc_cat_cliente (categoria_id, cliente_id),
    CONSTRAINT fk_cdc_categoria FOREIGN KEY (categoria_id)
        REFERENCES categorias_despesas(id) ON DELETE CASCADE,
    CONSTRAINT fk_cdc_cliente FOREIGN KEY (cliente_id)
        REFERENCES clientes(id) ON DELETE CASCADE,
    CONSTRAINT fk_cdc_conta FOREIGN KEY (conta_contabil_id)
        REFERENCES plano_contas_contas(id) ON DELETE SET NULL
) COMMENT='Vínculo por empresa entre categorias de despesas e contas contábeis';

SELECT 'Migration 20260317_add_categoria_despesa_contas aplicada com sucesso.' AS resultado;
