from flask import Flask, render_template, redirect, url_for, request, flash, session, jsonify
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from models.usuario import Usuario
from utils.db import get_db_connection
from werkzeug.security import check_password_hash, generate_password_hash
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

# Importar blueprints
from routes import clientes, fornecedores, veiculos, motoristas, fretes, rotas, origens_destinos, quilometragem

app.register_blueprint(clientes.bp)
app.register_blueprint(fornecedores.bp)
app.register_blueprint(veiculos.bp)
app.register_blueprint(motoristas.bp)
app.register_blueprint(fretes.bp)
app.register_blueprint(rotas.bp)
app.register_blueprint(origens_destinos.bp)
app.register_blueprint(quilometragem.bp)

# Rota principal (Dashboard)
@app.route('/')
@login_required
def index():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    try:
        # Estatísticas do dashboard - SEM filtro 'ativo' pois as tabelas não têm essa coluna
        cursor.execute("SELECT COUNT(*) as total FROM clientes")
        total_clientes = cursor.fetchone()['total']
        
        cursor.execute("SELECT COUNT(*) as total FROM fornecedores")
        total_fornecedores = cursor.fetchone()['total']
        
        cursor.execute("SELECT COUNT(*) as total FROM veiculos")
        total_veiculos = cursor.fetchone()['total']
        
        cursor.execute("SELECT COUNT(*) as total FROM motoristas")
        total_motoristas = cursor.fetchone()['total']
        
        return render_template('dashboard.html',
                             total_clientes=total_clientes,
                             total_fornecedores=total_fornecedores,
                             total_veiculos=total_veiculos,
                             total_motoristas=total_motoristas)
    finally:
        cursor.close()
        conn.close()

# Rotas de autenticação
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = Usuario.authenticate(username, password)
        
        if user:
            login_user(user)
            next_page = request.args.get('next')
            flash('Login realizado com sucesso!', 'success')
            return redirect(next_page if next_page else url_for('index'))
        else:
            flash('Usuário ou senha inválidos!', 'danger')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logout realizado com sucesso!', 'success')
    return redirect(url_for('login'))

# Rotas de gerenciamento de usuários
@app.route('/cadastro', methods=['GET', 'POST'])
@login_required
@admin_required
def cadastro():
    if request.method == 'POST':
        username = request.form.get('username')
        nome_completo = request.form.get('nome')
        nivel = request.form.get('nivel')
        password = request.form.get('password')
        confirmar_senha = request.form.get('confirmar_senha')
        
        if password != confirmar_senha:
            flash('As senhas não coincidem!', 'danger')
            return redirect(url_for('cadastro'))
        
        if Usuario.get_by_username(username):
            flash('Nome de usuário já existe!', 'danger')
            return redirect(url_for('cadastro'))
        
        try:
            Usuario.criar_usuario(username, nome_completo, nivel, password)
            flash('Usuário cadastrado com sucesso!', 'success')
            return redirect(url_for('listar_usuarios'))
        except Exception as e:
            flash(f'Erro ao cadastrar usuário: {str(e)}', 'danger')
    
    return render_template('cadastro.html')

@app.route('/listar_usuarios')
@login_required
@admin_required
def listar_usuarios():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    try:
        cursor.execute("""
            SELECT id, username, nome_completo as nome, nivel, ativo, data_criacao as created_at
            FROM usuarios
            ORDER BY nome_completo
        """)
        usuarios = cursor.fetchall()
        return render_template('listar_usuarios.html', usuarios=usuarios)
    finally:
        cursor.close()
        conn.close()

@app.route('/editar_usuario/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar_usuario(id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    if request.method == 'POST':
        nome_completo = request.form.get('nome')
        nivel = request.form.get('nivel')
        ativo = 1 if request.form.get('ativo') else 0
        nova_senha = request.form.get('nova_senha')
        confirmar_senha = request.form.get('confirmar_senha')
        
        try:
            if nova_senha:
                if nova_senha != confirmar_senha:
                    flash('As senhas não coincidem!', 'danger')
                    return redirect(url_for('editar_usuario', id=id))
                
                hashed_password = generate_password_hash(nova_senha)
                cursor.execute("""
                    UPDATE usuarios
                    SET nome_completo = %s, nivel = %s, ativo = %s, password_hash = %s
                    WHERE id = %s
                """, (nome_completo, nivel, ativo, hashed_password, id))
            else:
                cursor.execute("""
                    UPDATE usuarios
                    SET nome_completo = %s, nivel = %s, ativo = %s
                    WHERE id = %s
                """, (nome_completo, nivel, ativo, id))
            
            conn.commit()
            flash('Usuário atualizado com sucesso!', 'success')
            return redirect(url_for('listar_usuarios'))
        except Exception as e:
            conn.rollback()
            flash(f'Erro ao atualizar usuário: {str(e)}', 'danger')
        finally:
            cursor.close()
            conn.close()
    
    try:
        cursor.execute("SELECT id, username, nome_completo as nome, nivel, ativo FROM usuarios WHERE id = %s", (id,))
        usuario = cursor.fetchone()
        return render_template('alteracao_cadastro.html', usuario=usuario)
    finally:
        cursor.close()
        conn.close()

@app.route('/excluir_usuario/<int:id>')
@login_required
@admin_required
def excluir_usuario(id):
    if current_user.id == id:
        flash('Você não pode excluir seu próprio usuário!', 'danger')
        return redirect(url_for('listar_usuarios'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("DELETE FROM usuarios WHERE id = %s", (id,))
        conn.commit()
        flash('Usuário excluído com sucesso!', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Erro ao excluir usuário: {str(e)}', 'danger')
    finally:
        cursor.close()
        conn.close()
    
    return redirect(url_for('listar_usuarios'))

@app.route('/alterar_senha', methods=['GET', 'POST'])
@login_required
def alterar_senha():
    if request.method == 'POST':
        senha_atual = request.form.get('senha_atual')
        nova_senha = request.form.get('nova_senha')
        confirmar_senha = request.form.get('confirmar_senha')
        
        if not current_user.check_password(senha_atual):
            flash('Senha atual incorreta!', 'danger')
            return redirect(url_for('alterar_senha'))
        
        if nova_senha != confirmar_senha:
            flash('As senhas não coincidem!', 'danger')
            return redirect(url_for('alterar_senha'))
        
        try:
            current_user.alterar_senha(nova_senha)
            flash('Senha alterada com sucesso!', 'success')
            return redirect(url_for('index'))
        except Exception as e:
            flash(f'Erro ao alterar senha: {str(e)}', 'danger')
    
    return render_template('alterar_senha.html')

if __name__ == '__main__':
    app.run(debug=True)
