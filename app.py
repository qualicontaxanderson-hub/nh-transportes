from flask import Flask, render_template, redirect, url_for, flash, request
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from config import Config
from models.usuario import Usuario
from utils.db import get_db_connection
from werkzeug.security import generate_password_hash

app = Flask(__name__)
app.config.from_object(Config)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Por favor, faça login para acessar esta página.'
login_manager.login_message_category = 'warning'

@login_manager.user_loader
def load_user(user_id):
    return Usuario.get_by_id(user_id)

from routes import clientes, fornecedores, fretes, motoristas, veiculos, relatorios

app.register_blueprint(clientes.bp)
app.register_blueprint(fornecedores.bp)
app.register_blueprint(fretes.bp)
app.register_blueprint(motoristas.bp)
app.register_blueprint(veiculos.bp)
app.register_blueprint(relatorios.bp)

@app.context_processor
def inject_globals():
    return {'app_name': Config.APP_NAME, 'current_user': current_user}

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = Usuario.authenticate(username, password)
        
        if user:
            login_user(user, remember=True)
            flash(f'Bem-vindo, {user.nome_completo}!', 'success')
            return redirect(request.args.get('next') or url_for('dashboard'))
        else:
            flash('Usuário ou senha incorretos!', 'danger')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Você saiu do sistema.', 'info')
    return redirect(url_for('login'))

@app.route('/')
@app.route('/dashboard')
@login_required
def dashboard():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("SELECT COUNT(*) as total FROM lancamento_frete")
    result = cursor.fetchone()
    total_fretes = result['total'] if result else 0
    
    cursor.execute("SELECT SUM(vlr_total_frete) as total FROM lancamento_frete")
    result = cursor.fetchone()
    faturamento = result['total'] if result and result['total'] else 0
    
    cursor.execute("SELECT SUM(lucro) as total FROM lancamento_frete")
    result = cursor.fetchone()
    lucro_total = result['total'] if result and result['total'] else 0
    
    cursor.execute("""
        SELECT lf.id, DATE_FORMAT(lf.data_frete, '%d/%m/%Y') as data_frete,
               c.razao_social as cliente, lf.vlr_total_frete, fp.status as situacao
        FROM lancamento_frete lf
        LEFT JOIN clientes c ON lf.cliente_id = c.id
        LEFT JOIN forma_pagamento fp ON lf.situacao_financeira_id = fp.id
        ORDER BY lf.data_frete DESC LIMIT 10
    """)
    ultimos_fretes = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    from utils.formatadores import formatar_moeda
    
    return render_template('dashboard.html', total_fretes=total_fretes,
                         faturamento=formatar_moeda(faturamento),
                         lucro_total=formatar_moeda(lucro_total),
                         ultimos_fretes=ultimos_fretes)

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id INT AUTO_INCREMENT PRIMARY KEY,
            username VARCHAR(50) UNIQUE NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            nome_completo VARCHAR(100) NOT NULL,
            nivel VARCHAR(20) NOT NULL,
            ativo BOOLEAN DEFAULT TRUE,
            data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    cursor.execute("SELECT COUNT(*) as total FROM usuarios WHERE username = 'admin'")
    result = cursor.fetchone()
    
    if result == 0:
        admin_password = generate_password_hash('admin123')
        cursor.execute("""
            INSERT INTO usuarios (username, password_hash, nome_completo, nivel)
            VALUES ('admin', %s, 'Administrador', 'admin')
        """, (admin_password,))
        print("✅ Usuário admin criado! Login: admin | Senha: admin123")
    
    conn.commit()
    cursor.close()
    conn.close()

if __name__ == '__main__':
    print("🚀 Iniciando NH Transportes...")
    init_db()
    print("🌐 Sistema online!")
    import os
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
