-- ============================================================
-- SCRIPT SQL PARA INTEGRAÇÃO COM API EFI BANK (PIX/BOLETO)
-- NH Transportes - Sistema de Gestão de Fretes
-- Execute este script no banco de dados Railway
-- ============================================================

-- Tabela de configuração da API EFI
CREATE TABLE IF NOT EXISTS efi_config (
    id INT AUTO_INCREMENT PRIMARY KEY,
    client_id VARCHAR(100) NOT NULL COMMENT 'Client ID da aplicação EFI',
    client_secret VARCHAR(255) NOT NULL COMMENT 'Client Secret da aplicação EFI',
    certificado_pem TEXT NULL COMMENT 'Conteúdo do certificado .pem (Base64)',
    chave_pix VARCHAR(100) NULL COMMENT 'Chave PIX cadastrada na conta EFI',
    ambiente ENUM('sandbox', 'producao') NOT NULL DEFAULT 'sandbox' COMMENT 'Ambiente da API',
    webhook_url VARCHAR(255) NULL COMMENT 'URL para receber notificações',
    ativo BOOLEAN DEFAULT TRUE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Tabela de cobranças (PIX e Boleto)
CREATE TABLE IF NOT EXISTS cobrancas (
    id INT AUTO_INCREMENT PRIMARY KEY,
    
    -- Relacionamentos
    frete_id INT NULL COMMENT 'ID do frete relacionado',
    cliente_id INT NULL COMMENT 'ID do cliente',
    
    -- Dados do pagador
    pagador_nome VARCHAR(200) NOT NULL,
    pagador_cpf_cnpj VARCHAR(18) NOT NULL,
    pagador_email VARCHAR(100) NULL,
    pagador_telefone VARCHAR(20) NULL,
    pagador_endereco VARCHAR(255) NULL,
    pagador_cidade VARCHAR(100) NULL,
    pagador_uf VARCHAR(2) NULL,
    pagador_cep VARCHAR(10) NULL,
    
    -- Dados da cobrança
    tipo ENUM('pix', 'boleto') NOT NULL DEFAULT 'pix',
    valor DECIMAL(10,2) NOT NULL,
    descricao VARCHAR(255) NOT NULL,
    
    -- Dados EFI - PIX
    txid VARCHAR(35) NULL COMMENT 'ID da transação PIX',
    location VARCHAR(255) NULL COMMENT 'Location do PIX',
    qrcode_base64 TEXT NULL COMMENT 'QR Code em Base64',
    pix_copia_cola TEXT NULL COMMENT 'Código PIX copia e cola',
    
    -- Dados EFI - Boleto
    nosso_numero VARCHAR(20) NULL,
    codigo_barras VARCHAR(60) NULL,
    linha_digitavel VARCHAR(60) NULL,
    link_boleto VARCHAR(255) NULL,
    
    -- Controle
    status ENUM('pendente', 'aguardando', 'pago', 'cancelado', 'expirado', 'erro') 
        NOT NULL DEFAULT 'pendente',
    data_vencimento DATE NULL,
    data_pagamento DATETIME NULL,
    valor_pago DECIMAL(10,2) NULL,
    
    -- Resposta da API
    efi_response JSON NULL COMMENT 'Resposta completa da API EFI',
    mensagem_erro TEXT NULL,
    
    -- Timestamps
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    -- Índices e chaves estrangeiras
    INDEX idx_frete (frete_id),
    INDEX idx_cliente (cliente_id),
    INDEX idx_txid (txid),
    INDEX idx_status (status),
    INDEX idx_tipo (tipo),
    INDEX idx_data_vencimento (data_vencimento),
    INDEX idx_status_tipo_vencimento (status, tipo, data_vencimento),
    
    CONSTRAINT fk_cobranca_frete 
        FOREIGN KEY (frete_id) REFERENCES fretes(id) 
        ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT fk_cobranca_cliente 
        FOREIGN KEY (cliente_id) REFERENCES clientes(id) 
        ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Tabela de histórico/log de transações
CREATE TABLE IF NOT EXISTS cobrancas_log (
    id INT AUTO_INCREMENT PRIMARY KEY,
    cobranca_id INT NOT NULL,
    acao VARCHAR(50) NOT NULL COMMENT 'criacao, atualizacao, pagamento, cancelamento, etc',
    dados_anteriores JSON NULL,
    dados_novos JSON NULL,
    ip_origem VARCHAR(45) NULL,
    usuario_id INT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    
    INDEX idx_cobranca (cobranca_id),
    INDEX idx_acao (acao),
    
    CONSTRAINT fk_log_cobranca 
        FOREIGN KEY (cobranca_id) REFERENCES cobrancas(id) 
        ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================
-- INSTRUÇÕES DE USO:
-- 1. Copie este script
-- 2. Acesse o Railway e conecte no banco MySQL
-- 3. Execute o script para criar as tabelas
-- 4. Configure as credenciais na tabela efi_config
-- ============================================================
