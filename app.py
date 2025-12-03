import os
from flask import Flask, render_template, redirect, url_for, request, flash, session, jsonify
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from models.usuario import Usuario
from utils.db import get_db_connection
from werkzeug.security import generate_password_hash
from utils.decorators import admin_required

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'sua-chave-secreta-aqui')

# Configuração do Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = None

@login_manager.user_loader
def load_user(user_id):
    return Usuario.get_by_id(int(user_id))

# Importar pacotes/blueprints
from routes import (
    clientes,
    fornecedores,
    veiculos,
    motoristas,
    fretes,
    rotas,
    origens_destinos,
    quilometragem,
    produtos,
    relatorios,
    arla,
    pedidos,
    bases,  # se existir
)

# Registrar blueprints de forma defensiva (loga se algum módulo não tiver bp)
blueprint_modules = {
    'clientes': clientes,
    'fornecedores': fornecedores,
    'veiculos': veiculos,
    'motoristas': motoristas,
    'fretes': fretes,
    'rotas': rotas,
    'origens_destinos': origens_destinos,
    'quilometragem': quilometragem,
    'produtos': produtos,
    'relatorios': relatorios,
    'arla': arla,
    'pedidos': pedidos,
    'bases': bases,
}

for name, mod in blueprint_modules.items():
    try:
        if hasattr(mod, 'bp'):
            app.register_blueprint(mod.bp)
            app.logger.debug(f"Registered blueprint: {name}")
        else:
            app.logger.error(f"Module routes.{name} has no attribute 'bp' (blueprint not registered).")
    except Exception as e:
        # Não deixar o app morrer aqui — logamos o erro para inspeção
        app.logger.exception(f"Error registering blueprint routes.{name}: {e}")

# Rota principal (Dashboard)
@app.route('/')
@login_required
def index():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # Contadores principais
        cursor.execute("SELECT COUNT(*) as total FROM clientes")
        total_clientes = cursor.fetchone()['total']

        cursor.execute("SELECT COUNT(*) as total FROM fornecedores")
        total_fornecedores = cursor.fetchone()['total']

        cursor.execute("SELECT COUNT(*) as total FROM veiculos")
        total_veiculos = cursor.fetchone()['total']

        cursor.execute("SELECT COUNT(*) as total FROM motoristas")
        total_motoristas = cursor.fetchone()['total']

        # Contadores de fretes e pedidos
        cursor.execute("SELECT COUNT(*) as total FROM fretes")
        total_fretes = cursor.fetchone()['total']

        cursor.execute("SELECT COUNT(*) as total FROM pedidos")
        total_pedidos = cursor.fetchone()['total']

        return render_template(
            'dashboard.html',
            total_clientes=total_clientes,
            total_fornecedores=total_fornecedores,
            total_veiculos=total_veiculos,
            total_motoristas=total_motoristas,
            total_fretes=total_fretes,
            total_pedidos=total_pedidos,
        )

    finally:
        cursor.close()
        conn.close()

# ... o restante do arquivo permanece igual (login/logout/cadastro/usuarios etc) ...
# Copie daqui para baixo todo o conteúdo que já tinha (rotas de login, logout, usuários, etc).
# Mantive apenas o trecho inicial e o registro de blueprints que é o que precisamos consertar.
if __name__ == '__main__':
    app.run(debug=True)
