# Sistema de Importação e Conciliação de Extrato Bancário (OFX)

## Visão Geral

Este módulo adiciona ao sistema NH Transportes a capacidade de importar extratos bancários no formato OFX (Open Financial Exchange), analisar automaticamente as transações, extrair dados de CNPJ/CPF e conciliar as movimentações com fornecedores já cadastrados.

---

## Fluxo de Funcionamento

```
Upload OFX
    ↓
Validação do arquivo
    ↓
Parse e extração de dados (OFXParser)
    ↓
Deduplicação por hash SHA-256
    ↓
Extração de CNPJ/CPF da descrição
    ↓
Auto-conciliação (se existir mapeamento prévio)
    ↓
Armazenamento no banco de dados
    ↓
Conciliação manual das pendências
```

---

## Instalação

### 1. Executar a migration do banco de dados

```sql
SOURCE migrations/20260220_add_bank_import_tables.sql;
```

Ou via o script de migrations do projeto:

```bash
python run_single_migration.py migrations/20260220_add_bank_import_tables.sql
```

### 2. Cadastrar pelo menos uma conta bancária

Acesse `/banco/` e clique em **"Cadastrar Nova Conta"**, ou use a API:

```bash
curl -X POST /banco/api/contas \
  -H "Content-Type: application/json" \
  -d '{"banco_nome": "Banco do Brasil", "agencia": "1234", "conta": "56789-0", "apelido": "Conta Principal"}'
```

---

## Uso

### Importar extrato manualmente (upload)

1. Acesse `/banco/`
2. Selecione a conta bancária
3. Faça upload do arquivo `.ofx`
4. O sistema deduplica e importa automaticamente

### Pasta de Entrada OFX (Watch-Folder) — funciona no Railway sem configuração extra

O sistema possui uma **pasta de entrada** onde você pode depositar arquivos OFX. Eles ficam aguardando e você pode importar cada um no momento que quiser, sem que o processo seja imediato como no upload direto.

#### Railway (recomendado — sem configuração extra)

No Railway (e em qualquer cloud com container efêmero), o fluxo é feito **100% pelo navegador**:

1. Acesse `/banco/`
2. Na seção **"Pasta de Entrada OFX"**, clique em **"Enviar OFX para Pasta"**
3. Selecione o arquivo `.ofx` no seu computador — ele é salvo na pasta `ofx_inbox/` do servidor
4. O arquivo aparece na lista da pasta de entrada
5. Selecione a conta bancária e clique **Importar** ao lado do arquivo
6. O arquivo é processado e movido para `ofx_inbox/processados/` automaticamente

> **Nota sobre o Railway:** O filesystem de containers Railway é efêmero (reseta a cada deploy). Os arquivos salvos na inbox sobrevivem durante o uptime do container mas são perdidos no redeploy. Para persistência permanente, use um **Railway Volume** (veja abaixo).

#### Servidor próprio / VPS (Linux, FTP, NFS)

Se você tem acesso direto ao servidor, pode copiar arquivos para a pasta diretamente:

```bash
# Copiar via SCP
scp extrato_20260220.ofx usuario@servidor:/app/ofx_inbox/

# Ou configurar outra pasta via variável de ambiente
OFX_INBOX_DIR=/mnt/nfs/extratos_bancarios
```

#### Railway com Volume (persistência entre deploys)

1. No Railway, vá em **seu serviço → Settings → Add Volume**
2. Monte o volume em `/data`
3. Adicione a variável de ambiente:
   ```
   OFX_INBOX_DIR=/data/ofx_inbox
   ```
4. Faça redeploy — agora os arquivos persistem entre deploys

#### Estrutura de pastas

```
ofx_inbox/
├── extrato_20260220.ofx    ← arquivos aguardando importação
├── extrato_20260221.ofx
└── processados/            ← arquivos já importados são movidos aqui
    └── extrato_20260219.ofx
```

### Conciliar transações

1. Acesse `/banco/conciliar`
2. Clique em **Conciliar** na transação desejada
3. Pesquise e selecione o fornecedor correspondente
4. Confirme — o sistema aprende o mapeamento CNPJ ↔ fornecedor para as próximas importações

### Visualizar relatório

Acesse `/banco/relatorio` com filtros por conta, status e período.

---

## Banco de Dados

### Estrutura

