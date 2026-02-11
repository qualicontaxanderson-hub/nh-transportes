#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script de Teste Rápido - Permissões SUPERVISOR
Execute este script para verificar se a implementação está OK
"""

import sys
import os

# Adicionar o diretório do projeto ao path
sys.path.insert(0, '/home/runner/work/nh-transportes/nh-transportes')

def print_header(title):
    """Imprime cabeçalho formatado"""
    print("\n" + "="*70)
    print(f"  {title}")
    print("="*70)

def print_success(msg):
    """Imprime mensagem de sucesso"""
    print(f"✅ {msg}")

def print_error(msg):
    """Imprime mensagem de erro"""
    print(f"❌ {msg}")

def print_info(msg):
    """Imprime mensagem informativa"""
    print(f"ℹ️  {msg}")

def test_database_tables():
    """Teste 1: Verificar se as tabelas foram criadas"""
    print_header("TESTE 1: Verificar Tabelas no Banco de Dados")
    
    try:
        from utils.db import get_db_connection
        
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Verificar usuario_empresas
        cursor.execute("SHOW TABLES LIKE 'usuario_empresas'")
        if cursor.fetchone():
            print_success("Tabela 'usuario_empresas' existe")
            
            cursor.execute("DESCRIBE usuario_empresas")
            columns = cursor.fetchall()
            print_info(f"  Colunas: {', '.join([c['Field'] for c in columns])}")
        else:
            print_error("Tabela 'usuario_empresas' NÃO existe")
            return False
        
        # Verificar usuario_permissoes
        cursor.execute("SHOW TABLES LIKE 'usuario_permissoes'")
        if cursor.fetchone():
            print_success("Tabela 'usuario_permissoes' existe")
            
            cursor.execute("DESCRIBE usuario_permissoes")
            columns = cursor.fetchall()
            print_info(f"  Colunas: {', '.join([c['Field'] for c in columns])}")
        else:
            print_error("Tabela 'usuario_permissoes' NÃO existe")
            return False
        
        cursor.close()
        conn.close()
        return True
        
    except Exception as e:
        print_error(f"Erro ao verificar tabelas: {e}")
        return False

def test_usuario_model_methods():
    """Teste 2: Verificar métodos do modelo Usuario"""
    print_header("TESTE 2: Verificar Métodos do Modelo Usuario")
    
    try:
        from models.usuario import Usuario
        
        # Verificar métodos existem
        methods = [
            'get_empresas_usuario',
            'set_empresas_usuario', 
            'get_clientes_produtos_posto'
        ]
        
        all_exist = True
        for method in methods:
            if hasattr(Usuario, method):
                print_success(f"Método '{method}' existe")
            else:
                print_error(f"Método '{method}' NÃO existe")
                all_exist = False
        
        # Testar get_clientes_produtos_posto
        try:
            empresas = Usuario.get_clientes_produtos_posto()
            print_success(f"get_clientes_produtos_posto() retornou {len(empresas)} empresas")
            if empresas and len(empresas) > 0:
                print_info(f"  Exemplo: {empresas[0].get('razao_social', 'N/A')}")
        except Exception as e:
            print_error(f"Erro ao chamar get_clientes_produtos_posto(): {e}")
            all_exist = False
        
        return all_exist
        
    except Exception as e:
        print_error(f"Erro ao importar Usuario: {e}")
        return False

def test_decorator():
    """Teste 3: Verificar decorator supervisor_or_admin_required"""
    print_header("TESTE 3: Verificar Decorator")
    
    try:
        from utils.decorators import supervisor_or_admin_required
        print_success("Decorator 'supervisor_or_admin_required' existe")
        return True
    except ImportError as e:
        print_error(f"Erro ao importar decorator: {e}")
        return False

def test_route_permissions():
    """Teste 4: Verificar permissões nas rotas"""
    print_header("TESTE 4: Verificar Permissões nas Rotas")
    
    routes_to_check = [
        ('routes/caixa.py', 'caixa.py'),
        ('routes/cartoes.py', 'cartoes.py'),
        ('routes/tipos_receita_caixa.py', 'tipos_receita_caixa.py'),
    ]
    
    all_ok = True
    for module_path, filename in routes_to_check:
        try:
            filepath = f'/home/runner/work/nh-transportes/nh-transportes/{module_path}'
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            
            if 'supervisor_or_admin_required' in content:
                count = content.count('@supervisor_or_admin_required')
                print_success(f"{filename}: {count} rotas com supervisor_or_admin_required")
            else:
                print_info(f"{filename}: Não usa supervisor_or_admin_required")
                
        except Exception as e:
            print_error(f"Erro ao verificar {filename}: {e}")
            all_ok = False
    
    return all_ok

def test_templates():
    """Teste 5: Verificar templates atualizados"""
    print_header("TESTE 5: Verificar Templates")
    
    templates = [
        'templates/auth/usuarios/novo.html',
        'templates/auth/usuarios/editar.html'
    ]
    
    all_ok = True
    for template_path in templates:
        try:
            filepath = f'/home/runner/work/nh-transportes/nh-transportes/{template_path}'
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Verificar se tem campo de empresas
            if 'empresas_field' in content or 'empresas_ids' in content:
                print_success(f"{template_path.split('/')[-1]}: Campo de empresas presente")
            else:
                print_error(f"{template_path.split('/')[-1]}: Campo de empresas AUSENTE")
                all_ok = False
                
        except Exception as e:
            print_error(f"Erro ao verificar {template_path}: {e}")
            all_ok = False
    
    return all_ok

def main():
    """Função principal"""
    print("\n" + "█"*70)
    print("█" + " "*68 + "█")
    print("█" + "  TESTE RÁPIDO: PERMISSÕES SUPERVISOR".center(68) + "█")
    print("█" + " "*68 + "█")
    print("█"*70)
    
    print_info("Este script verifica se a implementação está funcionando")
    print_info("Versão: 1.0")
    print_info("Data: 2026-02-04")
    
    # Executar testes
    results = {
        'Tabelas no Banco': test_database_tables(),
        'Métodos do Modelo': test_usuario_model_methods(),
        'Decorator': test_decorator(),
        'Permissões nas Rotas': test_route_permissions(),
        'Templates': test_templates()
    }
    
    # Resumo
    print_header("RESUMO DOS TESTES")
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for test_name, result in results.items():
        status = "✅ PASSOU" if result else "❌ FALHOU"
        print(f"  {test_name:.<50} {status}")
    
    print("\n" + "-"*70)
    print(f"  Total: {passed}/{total} testes passaram")
    print("-"*70)
    
    if passed == total:
        print("\n" + "🎉"*35)
        print("🎉" + " "*68 + "🎉")
        print("🎉" + "  TODOS OS TESTES PASSARAM!".center(68) + "🎉")
        print("🎉" + "  Implementação OK - Pronto para uso!".center(68) + "🎉")
        print("🎉" + " "*68 + "🎉")
        print("🎉"*35)
        print("\n✅ Próximo passo: Teste manual no navegador")
        print("📖 Consulte: GUIA_TESTES_SUPERVISOR.md")
    else:
        print("\n⚠️  ATENÇÃO: Alguns testes falharam")
        print("📋 Verifique os erros acima e corrija")
        print("📖 Consulte a documentação para mais detalhes")
    
    print("\n" + "="*70)
    print("  Teste concluído!")
    print("="*70 + "\n")
    
    return 0 if passed == total else 1

if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  Teste interrompido pelo usuário")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Erro inesperado: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
