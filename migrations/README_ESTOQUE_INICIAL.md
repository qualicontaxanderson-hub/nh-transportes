# Migration: Add Estoque Inicial to Vendas Posto

## Overview
This migration adds the `estoque_inicial` (initial stock) column to the `vendas_posto` table, allowing users to track the starting inventory for each product on a daily basis.

## Migration File
- **File**: `20260121_add_estoque_inicial_vendas_posto.sql`
- **Date**: 2026-01-21

## Changes Made

### Database Schema
- Added `estoque_inicial` column to `vendas_posto` table
  - Type: `DECIMAL(10, 3)` (supports up to 3 decimal places for liters)
  - Nullable: `NULL` (optional field)
  - Position: After `quantidade_litros` column

### Application Code

#### Model (`models/vendas_posto.py`)
- Added `estoque_inicial` field to the `VendasPosto` model

#### Routes (`routes/posto.py`)
- Updated `vendas_lancar` route to handle `estoque_inicial` input when creating new sales
- Updated `vendas_editar_data` route to handle `estoque_inicial` when editing sales
- Updated sales listing to include `estoque_inicial` in the product data

#### Templates
- **`templates/posto/vendas_lancar.html`**:
  - Added "Estoque Inicial (Litros)" input field for each product in new entry form
  - Added "Estoque Inicial (Litros)" input field for each product in edit mode
  - Added JavaScript mask handling for the estoque inicial input (3 decimal places)

- **`templates/posto/vendas_lista.html`**:
  - Added "Estoque Inicial" column to the product listing table
  - Display shows the initial stock value or "-" if not set

## How to Apply Migration

### Option 1: Using MySQL Command Line
```bash
mysql -h <host> -u <user> -p <database> < migrations/20260121_add_estoque_inicial_vendas_posto.sql
```

### Option 2: Using Python Script
```python
import mysql.connector
from config import Config

config = Config()
connection = mysql.connector.connect(
    host=config.DB_HOST,
    port=config.DB_PORT,
    user=config.DB_USER,
    password=config.DB_PASSWORD,
    database=config.DB_NAME
)

cursor = connection.cursor()

# Read and execute migration file
with open('migrations/20260121_add_estoque_inicial_vendas_posto.sql', 'r') as f:
    sql = f.read()
    for statement in sql.split(';'):
        if statement.strip():
            cursor.execute(statement)

connection.commit()
cursor.close()
connection.close()
```

## Verification

After applying the migration, verify:

1. Column exists:
   ```sql
   SHOW COLUMNS FROM vendas_posto WHERE Field = 'estoque_inicial';
   ```

2. Index created:
   ```sql
   SHOW INDEX FROM vendas_posto WHERE Key_name = 'idx_vendas_posto_estoque';
   ```

## Usage

Users can now:
1. Enter initial stock values when creating new sales entries at `/posto/vendas/lancar`
2. View initial stock values in the sales listing at `/posto/vendas`
3. Edit initial stock values when modifying existing sales

## Notes
- The `estoque_inicial` field is optional and can be left empty
- Values are displayed with 3 decimal places (e.g., 5.000,000)
- The field uses the same decimal format as `quantidade_litros` for consistency
