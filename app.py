import os
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

from routes import clientes, fornecedores, fretes, motoristas, veiculos, relatorios

app.register_blueprint(clientes.bp)
app.register_blueprint(fornecedores.bp)
app.register_blueprint(fretes.bp)
app.register_blueprint(motoristas.bp)
app.register_blueprint(veiculos.bp)
app.register_blueprint(relatorios.bp)

def init_db():
    print("📊 Iniciando inicialização do banco de dados...")
    try:
        print(f"🔗 Tentando conectar em: {Config.DB_HOST}:{Config.DB_PORT}")
        conn = mysql.connector.connect(
            host=Config.DB_HOST,
            port=Config.DB_PORT,
            user=Config.DB_USER,
            password=Config.DB_PASSWORD,
            database=Config.DB_NAME
        )
        print("✅ Conexão com banco estabelecida!")
        
        cursor = conn.cursor()
        print("📋 Criando tabelas...")
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS usuarios (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(50) UNIQUE NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                nome_completo VARCHAR(100) NOT NULL,
                nivel ENUM('admin', 'operador') DEFAULT 'operador',
                ativo BOOLEAN DEFAULT TRUE,
                data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        print("✓ Tabela usuarios criada")
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS clientes (
                id INT AUTO_INCREMENT PRIMARY KEY,
                razao_social VARCHAR(200) NOT NULL,
                nome_fantasia VARCHAR(200),
                cnpj VARCHAR(18),
                ie_goias VARCHAR(15),
                logradouro VARCHAR(200),
                numero VARCHAR(20),
                bairro VARCHAR(100),
                cidade VARCHAR(100),
                uf VARCHAR(2),
                cep VARCHAR(10),
                telefone VARCHAR(20),
                email VARCHAR(100),
                observacoes TEXT,
                data_cadastro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        print("✓ Tabela clientes criada")
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS fornecedores (
                id INT AUTO_INCREMENT PRIMARY KEY,
                nome VARCHAR(200) NOT NULL,
                cnpj VARCHAR(18),
                telefone VARCHAR(20),
                email VARCHAR(100),
                observacoes TEXT,
                data_cadastro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        print("✓ Tabela fornecedores criada")
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS motoristas (
                id INT AUTO_INCREMENT PRIMARY KEY,
                nome VARCHAR(200) NOT NULL,
                cpf VARCHAR(14),
                cnh VARCHAR(20),
                telefone VARCHAR(20),
                observacoes TEXT,
                data_cadastro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        print("✓ Tabela motoristas criada")
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS veiculos (
                id INT AUTO_INCREMENT PRIMARY KEY,
                placa VARCHAR(10) NOT NULL,
                modelo VARCHAR(100),
                ano INT,
                observacoes TEXT,
                data_cadastro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        print("✓ Tabela veiculos criada")
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS lancamento_frete (
                id INT AUTO_INCREMENT PRIMARY KEY,
                cliente_id INT,
                fornecedor_id INT,
                motorista_id INT,
                veiculo_id INT,
                data_frete DATE,
                origem VARCHAR(200),
                destino VARCHAR(200),
                produto VARCHAR(200),
                quantidade DECIMAL(10,2),
                vlr_total_frete DECIMAL(10,2),
                vlr_adiantamento DECIMAL(10,2),
                lucro DECIMAL(10,2),
                observacoes TEXT,
                data_cadastro TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (cliente_id) REFERENCES clientes(id),
                FOREIGN KEY (fornecedor_id) REFERENCES fornecedores(id),
                FOREIGN KEY (motorista_id) REFERENCES motoristas(id),
                FOREIGN KEY (veiculo_id) REFERENCES veiculos(id)
            )
        """)
        print("✓ Tabela lancamento_frete criada")
        
        cursor.execute("SELECT COUNT(*) FROM usuarios WHERE username = 'admin'")
        if cursor.fetchone()[0] == 0:
            print("👤 Criando usuário admin...")
            password_hash = generate_password_hash('admin123')
            cursor.execute("""
                INSERT INTO usuarios (username, password_hash, nome_completo, nivel)
                VALUES ('admin', %s, 'Administrador', 'admin')
            """, (password_hash,))
            conn.commit()
            print("✅ Usuário admin criado com sucesso!")
        else:
            print("ℹ️  Usuário admin já existe")
        
        cursor.close()
        conn.close()
        print("✅ Inicialização do banco concluída!")
        
    except mysql.connector.Error as err:
        print(f"❌ ERRO DE BANCO DE DADOS: {err}")
        print(f"Código do erro: {err.errno}")
        print(f"Mensagem: {err.msg}")
    except Exception as e:
        print(f"❌ ERRO GERAL: {str(e)}")
        import traceback
        traceback.print_exc()

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

if __name__ == '__main__':
    print("🚀 Iniciando NH Transportes...")
    init_db()
    print("🌐 Sistema online!")
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)), debug=False)
