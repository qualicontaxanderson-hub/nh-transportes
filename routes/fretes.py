from flask import Blueprint, render_template, request, redirect, url_for, flash
# Atualizado em 16/11/2025 às 20:47 - VERSÃO COM DEBUG
from flask_login import login_required
from config import Config
import mysql.connector
from datetime import datetime

bp = Blueprint('fretes', __name__, url_prefix='/fretes')

def get_db():
    return mysql.connector.connect(
        host=Config.DB_HOST,
        port=Config.DB_PORT,
        user=Config.DB_USER,
        password=Config.DB_PASSWORD,
        database=Config.DB_NAME
    )

@bp.route('/')
@login_required
def lista():
    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        
        cursor.execute("""
            SELECT f.*, 
                   c.razao_social as cliente_nome,
                   fo.nome as fornecedor_nome,
                   m.nome as motorista_nome,
                   v.placa as veiculo_placa,
                   q.valor as quantidade_valor,
                   o.nome as origem_nome,
                   d.nome as destino_nome
            FROM fretes f
            LEFT JOIN clientes c ON f.clientes_id = c.id
            LEFT JOIN fornecedores fo ON f.fornecedores_id = fo.id
            LEFT JOIN motoristas m ON f.motoristas_id = m.id
            LEFT JOIN veiculos v ON f.veiculos_id = v.id
            LEFT JOIN quantidades q ON f.quantidade_id = q.id
            LEFT JOIN origens o ON f.origem_id = o.id
            LEFT JOIN destinos d ON f.destino_id = d.id
            ORDER BY f.data_frete DESC
        """)
        
        fretes = cursor.fetchall()
        
        # Buscar clientes e motoristas para filtros
        cursor.execute("SELECT id, razao_social FROM clientes ORDER BY razao_social")
        clientes = cursor.fetchall()
        
        cursor.execute("SELECT id, nome FROM motoristas ORDER BY nome")
        motoristas = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        return render_template('fretes/lista.html', 
                             fretes=fretes,
                             clientes=clientes,
                             motoristas=motoristas)
    except Exception as e:
        print(f"Erro ao listar fretes: {e}")
        flash(f'Erro ao carregar lista de fretes: {str(e)}', 'danger')
        return redirect(url_for('index'))

@bp.route('/novo', methods=['GET', 'POST'])
@login_required
def novo():
    if request.method == 'POST':
        try:
            conn = get_db()
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO fretes (
                    clientes_id, fornecedores_id, motoristas_id, veiculos_id,
                    quantidade_id, origem_id, destino_id,
                    preco_produto_unitario, total_nf_compra,
                    preco_por_litro, valor_total_frete, comissao_motorista,
                    valor_cte, comissao_cte, lucro,
                    data_frete, status, observacoes
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                request.form['clientes_id'],
                request.form['fornecedores_id'],
                request.form['motoristas_id'],
                request.form['veiculos_id'],
                request.form['quantidade_id'],
                request.form['origem_id'],
                request.form['destino_id'],
                request.form['preco_produto_unitario'],
                request.form['total_nf_compra'],
                request.form['preco_por_litro'],
                request.form['valor_total_frete'],
                request.form['comissao_motorista'],
                request.form['valor_cte'],
                request.form['comissao_cte'],
                request.form['lucro'],
                request.form['data_frete'],
                request.form['status'],
                request.form.get('observacoes', '')
            ))
            
            conn.commit()
            cursor.close()
            conn.close()
            
            flash('Frete cadastrado com sucesso!', 'success')
            return redirect(url_for('fretes.lista'))
            
        except Exception as e:
            print(f"Erro ao cadastrar frete: {e}")
            flash(f'Erro ao cadastrar frete: {str(e)}', 'danger')
            return redirect(url_for('fretes.novo'))
    
    try:
        print("=" * 80)
        print("🔍 DEBUG: Entrando na função novo() - VERSÃO 20:47 - ARQUIVO ATUALIZADO")
        print("=" * 80)
        
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        
        print("📋 DEBUG: Executando query de clientes com razao_social...")
        print("SQL: SELECT id, razao_social, paga_comissao FROM clientes ORDER BY razao_social")
        
        # CORRIGIDO: Buscar apenas os campos que existem
        cursor.execute("SELECT id, razao_social, paga_comissao FROM clientes ORDER BY razao_social")
        clientes = cursor.fetchall()
        print(f"✅ DEBUG: {len(clientes)} clientes carregados com sucesso!")
        if clientes:
            print(f"   Exemplo: {clientes[0]}")
        
        print("📋 DEBUG: Executando query de fornecedores...")
        cursor.execute("SELECT id, nome FROM fornecedores ORDER BY nome")
        fornecedores = cursor.fetchall()
        print(f"✅ DEBUG: {len(fornecedores)} fornecedores carregados")
        
        print("📋 DEBUG: Executando query de motoristas...")
        cursor.execute("SELECT id, nome FROM motoristas ORDER BY nome")
        motoristas = cursor.fetchall()
        print(f"✅ DEBUG: {len(motoristas)} motoristas carregados")
        
        print("📋 DEBUG: Executando query de veiculos...")
        cursor.execute("SELECT id, placa, modelo FROM veiculos ORDER BY placa")
        veiculos = cursor.fetchall()
        print(f"✅ DEBUG: {len(veiculos)} veículos carregados")
        
        print("📋 DEBUG: Executando query de quantidades...")
        cursor.execute("SELECT id, valor, descricao FROM quantidades ORDER BY valor")
        quantidades = cursor.fetchall()
        print(f"✅ DEBUG: {len(quantidades)} quantidades carregadas")
        
        print("📋 DEBUG: Executando query de origens...")
        cursor.execute("SELECT id, nome FROM origens ORDER BY nome")
        origens = cursor.fetchall()
        print(f"✅ DEBUG: {len(origens)} origens carregadas")
        
        print("📋 DEBUG: Executando query de destinos...")
        cursor.execute("SELECT id, nome FROM destinos ORDER BY nome")
        destinos = cursor.fetchall()
        print(f"✅ DEBUG: {len(destinos)} destinos carregados")
        
        cursor.close()
        conn.close()
        
        print("🎉 DEBUG: Todas as queries executadas com sucesso! Renderizando template...")
        print("=" * 80)
        
        return render_template('fretes/novo.html',
                             clientes=clientes,
                             fornecedores=fornecedores,
                             motoristas=motoristas,
                             veiculos=veiculos,
                             quantidades=quantidades,
                             origens=origens,
                             destinos=destinos)
    except Exception as e:
        print("=" * 80)
        print(f"❌ DEBUG: ERRO CAPTURADO: {e}")
        print(f"❌ DEBUG: Tipo do erro: {type(e)}")
        print("=" * 80)
        print(f"Erro ao carregar formulário: {e}")
        flash(f'Erro ao carregar formulário: {str(e)}', 'danger')
        return redirect(url_for('index'))

