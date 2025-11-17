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

from routes import clientes, fornecedores, fretes, motoristas, veiculos, relatorios, debug_bp

# Forçar reload do módulo routes para evitar cache
if 'routes.fretes' in sys.modules:
        importlib.reload(sys.modules['routes.fretes'])

app.register_blueprint(clientes.bp)
app.register_blueprint(fornecedores.bp)
app.register_blueprint(fretes.bp)
app.register_blueprint(motoristas.bp)
app.register_blueprint(veiculos.bp)
app.register_blueprint(relatorios.bp)
app.register_blueprint(debug_bp)

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
        
        # Tabela usuarios
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
        
        # Tabela clientes
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
                paga_comissao BOOLEAN DEFAULT TRUE,
                observacoes TEXT,
                data_cadastro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        print("✓ Tabela clientes criada")
        
        # Tabela fornecedores
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
        
        # Tabela motoristas
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
        
        # Tabela veiculos
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
        
        # ===== NOVAS TABELAS AUXILIARES =====
        
        # Tabela quantidades
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS quantidades (
                id INT AUTO_INCREMENT PRIMARY KEY,
                valor DECIMAL(10,2) NOT NULL,
                descricao VARCHAR(50),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        print("✓ Tabela quantidades criada")
        
        # Tabela origens
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS origens (
                id INT AUTO_INCREMENT PRIMARY KEY,
                nome VARCHAR(100) NOT NULL,
                cidade VARCHAR(100),
                estado VARCHAR(2) DEFAULT 'GO',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        print("✓ Tabela origens criada")
        
        # Tabela destinos
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS destinos (
                id INT AUTO_INCREMENT PRIMARY KEY,
                nome VARCHAR(100) NOT NULL,
                cidade VARCHAR(100),
                estado VARCHAR(2) DEFAULT 'GO',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        print("✓ Tabela destinos criada")
        
        # Tabela fretes (nova estrutura)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS fretes (
                id INT AUTO_INCREMENT PRIMARY KEY,
                clientes_id INT NOT NULL,
                fornecedores_id INT NOT NULL,
                motoristas_id INT NOT NULL,
                veiculos_id INT NOT NULL,
                quantidade_id INT NOT NULL,
                origem_id INT NOT NULL,
                destino_id INT NOT NULL,
                preco_produto_unitario DECIMAL(10,2) NOT NULL,
                total_nf_compra DECIMAL(10,2) NOT NULL,
                preco_por_litro DECIMAL(10,2) NOT NULL,
                valor_total_frete DECIMAL(10,2) NOT NULL,
                comissao_motorista DECIMAL(10,2) DEFAULT 0,
                valor_cte DECIMAL(10,2) NOT NULL,
                comissao_cte DECIMAL(10,2) NOT NULL,
                lucro DECIMAL(10,2) NOT NULL,
                data_frete DATE NOT NULL,
                status VARCHAR(20) DEFAULT 'pendente',
                observacoes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                FOREIGN KEY (clientes_id) REFERENCES clientes(id),
                FOREIGN KEY (fornecedores_id) REFERENCES fornecedores(id),
                FOREIGN KEY (motoristas_id) REFERENCES motoristas(id),
                FOREIGN KEY (veiculos_id) REFERENCES veiculos(id),
                FOREIGN KEY (quantidade_id) REFERENCES quantidades(id),
                FOREIGN KEY (origem_id) REFERENCES origens(id),
                FOREIGN KEY (destino_id) REFERENCES destinos(id)
            )
        """)
        print("✓ Tabela fretes criada")
        
        # Tabela lancamento_frete (antiga - manter para compatibilidade)
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
        
        # ===== POPULAR TABELAS AUXILIARES =====
        
        # Popular quantidades
        cursor.execute("SELECT COUNT(*) FROM quantidades")
        if cursor.fetchone()[0] == 0:
            print("📦 Populando tabela quantidades...")
            quantidades_data = [
                (1000.00, '1.000 litros'),
                (2000.00, '2.000 litros'),
                (3000.00, '3.000 litros'),
                (4000.00, '4.000 litros'),
                (5000.00, '5.000 litros'),
                (6000.00, '6.000 litros'),
                (7000.00, '7.000 litros'),
                (8000.00, '8.000 litros'),
                (9000.00, '9.000 litros'),
                (10000.00, '10.000 litros'),
                (15000.00, '15.000 litros'),
                (20000.00, '20.000 litros'),
                (25000.00, '25.000 litros'),
                (30000.00, '30.000 litros')
            ]
            cursor.executemany(
                "INSERT INTO quantidades (valor, descricao) VALUES (%s, %s)",
                quantidades_data
            )
            print(f"✅ {len(quantidades_data)} quantidades populadas")
        
        # Popular origens
        cursor.execute("SELECT COUNT(*) FROM origens")
        if cursor.fetchone()[0] == 0:
            print("📍 Populando tabela origens...")
            origens_data = [
                ('SENADOR CANEDO', 'Senador Canedo', 'GO'),
                ('GOIÂNIA', 'Goiânia', 'GO'),
                ('ANÁPOLIS', 'Anápolis', 'GO'),
                ('APARECIDA DE GOIÂNIA', 'Aparecida de Goiânia', 'GO'),
                ('TRINDADE', 'Trindade', 'GO'),
                ('RIO VERDE', 'Rio Verde', 'GO'),
                ('CATALÃO', 'Catalão', 'GO'),
                ('ITUMBIARA', 'Itumbiara', 'GO'),
                ('LUZIÂNIA', 'Luziânia', 'GO'),
                ('VALPARAÍSO DE GOIÁS', 'Valparaíso de Goiás', 'GO')
            ]
            cursor.executemany(
                "INSERT INTO origens (nome, cidade, estado) VALUES (%s, %s, %s)",
                origens_data
            )
            print(f"✅ {len(origens_data)} origens populadas")
        
        # Popular destinos
        cursor.execute("SELECT COUNT(*) FROM destinos")
        if cursor.fetchone()[0] == 0:
            print("🎯 Populando tabela destinos...")
            destinos_data = [
                ('POSTO NOVO HORIZONTE', 'Goiânia', 'GO'),
                ('AUTO POSTO TERRA BRANCA', 'Senador Canedo', 'GO'),
                ('RLM COMBUSTIVEIS', 'Goiânia', 'GO'),
                ('AUTO POSTO INTEGRAÇÃO', 'Aparecida de Goiânia', 'GO'),
                ('POSTO LÍDER', 'Anápolis', 'GO'),
                ('POSTO CENTRAL', 'Trindade', 'GO'),
                ('OUTROS', 'Diversos', 'GO')
            ]
            cursor.executemany(
                "INSERT INTO destinos (nome, cidade, estado) VALUES (%s, %s, %s)",
                destinos_data
            )
            print(f"✅ {len(destinos_data)} destinos populados")
        
        # Criar usuário admin
        cursor.execute("SELECT COUNT(*) FROM usuarios WHERE username = 'admin'")
        if cursor.fetchone()[0] == 0:
            print("👤 Criando usuário admin...")
            password_hash = generate_password_hash('admin123')
            cursor.execute("""
                INSERT INTO usuarios (username, password_hash, nome_completo, nivel)
                VALUES ('admin', %s, 'Administrador', 'admin')
            """, (password_hash,))
            conn.commit()
            print("✅ Usuário admin criado com sucesso! (senha: admin123)")
        else:
            print("ℹ️  Usuário admin já existe")
        
        conn.commit()
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

@app.route('/migrar-fretes')
@login_required
def migrar_fretes():
    """Migra dados da tabela lancamento_frete para fretes"""
    try:
        conn = mysql.connector.connect(
            host=Config.DB_HOST,
            port=Config.DB_PORT,
            user=Config.DB_USER,
            password=Config.DB_PASSWORD,
            database=Config.DB_NAME
        )
        cursor = conn.cursor(dictionary=True)
        
        # Buscar todos os registros da tabela antiga
        cursor.execute("""
            SELECT * FROM lancamento_frete 
            WHERE clientes_id IS NOT NULL 
            AND motoristas_id IS NOT NULL
            ORDER BY id
        """)
        
        registros_antigos = cursor.fetchall()
        total_registros = len(registros_antigos)
        
        if total_registros == 0:
            flash('Nenhum registro válido encontrado na tabela antiga!', 'warning')
            return redirect(url_for('fretes.listar'))
        
        migrados = 0
        erros = []
        
        # Buscar IDs padrão para campos obrigatórios
        cursor.execute("SELECT id FROM quantidades LIMIT 1")
        quantidade_default = cursor.fetchone()['id']
        
        cursor.execute("SELECT id FROM origens LIMIT 1")
        origem_default = cursor.fetchone()['id']
        
        cursor.execute("SELECT id FROM destinos LIMIT 1")
        destino_default = cursor.fetchone()['id']
        
        for registro in registros_antigos:
            try:
                # Verificar se já foi migrado
                cursor.execute("SELECT id FROM fretes WHERE id = %s", (registro['id'],))
                if cursor.fetchone():
                    continue  # Já migrado
                
                clientes_id = registro['clientes_id']
                motoristas_id = registro['motoristas_id']
                
                # Verificar fornecedor
                fornecedores_id = registro.get('fornecedores_id')
                if not fornecedores_id:
                    cursor.execute("SELECT id FROM fornecedores LIMIT 1")
                    forn = cursor.fetchone()
                    fornecedores_id = forn['id'] if forn else None
                
                # Verificar veículo
                veiculos_id = registro.get('veiculos_id')
                if not veiculos_id:
                    cursor.execute("SELECT id FROM veiculos LIMIT 1")
                    veic = cursor.fetchone()
                    veiculos_id = veic['id'] if veic else None
                
                # Pular se não tiver fornecedor ou veículo
                if not fornecedores_id or not veiculos_id:
                    erros.append(f"ID {registro['id']}: falta fornecedor ou veículo")
                    continue
                
                quantidade_id = registro.get('quantidade_id') or quantidade_default
                origem_id = registro.get('origem_produto_id') or origem_default
                destino_id = destino_default
                
                # Valores financeiros
                preco_unitario = registro.get('preco_produto_unitario') or 0.00
                total_nf = registro.get('total_nf_compra') or 0.00
                preco_litro = registro.get('preco_litro') or 0.00
                vlr_frete = registro.get('vlr_total_frete') or 0.00
                comissao_mot = registro.get('comissao_motorista') or 0.00
                vlr_cte = registro.get('vlr_cte') or 0.00
                comissao_cte = registro.get('comissao_cte') or 0.00
                lucro = registro.get('lucro') or 0.00
                data_frete = registro.get('data_frete') or '2025-01-01'
                
                # Inserir na nova tabela
                cursor.execute("""
                    INSERT INTO fretes (
                        id, clientes_id, fornecedores_id, motoristas_id, 
                        veiculos_id, quantidade_id, origem_id, destino_id,
                        preco_produto_unitario, total_nf_compra, preco_por_litro,
                        valor_total_frete, comissao_motorista, valor_cte, 
                        comissao_cte, lucro, data_frete, status
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, 
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, 'concluido'
                    )
                """, (
                    registro['id'], clientes_id, fornecedores_id, motoristas_id,
                    veiculos_id, quantidade_id, origem_id, destino_id,
                    preco_unitario, total_nf, preco_litro, vlr_frete,
                    comissao_mot, vlr_cte, comissao_cte, lucro, data_frete
                ))
                
                migrados += 1
                
            except Exception as e:
                erros.append(f"ID {registro.get('id', '?')}: {str(e)}")
                continue
        
        conn.commit()
        cursor.close()
        conn.close()
        
        # Retornar página com detalhes
        return f"""
        <html>
        <head>
            <title>Migração Concluída</title>
            <style>
                body {{ font-family: Arial; padding: 40px; background: #f5f5f5; }}
                .container {{ max-width: 800px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; }}
                h1 {{ color: #2c3e50; }}
                .success {{ color: #27ae60; font-size: 24px; margin: 20px 0; }}
                .stats {{ background: #ecf0f1; padding: 15px; border-radius: 5px; margin: 20px 0; }}
                .errors {{ background: #ffe5e5; padding: 15px; border-radius: 5px; margin: 20px 0; }}
                .btn {{ background: #3498db; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px; display: inline-block; margin-top: 20px; }}
            </style>
        </head>
        <body>
            <div class=\"container\">
                <h1>🚚 Migração de Fretes</h1>
                <div class=\"success\">✅ Migração Concluída!</div>
                <div class=\"stats\">
                    <h3>📊 Estatísticas:</h3>
                    <p><strong>Total de registros encontrados:</strong> {total_registros}</p>
                    <p><strong>Registros migrados com sucesso:</strong> {migrados}</p>
                    <p><strong>Registros com erro:</strong> {len(erros)}</p>
                </div>
                {f'<div class=\"errors\"><h3>⚠️ Erros:</h3><ul>{"".join([f"<li>{e}</li>" for e in erros[:10]])}</ul></div>' if erros else ''}
                <a href=\"/fretes/\" class=\"btn\">Ver Fretes Migrados</a>
            </div>
        </body>
        </html>
        """
        
    except Exception as e:
        flash(f'Erro na migração: {str(e)}', 'danger')
        return redirect(url_for('index'))


if __name__ == '__main__':
    print("🚀 Iniciando NH Transportes...")
    init_db()
    print("🌐 Sistema online!")
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)), debug=False)
