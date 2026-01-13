"""
Arquivo de integração do módulo POSTO
Para ativar, adicione no app.py:

    from blueprints_posto import registrar_blueprints_posto
    registrar_blueprints_posto(app)

Criado em: 2026-01-13
"""

def registrar_blueprints_posto(app):
    """
    Registra os blueprints do módulo POSTO no app Flask
    
    Args:
        app: Instância do Flask app
    """
    try:
        # Importar blueprint do posto
        from routes.posto import posto_bp
        
        # Registrar blueprint
        app.register_blueprint(posto_bp)
        
        print("✅ Blueprint POSTO registrado com sucesso!")
        print("   Rotas disponíveis:")
        print("   - /posto/vendas (lista)")
        print("   - /posto/vendas/lancar (novo lançamento)")
        print("   - /posto/admin/clientes (gerenciar produtos)")
        
        return True
        
    except Exception as e:
        print(f"❌ Erro ao registrar blueprint POSTO: {e}")
        return False
