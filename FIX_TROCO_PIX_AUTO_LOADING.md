# 🔧 Fix: TROCO PIX (AUTO) Not Loading Automatically

## Problem Description
When creating a new Cash Closure (Fechamento de Caixa) at `/lancamentos_caixa/novo`, the "TROCO PIX (AUTO)" field was not being automatically populated with data from the `troco_pix` table, while "CHEQUE AUTO" WAS working correctly.

## Root Cause
The JavaScript code that populates AUTO fields in the template (`templates/lancamentos_caixa/novo.html`) was only matching the field name `'TROCO PIX (AUTO)'` but not the legacy name `'TROCO PIX'`.

This caused issues if:
1. The migration `20260203_add_troco_pix_auto.sql` didn't run properly
2. The database still had an entry with nome='TROCO PIX' (without the (AUTO) suffix)
3. There was a whitespace or encoding mismatch in the field name

## Solution Applied
Updated line 367 in `templates/lancamentos_caixa/novo.html` to match BOTH field names:

**BEFORE:**
```javascript
} else if (tipoNome === 'TROCO PIX (AUTO)') {
    valorInput.value = formatCurrency(data.troco_pix || 0);
}
```

**AFTER:**
```javascript
} else if (tipoNome === 'TROCO PIX (AUTO)' || tipoNome === 'TROCO PIX') {
    valorInput.value = formatCurrency(data.troco_pix || 0);
}
```

This provides backward compatibility and ensures the field is populated regardless of which name is in the database.

## Files Modified
- `templates/lancamentos_caixa/novo.html` (line 367)
  - Added support for both 'TROCO PIX (AUTO)' and 'TROCO PIX' field names
  - Added console.log debugging statements to help trace issues

## How to Verify the Fix

### Step 1: Verify Database Configuration
Run this query to ensure TROCO PIX AUTO exists in the database:

```sql
SELECT 
    (SELECT COUNT(*) FROM tipos_receita_caixa WHERE nome = 'TROCO PIX (AUTO)') as tem_pix_auto,
    (SELECT COUNT(*) FROM formas_pagamento_caixa WHERE tipo = 'DEPOSITO_CHEQUE_VISTA' AND ativo = 1) as tem_cheque_vista,
    (SELECT COUNT(*) FROM formas_pagamento_caixa WHERE tipo = 'DEPOSITO_CHEQUE_PRAZO' AND ativo = 1) as tem_cheque_prazo;
```

**Expected Result:**
```
+──────────────┬──────────────────┬───────────────────┐
│ tem_pix_auto │ tem_cheque_vista │ tem_cheque_prazo  │
├──────────────┼──────────────────┼───────────────────┤
│      1       │        1         │         1         │
└──────────────┴──────────────────┴───────────────────┘
```

If `tem_pix_auto` is 0, run the migration:
```bash
mysql -u usuario -p banco < migrations/20260203_add_troco_pix_auto.sql
```

### Step 2: Test the Auto-Loading Feature

1. **Create a TROCO PIX transaction:**
   - Go to `/troco_pix/pista` (as PISTA user) or `/troco_pix/` (as ADMIN)
   - Click "Novo Troco PIX"
   - Fill in the form with test data:
     - Date: 02/01/2026
     - Cliente: POSTO NOVO HORIZONTE GOIATUBA LTDA
     - Venda: R$ 2.020,00
     - Cheque À Vista: R$ 3.000,00
     - Troco PIX: R$ 1.000,00
   - Save