@bp.route('/editar/<int:id>', methods=['GET', 'POST'])
@login_required
def editar(id):
    if request.method == 'POST':
        try:
            conn = get_db()
            cursor = conn.cursor()
            
            cursor.execute("""
                UPDATE fretes SET
                    clientes_id = %s, fornecedores_id = %s, motoristas_id = %s, veiculos_id = %s,
                    quantidade_id = %s, origem_id = %s, destino_id = %s,
                    preco_produto_unitario = %s, total_nf_compra = %s,
                    preco_por_litro = %s, valor_total_frete = %s, comissao_motorista = %s,
                    valor_cte = %s, comissao_cte = %s, lucro = %s,
                    data_frete = %s, status = %s, observacoes = %s
                WHERE id = %s
            """, (
                request.form['clientes_id'],
                request.form['fornecedores_id'],
                request.form['motoristas_id'],
                request.form['veiculos_id'],
                request.form['quantidade_id'],
                request.form['origem_id'],
                request.form['destino_id'],
                request.form['preco_produto_unitario'],
                request.form['total_nf_compra'],
                request.form['preco_por_litro'],
                request.form['valor_total_frete'],
                request.form['comissao_motorista'],
                request.form['valor_cte'],
                request.form['comissao_cte'],
                request.form['lucro'],
                request.form['data_frete'],
                request.form['status'],
                request.form.get('observacoes', ''),
                id
            ))
            
            conn.commit()
            cursor.close()
            conn.close()
            
            flash('Frete atualizado com sucesso!', 'success')
            return redirect(url_for('fretes.lista'))
            
        except Exception as e:
            print(f"Erro ao atualizar frete: {e}")
            flash(f'Erro ao atualizar frete: {str(e)}', 'danger')
            return redirect(url_for('fretes.editar', id=id))
    
    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        
        cursor.execute("SELECT * FROM fretes WHERE id = %s", (id,))
        frete = cursor.fetchone()
        
        if not frete:
            flash('Frete não encontrado', 'danger')
            return redirect(url_for('fretes.lista'))
        
        cursor.execute("SELECT id, razao_social, paga_comissao FROM clientes ORDER BY razao_social")
        clientes = cursor.fetchall()
        
        cursor.execute("SELECT id, nome FROM fornecedores ORDER BY nome")
        fornecedores = cursor.fetchall()
        
        cursor.execute("SELECT id, nome FROM motoristas ORDER BY nome")
        motoristas = cursor.fetchall()
        
        cursor.execute("SELECT id, placa, modelo FROM veiculos ORDER BY placa")
        veiculos = cursor.fetchall()
        
        cursor.execute("SELECT id, valor, descricao FROM quantidades ORDER BY valor")
        quantidades = cursor.fetchall()
        
        cursor.execute("SELECT id, nome FROM origens ORDER BY nome")
        origens = cursor.fetchall()
        
        cursor.execute("SELECT id, nome FROM destinos ORDER BY nome")
        destinos = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        return render_template('fretes/editar.html',
                             frete=frete,
                             clientes=clientes,
                             fornecedores=fornecedores,
                             motoristas=motoristas,
                             veiculos=veiculos,
                             quantidades=quantidades,
                             origens=origens,
                             destinos=destinos)
    except Exception as e:
        print(f"Erro ao carregar formulário: {e}")
        flash(f'Erro ao carregar formulário: {str(e)}', 'danger')
        return redirect(url_for('fretes.lista'))

@bp.route('/deletar/<int:id>', methods=['POST'])
@login_required
def deletar(id):
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute("DELETE FROM fretes WHERE id = %s", (id,))
        conn.commit()
        
        cursor.close()
        conn.close()
        
        flash('Frete excluído com sucesso!', 'success')
    except Exception as e:
        print(f"Erro ao deletar frete: {e}")
        flash(f'Erro ao excluir frete: {str(e)}', 'danger')
    
    return redirect(url_for('fretes.lista'))
