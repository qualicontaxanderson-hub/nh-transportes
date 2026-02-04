# 🚀 Guia de Configuração - NH Transportes

## 📋 Pré-requisitos

- Python 3.8 ou superior
- MySQL/MariaDB
- pip (gerenciador de pacotes Python)

## 🔧 Instalação

### 1. Clone o Repositório

```bash
git clone https://github.com/qualicontaxanderson-hub/nh-transportes.git
cd nh-transportes
```

### 2. Crie um Ambiente Virtual

```bash
python3 -m venv venv
source venv/bin/activate  # No Windows: venv\Scripts\activate
```

### 3. Instale as Dependências

```bash
pip install -r requirements.txt
```

### 4. Configure as Variáveis de Ambiente

⚠️ **IMPORTANTE:** Nunca commite credenciais reais no repositório!

#### Opção A: Criar arquivo `.env` (Recomendado)

Copie o arquivo de exemplo e configure com suas credenciais:

```bash
cp .env.example .env
```

Edite o arquivo `.env` e configure suas credenciais:

```env
# Configurações do Banco de Dados
DB_HOST=seu_host_aqui
DB_PORT=3306
DB_USER=seu_usuario_aqui
DB_PASSWORD=sua_senha_aqui
DB_NAME=seu_banco_aqui

# Chave Secreta da Aplicação
# IMPORTANTE: Gere uma chave forte e única!
# Para gerar: python -c "import secrets; print(secrets.token_hex(32))"
SECRET_KEY=sua_chave_secreta_forte_aqui

# Configurações da Aplicação
FLASK_DEBUG=0  # 1 para desenvolvimento, 0 para produção
PORT=5000
LOG_DIR=.
```

#### Opção B: Variáveis de Ambiente do Sistema

```bash
export DB_HOST=seu_host_aqui
export DB_PORT=3306
export DB_USER=seu_usuario_aqui
export DB_PASSWORD=sua_senha_aqui
export DB_NAME=seu_banco_aqui
export SECRET_KEY=sua_chave_secreta_forte_aqui
```

### 5. Execute as Migrações do Banco de Dados

```bash
# Conecte ao seu banco MySQL e execute os scripts de migração
mysql -h $DB_HOST -u $DB_USER -p$DB_PASSWORD $DB_NAME < migrations/arquivo_migration.sql
```

Ou execute manualmente os arquivos SQL na pasta `migrations/` na ordem correta.

### 6. Inicie a Aplicação

```bash
# Modo desenvolvimento
python app.py

# Modo produção (com gunicorn)
gunicorn app:app --bind 0.0.0.0:5000 --workers 4
```

## 🔒 Segurança

### Gerando uma SECRET_KEY Forte

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### Rotação de Credenciais

Se você já commitou credenciais acidentalmente:

1. **Mude imediatamente as senhas no banco de dados**
2. **Gere uma nova SECRET_KEY**
3. **Atualize o arquivo `.env` com as novas credenciais**
4. Considere reescrever o histórico do Git (com cuidado!)

### Boas Práticas

✅ **FAÇA:**
- Use arquivo `.env` para desenvolvimento local
- Use variáveis de ambiente do sistema em produção
- Rotacione credenciais regularmente
- Mantenha `.env` no `.gitignore`

❌ **NÃO FAÇA:**
- Nunca commite o arquivo `.env`
- Nunca coloque senhas diretamente no código
- Nunca compartilhe credenciais por email/chat

## 🌍 Deploy em Produção

### Railway

1. Configure as variáveis de ambiente no painel do Railway
2. O Railway detectará automaticamente o `Procfile`
3. A aplicação será iniciada automaticamente

### Heroku

1. Configure as variáveis de ambiente:
```bash
heroku config:set DB_HOST=seu_host
heroku config:set DB_PASSWORD=sua_senha
heroku config:set SECRET_KEY=sua_chave
```

2. Deploy:
```bash
git push heroku main
```

### Docker

```dockerfile
# Dockerfile exemplo
FROM python:3.9
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:5000"]
```

## 🐛 Troubleshooting

### Erro: "SECRET_KEY must be set"

**Causa:** A variável de ambiente SECRET_KEY não foi configurada.

**Solução:** 
1. Crie o arquivo `.env` com base no `.env.example`
2. Ou defina a variável de ambiente: `export SECRET_KEY=sua_chave`

### Erro: "No module named 'flask'"

**Causa:** Dependências não instaladas.

**Solução:**
```bash
pip install -r requirements.txt
```

### Erro de Conexão com Banco de Dados

**Causa:** Credenciais incorretas ou banco inacessível.

**Solução:**
1. Verifique as credenciais no `.env`
2. Teste a conexão manualmente:
```bash
mysql -h $DB_HOST -u $DB_USER -p$DB_PASSWORD $DB_NAME
```

## 📚 Documentação Adicional

- **MERGE_REVIEW.md** - Análise de segurança completa
- **RESPOSTA_MERGE.md** - Guia rápido de correções
- **migrations/** - Scripts de migração do banco de dados
- **docs/** - Documentação técnica detalhada

## 💬 Suporte

Se precisar de ajuda:
1. Verifique a documentação em `docs/`
2. Leia os arquivos de troubleshooting
3. Abra uma issue no GitHub

---

**Versão:** 1.0.0  
**Última Atualização:** 2026-02-04
