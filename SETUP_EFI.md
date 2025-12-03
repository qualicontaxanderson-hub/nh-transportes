# Integração API EFI Bank - NH Transportes

Este documento contém todas as instruções para configurar a integração com a API de cobranças do Banco EFI (PIX e Boleto) no sistema NH Transportes.

## 📋 Índice

1. [Pré-requisitos](#pré-requisitos)
2. [Configuração do Banco de Dados](#configuração-do-banco-de-dados)
3. [Configuração no GitHub](#configuração-no-github)
4. [Configuração no Railway](#configuração-no-railway)
5. [Obter Credenciais EFI](#obter-credenciais-efi)
6. [Usar o Sistema de Cobranças](#usar-o-sistema-de-cobranças)

---

## 🔧 Pré-requisitos

- Conta no [EFI Bank (Gerencianet)](https://gerencianet.com.br)
- Conta Jurídica aprovada para emissão de PIX e/ou Boleto
- Acesso ao Railway para deploy
- Acesso ao GitHub para configurar secrets

---

## 🗄️ Configuração do Banco de Dados

### Passo 1: Acessar o banco MySQL no Railway

1. Acesse o [Railway](https://railway.app)
2. Entre no seu projeto **nh-transportes**
3. Clique no serviço de **MySQL/Database**
4. Vá na aba **Query** ou use um cliente MySQL

### Passo 2: Executar o script SQL

Execute o script SQL localizado em `scripts/efi_cobrancas.sql`:

```sql
-- ============================================================
-- SCRIPT SQL PARA INTEGRAÇÃO COM API EFI BANK (PIX/BOLETO)
-- ============================================================

-- Tabela de configuração da API EFI
CREATE TABLE IF NOT EXISTS efi_config (
    id INT AUTO_INCREMENT PRIMARY KEY,
    client_id VARCHAR(100) NOT NULL COMMENT 'Client ID da aplicação EFI',
    client_secret VARCHAR(255) NOT NULL COMMENT 'Client Secret da aplicação EFI',
    certificado_pem TEXT NULL COMMENT 'Conteúdo do certificado .pem (Base64)',
    chave_pix VARCHAR(100) NULL COMMENT 'Chave PIX cadastrada na conta EFI',
    ambiente ENUM('sandbox', 'producao') NOT NULL DEFAULT 'sandbox',
    webhook_url VARCHAR(255) NULL COMMENT 'URL para receber notificações',
    ativo BOOLEAN DEFAULT TRUE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Tabela de cobranças (PIX e Boleto)
CREATE TABLE IF NOT EXISTS cobrancas (
    id INT AUTO_INCREMENT PRIMARY KEY,
    frete_id INT NULL,
    cliente_id INT NULL,
    pagador_nome VARCHAR(200) NOT NULL,
    pagador_cpf_cnpj VARCHAR(18) NOT NULL,
    pagador_email VARCHAR(100) NULL,
    pagador_telefone VARCHAR(20) NULL,
    pagador_endereco VARCHAR(255) NULL,
    pagador_cidade VARCHAR(100) NULL,
    pagador_uf VARCHAR(2) NULL,
    pagador_cep VARCHAR(10) NULL,
    tipo ENUM('pix', 'boleto') NOT NULL DEFAULT 'pix',
    valor DECIMAL(10,2) NOT NULL,
    descricao VARCHAR(255) NOT NULL,
    txid VARCHAR(35) NULL,
    location VARCHAR(255) NULL,
    qrcode_base64 TEXT NULL,
    pix_copia_cola TEXT NULL,
    nosso_numero VARCHAR(20) NULL,
    codigo_barras VARCHAR(60) NULL,
    linha_digitavel VARCHAR(60) NULL,
    link_boleto VARCHAR(255) NULL,
    status ENUM('pendente', 'aguardando', 'pago', 'cancelado', 'expirado', 'erro') 
        NOT NULL DEFAULT 'pendente',
    data_vencimento DATE NULL,
    data_pagamento DATETIME NULL,
    valor_pago DECIMAL(10,2) NULL,
    efi_response JSON NULL,
    mensagem_erro TEXT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_frete (frete_id),
    INDEX idx_cliente (cliente_id),
    INDEX idx_txid (txid),
    INDEX idx_status (status),
    CONSTRAINT fk_cobranca_frete 
        FOREIGN KEY (frete_id) REFERENCES fretes(id) 
        ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT fk_cobranca_cliente 
        FOREIGN KEY (cliente_id) REFERENCES clientes(id) 
        ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Tabela de log
CREATE TABLE IF NOT EXISTS cobrancas_log (
    id INT AUTO_INCREMENT PRIMARY KEY,
    cobranca_id INT NOT NULL,
    acao VARCHAR(50) NOT NULL,
    dados_anteriores JSON NULL,
    dados_novos JSON NULL,
    ip_origem VARCHAR(45) NULL,
    usuario_id INT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_cobranca (cobranca_id),
    CONSTRAINT fk_log_cobranca 
        FOREIGN KEY (cobranca_id) REFERENCES cobrancas(id) 
        ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

---

## 🔐 Configuração no GitHub

### Secrets a serem criados

Vá em **Settings > Secrets and variables > Actions** no seu repositório e adicione:

| Nome do Secret | Descrição | Exemplo |
|----------------|-----------|---------|
| `EFI_CLIENT_ID` | Client ID da aplicação EFI | `Client_Id_abc123...` |
| `EFI_CLIENT_SECRET` | Client Secret da aplicação EFI | `Client_Secret_xyz789...` |
| `EFI_CERTIFICADO_PEM` | Conteúdo do certificado .pem em Base64 | (ver instruções abaixo) |
| `EFI_CHAVE_PIX` | Sua chave PIX cadastrada | `email@empresa.com` ou chave aleatória |
| `EFI_AMBIENTE` | Ambiente da API | `sandbox` ou `producao` |

### Como converter o certificado para Base64

No terminal Linux/Mac:
```bash
base64 -w 0 seu_certificado.pem > certificado_base64.txt
```

No Windows PowerShell:
```powershell
[Convert]::ToBase64String([IO.File]::ReadAllBytes("seu_certificado.pem")) | Out-File certificado_base64.txt
```

Copie o conteúdo do arquivo gerado para o secret `EFI_CERTIFICADO_PEM`.

---

## 🚂 Configuração no Railway

### Variáveis de ambiente a configurar

No seu projeto Railway, vá em **Variables** e adicione:

| Variável | Valor |
|----------|-------|
| `EFI_CLIENT_ID` | Seu Client ID |
| `EFI_CLIENT_SECRET` | Seu Client Secret |
| `EFI_CERTIFICADO_PEM` | Certificado em Base64 |
| `EFI_CHAVE_PIX` | Sua chave PIX |
| `EFI_AMBIENTE` | `sandbox` ou `producao` |

**⚠️ IMPORTANTE:** Use `sandbox` para testes antes de ir para produção!

---

## 🏦 Obter Credenciais EFI

### Passo 1: Criar conta EFI

1. Acesse [gerencianet.com.br](https://gerencianet.com.br)
2. Crie uma conta PJ (pessoa jurídica)
3. Complete a verificação de identidade

### Passo 2: Criar aplicação

1. Após login, vá em **API > Aplicações**
2. Clique em **Nova Aplicação**
3. Preencha:
   - Nome: `NH Transportes`
   - Tipo: `Servidor (Backend)`
4. Salve e copie o **Client ID** e **Client Secret**

### Passo 3: Gerar certificado PIX

1. Na mesma página da aplicação, vá em **Certificados**
2. Clique em **Novo Certificado**
3. Baixe o arquivo `.pem`
4. **Guarde este arquivo com segurança!**

### Passo 4: Cadastrar chave PIX

1. Vá em **PIX > Minhas Chaves**
2. Cadastre uma chave (CPF, CNPJ, E-mail ou Aleatória)
3. Copie a chave cadastrada

### Passo 5: Configurar Webhook (Opcional)

Para receber notificações automáticas de pagamento:

1. Na aplicação EFI, vá em **Webhooks**
2. Adicione a URL: `https://seu-dominio.railway.app/cobrancas/webhook`
3. Marque os eventos: `pix`, `pagamento`

---

## 💳 Usar o Sistema de Cobranças

### Acessando o módulo

1. Faça login no sistema NH Transportes
2. No menu, clique em **Financeiro > Cobranças PIX/Boleto**

### Configurando credenciais (primeira vez)

1. Vá em **Financeiro > Configurar EFI**
2. Preencha:
   - Client ID
   - Client Secret
   - Faça upload do certificado .pem
   - Cole sua chave PIX
   - Selecione o ambiente (sandbox/produção)
3. Clique em **Salvar Configuração**

### Criando uma cobrança PIX

1. Clique em **Nova Cobrança**
2. Selecione tipo: **PIX**
3. Preencha o valor e descrição
4. Preencha dados do pagador (ou selecione um cliente)
5. Clique em **Criar Cobrança**
6. O QR Code será gerado automaticamente
7. Envie o QR Code ou código copia-e-cola para o cliente

### Criando um Boleto

1. Clique em **Nova Cobrança**
2. Selecione tipo: **Boleto**
3. Preencha valor, descrição e **data de vencimento**
4. Preencha dados completos do pagador (incluindo endereço)
5. Clique em **Criar Cobrança**
6. O boleto será gerado com link para PDF

### Verificando pagamentos

- Na lista de cobranças, clique no ícone de atualizar (🔄) para consultar status
- Cobranças pagas aparecerão com status verde
- Com webhook configurado, o status é atualizado automaticamente

---

## 🔍 Consultas SQL Úteis

### Ver todas as cobranças
```sql
SELECT * FROM cobrancas ORDER BY created_at DESC;
```

### Ver cobranças pendentes
```sql
SELECT * FROM cobrancas WHERE status IN ('pendente', 'aguardando');
```

### Ver cobranças pagas
```sql
SELECT * FROM cobrancas WHERE status = 'pago';
```

### Relatório de cobranças por cliente
```sql
SELECT 
    c.pagador_nome,
    COUNT(*) as total_cobrancas,
    SUM(CASE WHEN c.status = 'pago' THEN c.valor ELSE 0 END) as total_pago,
    SUM(CASE WHEN c.status IN ('pendente', 'aguardando') THEN c.valor ELSE 0 END) as total_pendente
FROM cobrancas c
GROUP BY c.pagador_nome;
```

### Ver configuração EFI
```sql
SELECT id, client_id, chave_pix, ambiente, ativo, updated_at 
FROM efi_config 
WHERE ativo = TRUE;
```

---

## ❓ Solução de Problemas

### Erro "API EFI não configurada"
- Verifique se as credenciais estão salvas em **Configurar EFI**
- Verifique se o registro está ativo (`ativo = TRUE`)

### Erro de autenticação
- Verifique Client ID e Client Secret
- Verifique se o certificado está correto
- Verifique se está usando o ambiente correto (sandbox/produção)

### QR Code não aparece
- Verifique se a chave PIX está configurada
- Verifique se a chave PIX está cadastrada na conta EFI

### Boleto não gerado
- Verifique se todos os dados do pagador estão preenchidos
- CPF/CNPJ deve ser válido
- Endereço é obrigatório para boleto

---

## 📞 Suporte

- **Documentação EFI:** [dev.efipay.com.br](https://dev.efipay.com.br)
- **Suporte EFI:** suporte@efipay.com.br
- **Comunidade:** [Fórum EFI](https://comunidade.gerencianet.com.br)

---

*Última atualização: Dezembro 2024*
