import os
import sys
import importlib
from flask import Flask, render_template, redirect, url_for, request, flash
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash
from models.usuario import Usuario
from config import Config
import mysql.connector

app = Flask(__name__)
app.config.from_object(Config)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return Usuario.get_by_id(user_id)

# Importar blueprints após definir 'app'
from routes import clientes, fornecedores, fretes, motoristas, veiculos, relatorios, debug_bp

# (Opcional: Forçar reload do módulo routes/fretes)
if 'routes.fretes' in sys.modules:
    importlib.reload(sys.modules['routes.fretes'])

# Registrar blueprints
app.register_blueprint(clientes.bp)
app.register_blueprint(fornecedores.bp)
app.register_blueprint(fretes.bp)  # <-- este ativa a listagem/cadastro de fretes!
app.register_blueprint(motoristas.bp)
app.register_blueprint(veiculos.bp)
app.register_blueprint(relatorios.bp)
app.register_blueprint(debug_bp)

def get_db():
    return mysql.connector.connect(
        host=Config.DB_HOST,
        port=Config.DB_PORT,
        user=Config.DB_USER,
        password=Config.DB_PASSWORD,
        database=Config.DB_NAME
    )

def init_db():
    # ... (mantenha seu bloco de criação de tabelas e dados que você já tem aqui)
    pass

@app.route('/health')
def health():
    return {'status': 'ok'}, 200

@app.route('/')
@login_required
def index():
    return render_template('dashboard.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = Usuario.authenticate(username, password)
        if user:
            login_user(user)
            next_page = request.args.get('next')
            return redirect(next_page or url_for('index'))
        flash('Usuário ou senha incorretos', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# Script de migração etc, caso necessário.

if __name__ == '__main__':
    print("🚀 Iniciando NH Transportes...")
    # (Descomente se usar realmente a função de inicialização do banco)
    # init_db()
    print("🌐 Sistema online!")
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)), debug=False)
