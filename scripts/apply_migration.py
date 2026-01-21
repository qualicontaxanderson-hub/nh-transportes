#!/usr/bin/env python3
"""
Script to apply database migrations
"""
import os
import sys
import mysql.connector
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import Config

def apply_migration(migration_file):
    """Apply a single migration file"""
    print(f"Applying migration: {migration_file}")
    
    # Read migration SQL
    with open(migration_file, 'r') as f:
        sql = f.read()
    
    # Connect to database
    conn = mysql.connector.connect(
        host=Config.DB_HOST,
        port=Config.DB_PORT,
        user=Config.DB_USER,
        password=Config.DB_PASSWORD,
        database=Config.DB_NAME
    )
    
    cursor = conn.cursor()
    
    try:
        # Split SQL into individual statements
        statements = [s.strip() for s in sql.split(';') if s.strip()]
        
        for statement in statements:
            if statement:
                print(f"Executing: {statement[:100]}...")
                cursor.execute(statement)
        
        conn.commit()
        print(f"✓ Migration applied successfully: {migration_file}")
        return True
        
    except Exception as e:
        print(f"✗ Error applying migration: {e}")
        conn.rollback()
        return False
        
    finally:
        cursor.close()
        conn.close()

def main():
    """Main function"""
    migrations_dir = Path(__file__).parent.parent / 'migrations'
    
    # Get migration file from command line or apply all
    if len(sys.argv) > 1:
        migration_file = migrations_dir / sys.argv[1]
        if migration_file.exists():
            success = apply_migration(migration_file)
            sys.exit(0 if success else 1)
        else:
            print(f"Migration file not found: {migration_file}")
            sys.exit(1)
    else:
        # Apply all migrations
        print("Applying all migrations...")
        migrations = sorted(migrations_dir.glob('*.sql'))
        
        if not migrations:
            print("No migrations found")
            sys.exit(0)
        
        success_count = 0
        for migration in migrations:
            if apply_migration(migration):
                success_count += 1
            print()
        
        print(f"\n{success_count}/{len(migrations)} migrations applied successfully")
        sys.exit(0 if success_count == len(migrations) else 1)

if __name__ == '__main__':
    main()
