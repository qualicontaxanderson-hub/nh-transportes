#!/usr/bin/env python3
"""
Script para executar uma migration específica no banco de dados.

Uso:
    python run_single_migration.py migrations/20260215_add_despesas_fornecedores.sql

Ou pelo shell do Render:
    cd /opt/render/project/src
    python run_single_migration.py migrations/20260215_add_despesas_fornecedores.sql
"""

import sys
import os
from pathlib import Path

# Adiciona o diretório atual ao path para imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def run_migration(migration_file):
    """Executa um arquivo de migration SQL."""
    try:
        # Import aqui para pegar as configurações corretas
        from utils.db import get_connection
        
        # Verifica se o arquivo existe
        if not os.path.exists(migration_file):
            print(f"❌ Erro: Arquivo não encontrado: {migration_file}")
            return False
        
        # Lê o conteúdo do arquivo SQL
        print(f"📄 Lendo migration: {migration_file}")
        with open(migration_file, 'r', encoding='utf-8') as f:
            sql_content = f.read()
        
        # Remove comentários e linhas vazias para log
        sql_lines = [line for line in sql_content.split('\n') 
                    if line.strip() and not line.strip().startswith('--')]
        
        print(f"📊 SQL a ser executado ({len(sql_lines)} linhas não-vazias)")
        print("-" * 60)
        
        # Conecta ao banco
        print("🔌 Conectando ao banco de dados...")
        conn = get_connection()
        cursor = conn.cursor()
        
        # Executa o SQL
        print("⚙️  Executando migration...")
        
        # Divide por statements (separados por ;)
        statements = [s.strip() for s in sql_content.split(';') if s.strip()]
        
        for i, statement in enumerate(statements, 1):
            if statement.strip():
                print(f"   Executando statement {i}/{len(statements)}...")
                cursor.execute(statement)
        
        conn.commit()
        
        print("✅ Migration executada com sucesso!")
        
        # Verifica se a tabela foi criada
        if 'despesas_fornecedores' in sql_content:
            cursor.execute("SHOW TABLES LIKE 'despesas_fornecedores'")
            result = cursor.fetchone()
            if result:
                print("✅ Tabela 'despesas_fornecedores' criada com sucesso!")
                
                # Mostra estrutura da tabela
                cursor.execute("DESCRIBE despesas_fornecedores")
                columns = cursor.fetchall()
                print("\n📋 Estrutura da tabela:")
                for col in columns:
                    print(f"   - {col[0]}: {col[1]}")
            else:
                print("⚠️  Aviso: Tabela 'despesas_fornecedores' não encontrada após execução")
        
        cursor.close()
        conn.close()
        
        print("\n" + "=" * 60)
        print("✅ MIGRATION CONCLUÍDA COM SUCESSO!")
        print("=" * 60)
        return True
        
    except Exception as e:
        print(f"\n❌ Erro ao executar migration:")
        print(f"   {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Função principal."""
    if len(sys.argv) < 2:
        print("Uso: python run_single_migration.py <arquivo_migration.sql>")
        print("\nExemplo:")
        print("  python run_single_migration.py migrations/20260215_add_despesas_fornecedores.sql")
        sys.exit(1)
    
    migration_file = sys.argv[1]
    
    print("=" * 60)
    print("🚀 EXECUTAR MIGRATION")
    print("=" * 60)
    print(f"Arquivo: {migration_file}")
    print()
    
    # Confirma execução
    if '--force' not in sys.argv:
        response = input("⚠️  Deseja continuar? (s/N): ")
        if response.lower() not in ['s', 'sim', 'y', 'yes']:
            print("❌ Cancelado pelo usuário.")
            sys.exit(0)
    
    success = run_migration(migration_file)
    
    if success:
        print("\n✅ Processo concluído com sucesso!")
        sys.exit(0)
    else:
        print("\n❌ Processo falhou. Verifique os erros acima.")
        sys.exit(1)

if __name__ == '__main__':
    main()
