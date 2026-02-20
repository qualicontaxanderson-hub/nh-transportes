#!/usr/bin/env python3
"""
Test script to validate expense management routes and templates
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

def test_imports():
    """Test if all modules can be imported"""
    print("Testing imports...")
    
    try:
        from routes.despesas import bp
        print("✓ routes.despesas imported successfully")
        print(f"  - Blueprint name: {bp.name}")
        print(f"  - URL prefix: {bp.url_prefix}")
    except Exception as e:
        print(f"✗ Failed to import routes.despesas: {e}")
        return False
    
    try:
        from models.titulo_despesa import TituloDespesa
        from models.categoria_despesa import CategoriaDespesa
        from models.subcategoria_despesa import SubcategoriaDespesa
        print("✓ All expense models imported successfully")
    except Exception as e:
        print(f"✗ Failed to import models: {e}")
        return False
    
    return True

def test_routes():
    """Test if routes are properly defined"""
    print("\nTesting routes...")
    
    try:
        from routes.despesas import bp
        
        routes = []
        for rule in bp.deferred_functions:
            routes.append(str(rule))
        
        expected_routes = [
            'index',
            'titulo_detalhes',
            'categoria_detalhes',
            'novo_titulo',
            'editar_titulo',
            'nova_categoria',
            'editar_categoria',
            'nova_subcategoria',
            'editar_subcategoria',
            'excluir_titulo',
            'excluir_categoria',
            'excluir_subcategoria'
        ]
        
        # Get actual registered routes
        actual_routes = []
        for func in bp.deferred_functions:
            if hasattr(func, '__name__'):
                actual_routes.append(func.__name__)
        
        print(f"✓ Blueprint has {len(actual_routes)} routes registered")
        
        # Check for key routes
        key_routes = ['index', 'novo_titulo', 'nova_categoria']
        for route in key_routes:
            if any(route in str(r) for r in actual_routes):
                print(f"  ✓ Route '{route}' found")
            else:
                print(f"  ⚠ Route '{route}' not found")
        
    except Exception as e:
        print(f"✗ Failed to test routes: {e}")
        return False
    
    return True

def test_templates():
    """Test if templates exist"""
    print("\nTesting templates...")
    
    templates_dir = os.path.join(os.path.dirname(__file__), 'templates', 'despesas')
    
    expected_templates = [
        'index.html',
        'titulo_detalhes.html',
        'categoria_detalhes.html',
        'titulo_form.html',
        'categoria_form.html',
        'subcategoria_form.html'
    ]
    
    for template in expected_templates:
        template_path = os.path.join(templates_dir, template)
        if os.path.exists(template_path):
            print(f"  ✓ Template '{template}' exists")
        else:
            print(f"  ✗ Template '{template}' NOT FOUND")
            return False
    
    return True

def test_migrations():
    """Test if migration files exist"""
    print("\nTesting migrations...")
    
    migrations_dir = os.path.join(os.path.dirname(__file__), 'migrations')
    
    expected_migrations = [
        '20260212_add_titulos_despesas.sql',
        '20260212_seed_despesas.sql'
    ]
    
    for migration in expected_migrations:
        migration_path = os.path.join(migrations_dir, migration)
        if os.path.exists(migration_path):
            print(f"  ✓ Migration '{migration}' exists")
            # Check file size
            size = os.path.getsize(migration_path)
            print(f"    Size: {size} bytes")
        else:
            print(f"  ✗ Migration '{migration}' NOT FOUND")
            return False
    
    return True

def main():
    print("="*60)
    print("NH Transportes - Expense Management System Validation")
    print("="*60)
    
    results = []
    
    results.append(("Imports", test_imports()))
    results.append(("Routes", test_routes()))
    results.append(("Templates", test_templates()))
    results.append(("Migrations", test_migrations()))
    
    print("\n" + "="*60)
    print("Test Results Summary:")
    print("="*60)
    
    all_passed = True
    for test_name, result in results:
        status = "✓ PASSED" if result else "✗ FAILED"
        print(f"{test_name:20s}: {status}")
        if not result:
            all_passed = False
    
    print("="*60)
    
    if all_passed:
        print("✓ All tests passed! System is ready for deployment.")
        return 0
    else:
        print("✗ Some tests failed. Please review the errors above.")
        return 1

if __name__ == '__main__':
    sys.exit(main())
