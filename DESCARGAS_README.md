# Controle de Descargas - Documentação

## Visão Geral

O módulo de **Controle de Descargas** permite o gerenciamento completo do processo de descarga de combustíveis, incluindo:

- Controle de volume descarregado
- Medições do sistema e régua antes/depois
- Cálculo automático de perdas e sobras
- Suporte para descargas em múltiplas etapas
- Compartilhamento via WhatsApp

## Estrutura de Arquivos

### Backend
- `models/descarga.py` - Model principal de descargas
- `models/descarga_etapa.py` - Model para etapas de descargas
- `routes/descargas.py` - Rotas e endpoints
- `migrations/20260121_add_descargas_tables.sql` - Script de migração do banco
- `scripts/apply_migration.py` - Script para aplicar migrações

### Frontend
- `templates/descargas/lista.html` - Lista de descargas com filtros
- `templates/descargas/novo.html` - Formulário de nova descarga/etapa
- `templates/descargas/detalhes.html` - Detalhes completos da descarga

## Instalação

### 1. Aplicar Migração do Banco de Dados

**Opção A: Via script Python (recomendado)**
```bash
python3 scripts/apply_migration.py 20260121_add_descargas_tables.sql
```

**Opção B: Manualmente via MySQL client**
```bash
mysql -h <host> -u <user> -p <database> < migrations/20260121_add_descargas_tables.sql
```

### 2. Verificar Instalação

Após aplicar a migração, verifique se as tabelas foram criadas:
```sql
SHOW TABLES LIKE '%descarga%';
```

Você deve ver:
- `descargas`
- `descarga_etapas`

## Uso

### 1. Criar Nova Descarga

1. Vá para **Lançamentos > Fretes**
2. Localize o frete desejado
3. Clique no botão de **"Criar Descarga"** (ícone de caminhão)
4. Preencha os dados da descarga:
   - Data de carregamento (pré-preenchida do frete)
   - Data de descarga
   - Volume desta descarga
   - Medições do sistema (antes/depois)
   - Medições da régua (antes/depois)
   - Abastecimento durante descarga (se houver)
   - Temperatura e densidade (opcional)

### 2. Descargas em Etapas

Se uma descarga não for completada de uma vez:

1. Crie a primeira descarga com o volume parcial
2. O sistema marcará como **"Parcial"**
3. Acesse novamente a descarga pelo frete
4. Clique em **"Adicionar Etapa"**
5. Preencha os dados da nova etapa
6. O sistema atualizará automaticamente o status quando o volume total for completado

### 3. Visualizar Descargas

Acesse **Lançamentos > Descargas** para:
- Ver todas as descargas com filtros
- Ver status (Pendente/Parcial/Concluído)
- Ver diferenças calculadas
- Produtos com cores diferenciadas

### 4. Compartilhar via WhatsApp

1. Na lista de descargas ou detalhes
2. Clique no botão **WhatsApp** (verde)
3. O texto formatado será copiado para área de transferência
4. Cole no WhatsApp

Formato do texto:
```
Distribuidora: <Fornecedor>
Data de carregamento: <Data>
Data de descarga: <Data>
Produto: <Produto>
Volume: <Volume>
Motorista: <Motorista>
Medida Sistema Antes: <Valor>
Medida Sistema Depois: <Valor>
Diferença: <Valor>
Temperatura: <Valor>
Densidade: <Valor>
Medição Régua:
Antes: <Valor>
Depois: <Valor>
Diferença: <Valor>
```

## Funcionalidades

### Cálculo Automático de Diferenças

O sistema calcula automaticamente as diferenças usando a fórmula:

```
Diferença = (Estoque Depois - Estoque Antes) - Volume Descarregado + Abastecimento
```

- **Valor Positivo**: Sobra de combustível
- **Valor Negativo**: Perda de combustível  
- **Zero**: Volume exato

### Cores dos Produtos

Os produtos são exibidos com cores específicas:
- **ETANOL**: Verde (#28a745)
- **GASOLINA**: Vermelho (#dc3545)
- **GASOLINA ADITIVADA**: Azul (#007bff)
- **S-10**: Azul (#007bff)
- **S-500**: Cinza escuro (#343a40)

### Filtros Disponíveis

Na lista de descargas:
- Data de início/fim
- Cliente
- Status (Pendente/Parcial/Concluído)

## Estrutura do Banco de Dados

### Tabela: `descargas`

| Campo | Tipo | Descrição |
|-------|------|-----------|
| id | INT | ID único |
| frete_id | INT | ID do frete vinculado |
| data_carregamento | DATE | Data de carregamento |
| data_descarga | DATE | Data de descarga |
| volume_total | DECIMAL(10,2) | Volume total do frete |
| volume_descarregado | DECIMAL(10,2) | Volume já descarregado |
| estoque_sistema_antes | DECIMAL(10,2) | Estoque sistema antes |
| estoque_sistema_depois | DECIMAL(10,2) | Estoque sistema depois |
| estoque_regua_antes | DECIMAL(10,2) | Estoque régua antes |
| estoque_regua_depois | DECIMAL(10,2) | Estoque régua depois |
| abastecimento_durante_descarga | DECIMAL(10,2) | Abastecimento durante |
| temperatura | DECIMAL(5,2) | Temperatura |
| densidade | DECIMAL(5,4) | Densidade |
| diferenca_sistema | DECIMAL(10,2) | Diferença calculada (sistema) |
| diferenca_regua | DECIMAL(10,2) | Diferença calculada (régua) |
| status | VARCHAR(20) | Status (pendente/parcial/concluido) |
| observacoes | TEXT | Observações |

### Tabela: `descarga_etapas`

Armazena etapas individuais de descargas parciais com os mesmos campos de medição.

## Manutenção

### Verificar Integridade

```sql
-- Descargas sem frete
SELECT * FROM descargas WHERE frete_id NOT IN (SELECT id FROM fretes);

-- Etapas sem descarga
SELECT * FROM descarga_etapas WHERE descarga_id NOT IN (SELECT id FROM descargas);

-- Volume total vs descarregado
SELECT 
  id, 
  volume_total, 
  volume_descarregado,
  (volume_total - volume_descarregado) as restante
FROM descargas 
WHERE status != 'concluido';
```

## Troubleshooting

### Problema: Diferença não calculada
- Verifique se os campos "antes" e "depois" estão preenchidos
- O cálculo é feito no backend ao salvar

### Problema: Não consigo adicionar etapa
- Verifique se a descarga não está marcada como "concluído"
- Volume restante deve ser maior que zero

### Problema: WhatsApp não copia
- Verifique permissões do navegador
- Tente usar botão em navegador atualizado
- Fallback: o sistema mostra o texto em alert

## Suporte

Para dúvidas ou problemas, entre em contato com a equipe de desenvolvimento.
