#!/usr/bin/env python3
"""
Script de teste para verificar funcionalidade SUPERVISOR
"""

import sys
sys.path.insert(0, '/home/runner/work/nh-transportes/nh-transportes')

from models.usuario import Usuario
from utils.db import get_db_connection

def test_database_tables():
    """Testa se as tabelas foram criadas"""
    print("=" * 60)
    print("TESTE 1: Verificar Tabelas no Banco de Dados")
    print("=" * 60)
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Verificar usuario_empresas
    try:
        cursor.execute("SHOW TABLES LIKE 'usuario_empresas'")
        result = cursor.fetchone()
        if result:
            print("✓ Tabela 'usuario_empresas' existe")
            cursor.execute("DESCRIBE usuario_empresas")
            columns = cursor.fetchall()
            print(f"  Colunas: {', '.join([c['Field'] for c in columns])}")
        else:
            print("✗ Tabela 'usuario_empresas' NÃO existe - Execute a migration!")
    except Exception as e:
        print(f"✗ Erro ao verificar usuario_empresas: {e}")
    
    # Verificar usuario_permissoes
    try:
        cursor.execute("SHOW TABLES LIKE 'usuario_permissoes'")
        result = cursor.fetchone()
        if result:
            print("✓ Tabela 'usuario_permissoes' existe")
            cursor.execute("DESCRIBE usuario_permissoes")
            columns = cursor.fetchall()
            print(f"  Colunas: {', '.join([c['Field'] for c in columns])}")
        else:
            print("✗ Tabela 'usuario_permissoes' NÃO existe - Execute a migration!")
    except Exception as e:
        print(f"✗ Erro ao verificar usuario_permissoes: {e}")
    
    cursor.close()
    conn.close()
    print()

def test_usuario_methods():
    """Testa os novos métodos do modelo Usuario"""
    print("=" * 60)
    print("TESTE 2: Verificar Métodos do Modelo Usuario")
    print("=" * 60)
    
    # Verificar se métodos existem
    methods = [
        'get_empresas_usuario',
        'set_empresas_usuario',
        'get_clientes_produtos_posto'
    ]
    
    for method in methods:
        if hasattr(Usuario, method):
            print(f"✓ Método '{method}' existe")
        else:
            print(f"✗ Método '{method}' NÃO existe")
    
    # Testar get_clientes_produtos_posto
    try:
        empresas = Usuario.get_clientes_produtos_posto()
        print(f"\n✓ get_clientes_produtos_posto() retornou {len(empresas)} empresas")
        if empresas:
            print(f"  Exemplo: {empresas[0].get('razao_social', 'N/A')}")
    except Exception as e:
        print(f"✗ Erro ao chamar get_clientes_produtos_posto(): {e}")
    
    print()

def test_decorators():
    """Testa se o decorator foi adicionado"""
    print("=" * 60)
    print("TESTE 3: Verificar Decorators")
    print("=" * 60)
    
    try:
        from utils.decorators import supervisor_or_admin_required
        print("✓ Decorator 'supervisor_or_admin_required' importado com sucesso")
    except ImportError as e:
        print(f"✗ Erro ao importar supervisor_or_admin_required: {e}")
    
    print()

def test_route_permissions():
    """Testa se as rotas foram atualizadas"""
    print("=" * 60)
    print("TESTE 4: Verificar Permissões nas Rotas")
    print("=" * 60)
    
    routes_to_check = [
        ('routes.caixa', 'caixa.py'),
        ('routes.cartoes', 'cartoes.py'),
        ('routes.tipos_receita_caixa', 'tipos_receita_caixa.py'),
    ]
    
    for module_name, filename in routes_to_check:
        try:
            # Ler o arquivo
            with open(f'/home/runner/work/nh-transportes/nh-transportes/routes/{filename}', 'r') as f:
                content = f.read()
            
            # Verificar se supervisor_or_admin_required está presente
            if 'supervisor_or_admin_required' in content:
                count = content.count('@supervisor_or_admin_required')
                print(f"✓ {filename}: {count} rotas com supervisor_or_admin_required")
            else:
                print(f"⚠ {filename}: Não usa supervisor_or_admin_required (pode ser intencional)")
        except Exception as e:
            print(f"✗ Erro ao verificar {filename}: {e}")
    
    print()

def main():
    print("\n" + "=" * 60)
    print("TESTE DE IMPLEMENTAÇÃO: PERMISSÕES SUPERVISOR")
    print("=" * 60)
    print()
    
    try:
        test_database_tables()
        test_usuario_methods()
        test_decorators()
        test_route_permissions()
        
        print("=" * 60)
        print("RESUMO")
        print("=" * 60)
        print("✓ Testes de código completados")
        print("⚠ Para testar completamente:")
        print("  1. Execute a migration no banco de dados")
        print("  2. Teste criar usuário SUPERVISOR via interface")
        print("  3. Teste acessar rotas protegidas com SUPERVISOR")
        print()
        
    except Exception as e:
        print(f"\n✗ ERRO GERAL: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    main()