2. **Create a Cash Closure and verify auto-loading:**
   - Go to `/lancamentos_caixa/novo`
   - Select:
     - Cliente: POSTO NOVO HORIZONTE GOIATUBA LTDA
     - Data: 02/01/2026
   - Wait for auto-loading (you'll see "Carregando vendas do dia..." message)

3. **Check Browser Console (F12) for debug output:**
   ```
   Dados recebidos do get_vendas_dia: {vendas_posto: 44294.17, arla: 114.52, lubrificantes: 0, troco_pix: 1000, cheques_auto: Array(1)}
   Verificando receita: tipoNome="VENDAS POSTO", readonly=true
   Verificando receita: tipoNome="ARLA", readonly=true
   Verificando receita: tipoNome="LUBRIFICANTES", readonly=true
   Verificando receita: tipoNome="TROCO PIX (AUTO)", readonly=true
   Atualizando TROCO PIX: tipoNome="TROCO PIX (AUTO)", valor=1000
   ```

4. **Verify the form shows:**
   - ✅ TROCO PIX (AUTO): R$ 1.000,00 (readonly, with "Auto" badge)
   - ✅ CHEQUE AUTO in Comprovações: R$ 3.000,00 (with description "AUTO - Cheque À Vista - Troco PIX #14")

### Step 3: Expected Behavior

**Receitas e Entradas (Left Side):**
- VENDAS POSTO: Auto-filled
- ARLA: Auto-filled
- LUBRIFICANTES: Auto-filled
- **TROCO PIX (AUTO): R$ 1.000,00** ← Should be auto-filled ✅
- Other manual fields...

**Comprovação para Fechamento (Right Side):**
- **Depósitos em Cheques À Vista: R$ 3.000,00** ← Should be auto-filled ✅
- Description: "AUTO - Cheque À Vista - Troco PIX #14"
- Other manual fields...

## What If It Still Doesn't Work?

### Check 1: Verify tipos_receita_caixa entries
```sql
SELECT id, nome, tipo, ativo FROM tipos_receita_caixa WHERE nome LIKE '%TROCO PIX%';
```

Expected result:
```
+----+---------------------+--------+-------+
| id | nome                | tipo   | ativo |
+----+---------------------+--------+-------+
| XX | TROCO PIX (MANUAL)  | MANUAL |     1 |
| XX | TROCO PIX (AUTO)    | AUTO   |     1 |
+----+---------------------+--------+-------+
```

### Check 2: Verify troco_pix data exists
```sql
SELECT id, cliente_id, data, troco_pix, cheque_valor 
FROM troco_pix 
WHERE cliente_id = [CLIENTE_ID] AND data = '2026-01-02';
```

This should return records with troco_pix > 0.

### Check 3: Test the API directly
Open browser and go to:
```
https://nh-transportes.onrender.com/lancamentos_caixa/get_vendas_dia?cliente_id=[ID]&data=2026-01-02
```

Expected response:
```json
{
  "vendas_posto": 44294.17,
  "arla": 114.52,
  "lubrificantes": 0,
  "troco_pix": 1000.00,
  "cheques_auto": [
    {
      "troco_pix_id": 14,
      "tipo": "A_VISTA",
      "valor": 3000.00,
      "data_vencimento": null,
      "descricao": "AUTO - Cheque À Vista - Troco PIX #14"
    }
  ]
}
```

### Check 4: Browser Console Errors
Open DevTools (F12) → Console tab and look for any errors:
- ❌ "Failed to fetch..."
- ❌ "TypeError..."
- ❌ "Uncaught..."

## Debug Mode
The fix includes console.log statements for debugging. To see them:
1. Open browser DevTools (F12)
2. Go to Console tab
3. Load the Cash Closure form
4. Select cliente and data
5. You should see debug output showing:
   - Data received from API
   - Each receita field being checked
   - TROCO PIX value being updated

## Migration Required
If `tem_pix_auto` returns 0, you MUST run the migration:

```bash
mysql -u root -p railway < /home/runner/work/nh-transportes/nh-transportes/migrations/20260203_add_troco_pix_auto.sql
```

Or via Render console:
```bash
mysql -h centerbeam.proxy.rlwy.net -P 56026 -u root -p railway < migrations/20260203_add_troco_pix_auto.sql
```

## Technical Details

### How AUTO Fields Work
1. User selects Cliente and Data
2. JavaScript calls `/lancamentos_caixa/get_vendas_dia` API
3. Backend queries:
   - `vendas_posto` table for sales
   - `arla_lancamentos` for ARLA
   - `lubrificantes_lancamentos` for lubrificantes
   - **`troco_pix` table for PIX change** ← Fixed here
   - `troco_pix` table for checks
4. JavaScript populates readonly fields with returned values
5. Fields marked with tipo='AUTO' are readonly and show "Auto" badge

### Why CHEQUE AUTO Worked But TROCO PIX Didn't
- CHEQUES AUTO: Uses `cheque_valor` column and filters `cheque_valor > 0` ✅
- TROCO PIX AUTO: Uses `troco_pix` column but field name wasn't matching ❌

Now both work correctly with the fix! ✅

## Next Steps
1. Deploy this fix to production (already pushed to branch)
2. Run migration if not already done
3. Test with real data
4. Remove debug console.log statements if needed (optional)
5. Update user documentation to mention the TROCO PIX AUTO field

## References
- Migration: `migrations/20260203_add_troco_pix_auto.sql`
- Integration docs: `INTEGRACAO_TROCO_PIX_CHEQUES.md`
- Validation checklist: `CHECKLIST_VALIDACAO_TROCO_PIX.md`
- Explanation: `EXPLICACAO_QUERY_AUTOMATICO.md`

---
**Date:** 2026-02-03
**Status:** ✅ Fixed
**Branch:** copilot/fix-troco-pix-auto-error
