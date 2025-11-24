import os
from flask import Flask, render_template, redirect, url_for, request, flash
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from models.usuario import Usuario
from models.rota import Rota
from config import Config
from models import db

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return Usuario.get_by_id(user_id)

# Importar blueprints após definir 'app'
from routes import clientes, fornecedores, fretes, motoristas, veiculos, relatorios, debug_bp, rotas, quilometragem, origens_destinos, produtos
from routes.api import api_bp

app.register_blueprint(clientes.bp)
app.register_blueprint(fornecedores.bp)
app.register_blueprint(fretes.bp)
app.register_blueprint(motoristas.bp)
app.register_blueprint(veiculos.bp)
app.register_blueprint(relatorios.bp)
app.register_blueprint(debug_bp)
app.register_blueprint(api_bp)
app.register_blueprint(rotas.bp)
app.register_blueprint(quilometragem.bp)
app.register_blueprint(origens_destinos.bp)
app.register_blueprint(produtos.bp)

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

@app.route('/alterar_senha', methods=['GET', 'POST'])
@login_required
def alterar_senha():
    if request.method == 'POST':
        senha_atual = request.form.get('senha_atual')
        senha_nova = request.form.get('senha_nova')
        confirmar_senha = request.form.get('confirmar_senha')
        
        # Validações
        if not senha_atual or not senha_nova or not confirmar_senha:
            flash('Todos os campos são obrigatórios.', 'danger')
            return render_template('alterar_senha.html')
        
        if not current_user.check_password(senha_atual):
            flash('Senha atual incorreta.', 'danger')
            return render_template('alterar_senha.html')
        
        if senha_nova != confirmar_senha:
            flash('A nova senha e a confirmação não coincidem.', 'danger')
            return render_template('alterar_senha.html')
        
        if len(senha_nova) < 6:
            flash('A senha deve ter no mínimo 6 caracteres.', 'danger')
            return render_template('alterar_senha.html')
        
        # Alterar senha
        try:
            current_user.alterar_senha(senha_nova)
            flash('Senha alterada com sucesso!', 'success')
            return redirect(url_for('index'))
        except Exception as e:
            flash(f'Erro ao alterar senha: {str(e)}', 'danger')
    
    return render_template('alterar_senha.html')

@app.route('/cadastro', methods=['GET', 'POST'])
@login_required
def cadastro():
    # Proteção: apenas admins podem criar usuários
    if current_user.nivel != 'admin':
        flash('Acesso negado. Apenas administradores podem criar usuários.', 'danger')
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        nome_completo = request.form.get('nome_completo')
        nivel = request.form.get('nivel')
        senha = request.form.get('senha')
        confirmar_senha = request.form.get('confirmar_senha')
        
        # Validações
        if not username or not nome_completo or not nivel or not senha or not confirmar_senha:
            flash('Todos os campos são obrigatórios.', 'danger')
            return render_template('cadastro.html')
        
        if senha != confirmar_senha:
            flash('As senhas não coincidem.', 'danger')
            return render_template('cadastro.html')
        
        if len(senha) < 6:
            flash('A senha deve ter no mínimo 6 caracteres.', 'danger')
            return render_template('cadastro.html')
        
        # Criar usuário
        try:
            Usuario.criar_usuario(username, nome_completo, nivel, senha)
            flash(f'Usuário {username} criado com sucesso!', 'success')
            return redirect(url_for('index'))
        except Exception as e:
            flash(f'Erro ao criar usuário: {str(e)}', 'danger')
    
    return render_template('cadastro.html')

if __name__ == '__main__':
    print("🚀 Iniciando NH Transportes...")
    print("🌐 Sistema online!")
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)), debug=False)
