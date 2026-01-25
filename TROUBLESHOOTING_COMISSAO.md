# Troubleshooting: Comissão não aparece no formulário

## Problema
A coluna "Comissão" não está aparecendo na planilha de lançamentos de funcionários (`/lancamentos-funcionarios/novo`).

## Causa Provável
A rubrica "Comissão" não existe na tabela `rubricas` do banco de dados, ou está inativa.

## Solução

### Opção 1: Verificar se a rubrica existe

Execute no banco de dados:
```sql
SELECT * FROM rubricas WHERE nome = 'Comissão';
```

Se não retornar nenhum resultado, a rubrica não existe.

### Opção 2: Criar/Ativar a rubrica

Execute o script de migração:
```bash
# No servidor ou local onde tem acesso ao banco
mysql -u seu_usuario -p seu_banco < migrations/20260124_ensure_comissao_rubrica.sql
```

Ou execute manualmente no banco:
```sql
INSERT INTO `rubricas` (`nome`, `descricao`, `tipo`, `percentualouvalorfixo`, `ativo`, `ordem`) 
VALUES ('Comissão', 'Comissão sobre vendas/fretes', 'BENEFICIO', 'VALOR_FIXO', 1, 10)
ON DUPLICATE KEY UPDATE 
    descricao = 'Comissão sobre vendas/fretes',
    tipo = 'BENEFICIO',
    ativo = 1,
    ordem = 10;
```

### Opção 3: Verificar se está ativa

Se a rubrica existe mas não aparece, pode estar inativa:
```sql
UPDATE rubricas SET ativo = 1 WHERE nome = 'Comissão';
```

### Opção 4: Migrar de "COMISSÃO" para "Comissão"

Se você tinha a rubrica com nome "COMISSÃO" (maiúsculas), atualize para "Comissão":
```sql
UPDATE rubricas SET nome = 'Comissão' WHERE nome = 'COMISSÃO';
```

## Como Verificar se Funcionou

1. Acesse `/lancamentos-funcionarios/novo`
2. Selecione um **Cliente** e um **Mês/Ano**
3. A tabela deve carregar com uma coluna "Comissão"
4. Para motoristas que tiveram comissão no mês, o valor deve aparecer automaticamente preenchido

## Verificação de Comissões de Motoristas

Para que as comissões apareçam automaticamente, certifique-se:

1. **Motoristas configurados corretamente:**
```sql
SELECT id, nome, paga_comissao FROM motoristas WHERE paga_comissao = 1;
```

2. **Fretes têm comissão registrada:**
```sql
SELECT 
    m.nome as motorista,
    DATE_FORMAT(f.data_frete, '%m/%Y') as mes,
    SUM(f.comissao_motorista) as total_comissao
FROM fretes f
INNER JOIN motoristas m ON f.motoristas_id = m.id
WHERE m.paga_comissao = 1
  AND f.data_frete >= '2026-01-01'  -- Ajuste a data
GROUP BY m.id, m.nome, DATE_FORMAT(f.data_frete, '%m/%Y')
HAVING total_comissao > 0;
```

## Debug no Navegador

Abra o Console do navegador (F12) e verifique:

1. **Erros no carregamento:**
   - Procure por erros em vermelho
   - Verifique se as chamadas para `/lancamentos-funcionarios/get-comissoes/` retornam 200

2. **Dados recebidos:**
```javascript
// No console do navegador, após selecionar cliente e mês
console.log('Rubricas:', rubricas);
console.log('Comissões:', comissoesData);
```

## Contato

Se o problema persistir após seguir estes passos, verifique:
- Se o script de migração `20260121_create_employee_management_system.sql` foi executado
- Se há erros no log do servidor
- Se a versão do código está atualizada
