#!/usr/bin/env python3
"""
Script to run SQL migrations
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from utils.db import get_db_connection

def run_migration(file_path):
    """Run a single migration file"""
    print(f"\n{'='*60}")
    print(f"Running migration: {os.path.basename(file_path)}")
    print('='*60)
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            sql_content = f.read()
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Split by semicolons but handle multi-line statements
        statements = []
        current_statement = []
        
        for line in sql_content.split('\n'):
            # Skip comments
            if line.strip().startswith('--'):
                continue
            
            current_statement.append(line)
            
            # Check if statement ends with semicolon
            if line.strip().endswith(';'):
                statement = '\n'.join(current_statement)
                if statement.strip():
                    statements.append(statement)
                current_statement = []
        
        # Execute each statement
        for i, statement in enumerate(statements, 1):
            try:
                if statement.strip():
                    print(f"Executing statement {i}/{len(statements)}...")
                    cursor.execute(statement)
                    conn.commit()
            except Exception as e:
                print(f"Warning on statement {i}: {e}")
                # Continue with other statements
                conn.rollback()
        
        cursor.close()
        conn.close()
        
        print(f"✓ Migration completed: {os.path.basename(file_path)}")
        return True
        
    except Exception as e:
        print(f"✗ Error running migration: {e}")
        return False

if __name__ == '__main__':
    migrations_dir = os.path.join(os.path.dirname(__file__), 'migrations')
    
    # Run specific migrations for expenses
    migrations = [
        '20260212_add_titulos_despesas.sql',
        '20260212_seed_despesas.sql',
    ]
    
    success_count = 0
    for migration in migrations:
        file_path = os.path.join(migrations_dir, migration)
        if os.path.exists(file_path):
            if run_migration(file_path):
                success_count += 1
        else:
            print(f"✗ Migration file not found: {migration}")
    
    print(f"\n{'='*60}")
    print(f"Migrations completed: {success_count}/{len(migrations)}")
    print('='*60)
