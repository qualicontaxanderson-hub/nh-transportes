-- Migration: Criar tabela de Fornecedores de Despesas
-- Data: 2026-02-15
-- Descrição: Tabela para cadastrar fornecedores vinculados a categorias de despesas

CREATE TABLE IF NOT EXISTS despesas_fornecedores (
    id INT AUTO_INCREMENT PRIMARY KEY,
    nome VARCHAR(200) NOT NULL,
    categoria_id INT NOT NULL,
    ativo TINYINT(1) DEFAULT 1,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (categoria_id) REFERENCES categorias_despesas(id),
    INDEX idx_despesas_fornecedores_categoria (categoria_id),
    INDEX idx_despesas_fornecedores_ativo (ativo)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Comentários
ALTER TABLE despesas_fornecedores 
COMMENT = 'Fornecedores de despesas vinculados a categorias específicas';