```
bank_accounts (id, banco_nome, agencia, conta, apelido, ativo)
       ↓
bank_transactions (id, account_id, hash_dedup, data_transacao, tipo, valor,
                   descricao, cnpj_cpf, memo, fitid, status,
                   fornecedor_id, conciliado_em, conciliado_por)
       ↓
bank_supplier_mapping (id, fornecedor_id, cnpj_cpf, tipo_chave, total_conciliacoes)
```

### Views

| View | Descrição |
|------|-----------|
| `vw_bank_summary_by_supplier` | Resumo de débitos/créditos agrupados por fornecedor |
| `vw_bank_pending_reconciliation` | Transações pendentes de conciliação |

### Stored Procedure

`CALL sp_auto_reconcile_transactions()` — concilia automaticamente todas as transações pendentes que possuam CNPJ/CPF mapeado.

### Trigger

`tr_learn_supplier_mapping` — ao conciliar manualmente uma transação com CNPJ/CPF, registra (ou atualiza) o mapeamento na tabela `bank_supplier_mapping` para uso futuro.

---

## API REST

| Método | Endpoint | Descrição |
|--------|----------|-----------|
| `GET` | `/banco/` | Página principal (dashboard) |
| `GET` | `/banco/upload` | Formulário de upload (redireciona para `/banco/`) |
| `POST` | `/banco/upload` | Importa um arquivo OFX |
| `GET` | `/banco/conciliar` | Lista transações pendentes |
| `POST` | `/banco/conciliar` | Concilia ou ignora uma transação |
| `GET` | `/banco/relatorio` | Relatório com filtros |
| `GET` | `/banco/api/transacoes-pendentes` | JSON: transações pendentes |
| `POST` | `/banco/api/auto-reconcile` | Força auto-conciliação |
| `GET` | `/banco/api/contas` | JSON: contas cadastradas |
| `POST` | `/banco/api/contas` | Cria nova conta bancária |
| `GET` | `/banco/api/inbox-files` | JSON: lista arquivos OFX na pasta de entrada |
| `POST` | `/banco/api/inbox-upload` | Salva arquivo OFX na pasta de entrada (sem importar) |
| `POST` | `/banco/scan-inbox` | Importa arquivo da pasta de entrada e move para `processados/` |

---

## Módulos

| Arquivo | Descrição |
|---------|-----------|
| `integrations/ofx_parser.py` | Parser OFX — extrai transações e CNPJ/CPF |
| `models/bank_models.py` | Modelos SQLAlchemy: BankAccount, BankTransaction, BankSupplierMapping |
| `routes/bank_import.py` | Blueprint Flask com todas as rotas |
| `templates/bank_import/index.html` | Dashboard + upload drag-and-drop + pasta de entrada OFX |
| `templates/bank_import/conciliar.html` | Interface de conciliação manual |
| `templates/bank_import/relatorio.html` | Relatório com filtros |
| `migrations/20260220_add_bank_import_tables.sql` | DDL completo |
| `ofx_inbox/` | Pasta de entrada para arquivos OFX (watch-folder) |
| `ofx_inbox/processados/` | Arquivos OFX já processados são movidos aqui |

---

## Aprendizado Automático

1. Ao conciliar manualmente uma transação que contém CNPJ/CPF, o sistema salva o mapeamento `cnpj_cpf → fornecedor_id` na tabela `bank_supplier_mapping`.
2. Na próxima importação, qualquer transação com o mesmo CNPJ/CPF é conciliada **automaticamente** ao fornecedor mapeado.
3. O botão **"Executar Auto-Conciliação"** no dashboard processa em lote todas as pendências com mapeamento existente.

---

## Troubleshooting

**Nenhuma transação importada:**
- Verifique se o arquivo é um OFX válido (começa com `<OFX>` ou cabeçalho SGML).
- Confirme que o arquivo contém blocos `<STMTTRN>`.

**Duplicatas não detectadas:**
- A deduplicação usa SHA-256 de `FITID + data + valor + descrição`. Se o banco alterar o FITID entre exportações, pode gerar duplicatas.

**CNPJ não extraído:**
- O sistema busca padrões `XX.XXX.XXX/XXXX-XX` no campo `NAME` e `MEMO`. Certifique-se de que o banco inclui o CNPJ na descrição da transação.
