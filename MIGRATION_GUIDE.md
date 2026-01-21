# Quilometragem Page Improvements - Migration Guide

## Changes Implemented

This PR implements the following improvements to the Quilometragem page to match the functionality of the Posto/Vendas page:

### 1. Default to Current Month Filter ✅
- The page now automatically filters data to show only the current month by default
- Users can still change the date range using the filters

### 2. Enhanced Summary Section ✅
- Now shows a table format (similar to posto/vendas) with:
  - **Quantidade de Abastecimentos**: Number of refuelings per vehicle
  - **Total Litros**: Total liters refueled (with 3 decimal places)
  - **KMs Rodados**: Total kilometers driven
  - **Valor Total**: Total fuel cost
  - **Média km/l**: Average fuel consumption per vehicle
- Only vehicles that were actually refueled are shown in the summary

### 3. New Field: Valor Produtos Diversos ✅
- Added a new optional field to track expenses with other products (not just fuel)
- Can be left blank if not used
- Appears in both the form and the list view

### 4. Automatic Number Formatting ✅
- **Valor Combustível & KM Final**: Automatically formats with 2 decimal places
  - Example: typing `100000` displays as `1.000,00`
  - Example: typing `10000` displays as `100,00`
- **Litros Abastecidos**: Automatically formats with 3 decimal places
  - Example: typing `10000` displays as `10,000`
  - Example: typing `1000` displays as `1,000`
- **Valor Produtos Diversos**: Same formatting as Valor Combustível (2 decimal places)

## Database Migration Required

Before deploying this update, you **MUST** run the following SQL migration:

```sql
ALTER TABLE quilometragem
ADD COLUMN valor_produtos_diversos DECIMAL(10,2) DEFAULT 0.00
COMMENT 'Valor gasto com produtos diversos (não combustível)';
```

### How to Apply the Migration:

#### Option 1: Using the migration file
```bash
mysql -h [HOST] -P [PORT] -u [USER] -p[PASSWORD] [DATABASE] < migrations/20260121_add_produtos_diversos_quilometragem.sql
```

#### Option 2: Run directly in MySQL
1. Connect to your MySQL database
2. Select the `railway` database (or your database name)
3. Execute the ALTER TABLE command above

### Verification
After running the migration, verify it was successful:
```sql
DESCRIBE quilometragem;
```

You should see the new column `valor_produtos_diversos` in the table structure.

## Screenshots

### Number Formatting Demo (Before filling)
![Number Formatting Demo - Initial](https://github.com/user-attachments/assets/0900f892-d804-4173-8ac2-28da1c80df0a)

### Number Formatting Demo (After filling)
![Number Formatting Demo - Filled](https://github.com/user-attachments/assets/6a5b872b-503f-4bad-a129-74c3e311ce50)

As shown in the screenshots:
- **KM Final**: 100000 → **1.000,00** (2 decimals)
- **Valor Combustível**: 10000 → **100,00** (2 decimals)
- **Litros Abastecidos**: 10000 → **10,000** (3 decimals)
- **Valor Produtos Diversos**: 5000 → **50,00** (2 decimals)

## Files Modified

1. **routes/quilometragem.py**
   - Added default date filtering to current month
   - Updated summary query to include refueling count
   - Changed LEFT JOIN to INNER JOIN to only show vehicles with refuelings
   - Added handling for `valor_produtos_diversos` field

2. **templates/quilometragem/lista.html**
   - Improved summary section with table format
   - Added "Produtos Diversos" column to the main table
   - Enhanced styling to match posto/vendas page

3. **templates/quilometragem/novo.html**
   - Added "Valor Produtos Diversos" field
   - Implemented automatic number formatting with JavaScript
   - Added helpful hints for users about the formatting

4. **templates/quilometragem/editar.html**
   - Added "Valor Produtos Diversos" field for editing

5. **migrations/20260121_add_produtos_diversos_quilometragem.sql**
   - New migration file to add the database column

## Testing

All code has been validated:
- ✅ Python syntax check passed
- ✅ Jinja2 template syntax check passed
- ✅ JavaScript syntax check passed
- ✅ Number formatting functions tested and working

## Deployment Steps

1. **Before deployment**: Run the database migration (see above)
2. Deploy the updated code
3. Test the page to ensure:
   - Default date filter works (shows current month)
   - Summary section displays correctly
   - Number formatting works in the form
   - New "Produtos Diversos" field appears and is optional
   - Existing data displays correctly

## Notes

- The `valor_produtos_diversos` field is **optional** and can be left blank
- When left blank, it defaults to 0.00 in the database
- The field will not be shown in the list if the value is 0 or NULL
- All existing quilometragem records will have this field set to 0.00 by default
