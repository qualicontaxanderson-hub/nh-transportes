from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from utils.db import get_db_connection

bp = Blueprint('fretes', __name__, url_prefix='/fretes')

@bp.route('/novo', methods=['GET', 'POST'])
@login_required
def novo():
    if request.method == 'POST':
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO fretes (clientes_id, fornecedores_id, motoristas_id, veiculos_id, quantidade_id, origem_id, destino_id, preco_produto_unitario, total_nf_compra, preco_por_litro, valor_total_frete, comissao_motorista, valor_cte, comissao_cte, lucro, data_frete, status, observacoes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                request.form.get('clientes_id'),
                request.form.get('fornecedores_id'),
                request.form.get('motoristas_id'),
                request.form.get('veiculos_id'),
                request.form.get('quantidade_id'),
                request.form.get('origem_id'),
                request.form.get('destino_id'),
                request.form.get('preco_produto_unitario'),
                request.form.get('total_nf_compra'),
                request.form.get('preco_por_litro'),
                request.form.get('valor_total_frete'),
                request.form.get('comissao_motorista'),
                request.form.get('valor_cte'),
                request.form.get('comissao_cte'),
                request.form.get('lucro'),
                request.form.get('data_frete'),
                request.form.get('status'),
                request.form.get('observacoes')
            ))
            conn.commit()
            cursor.close()
            conn.close()
            flash('Frete cadastrado com sucesso!', 'success')
            return redirect(url_for('fretes.lista'))
        except Exception as e:
            print(f'Erro ao cadastrar frete: {e}')
            flash(f'Erro ao cadastrar frete: {str(e)}', 'danger')
            return redirect(url_for('fretes.novo'))
    
    # GET - Carrega dados para formulário
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # IMPORTANTE: Adicionar paga_comissao dos clientes e motoristas
        cursor.execute("""
            SELECT id, razao_social, paga_comissao, percentual_cte 
            FROM clientes 
            ORDER BY razao_social
        """)
        clientes = cursor.fetchall()
        
        cursor.execute("""
            SELECT id, razao_social 
            FROM fornecedores 
            ORDER BY razao_social
        """)
        fornecedores = cursor.fetchall()
        
        # IMPORTANTE: Adicionar paga_comissao dos motoristas
        cursor.execute("""
            SELECT id, nome, paga_comissao 
            FROM motoristas 
            ORDER BY nome
        """)
        motoristas = cursor.fetchall()
        
        cursor.execute("""
            SELECT id, caminhao, placa 
            FROM veiculos 
            ORDER BY placa
        """)
        veiculos = cursor.fetchall()
        
        cursor.execute("""
            SELECT id, valor, descricao 
            FROM quantidades 
            ORDER BY valor
        """)
        quantidades = cursor.fetchall()
        
        cursor.execute("""
            SELECT id, nome 
            FROM origens 
            ORDER BY nome
        """)
        origens = cursor.fetchall()
        
        cursor.execute("""
            SELECT id, nome 
            FROM destinos 
            ORDER BY nome
        """)
        destinos = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        return render_template(
            'fretes/novo.html',
            clientes=clientes,
            fornecedores=fornecedores,
            motoristas=motoristas,
            veiculos=veiculos,
            quantidades=quantidades,
            origens=origens,
            destinos=destinos
        )
    except Exception as e:
        print(f'Erro ao carregar formulário: {e}')
        flash(f'Erro ao carregar formulário: {str(e)}', 'danger')
        return redirect(url_for('index'))

@bp.route('/lista')
@login_required
def lista():
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        cursor.execute("""
            SELECT f.*, 
                   c.razao_social AS cliente_nome, 
                   fo.razao_social AS fornecedor_nome, 
                   m.nome AS motorista_nome, 
                   v.placa AS veiculo_placa, 
                   q.valor AS quantidade_valor, 
                   o.nome AS origem_nome, 
                   d.nome AS destino_nome
            FROM fretes f
            LEFT JOIN clientes c ON f.clientes_id = c.id
            LEFT JOIN fornecedores fo ON f.fornecedores_id = fo.id
            LEFT JOIN motoristas m ON f.motoristas_id = m.id
            LEFT JOIN veiculos v ON f.veiculos_id = v.id
            LEFT JOIN quantidades q ON f.quantidade_id = q.id
            LEFT JOIN origens o ON f.origem_id = o.id
            LEFT JOIN destinos d ON f.destino_id = d.id
            ORDER BY f.id DESC
        """)
        fretes = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        return render_template('fretes/lista.html', fretes=fretes)
    except Exception as e:
        print(f'Erro ao carregar lista de fretes: {e}')
        flash(f'Erro ao carregar lista de fretes: {str(e)}', 'danger')
        return redirect(url_for('index'))

@bp.route('/deletar/<int:id>', methods=['POST', 'GET'])
@login_required
def deletar(id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM fretes WHERE id = %s', (id,))
        conn.commit()
        cursor.close()
        conn.close()
        flash('Frete excluído com sucesso!', 'success')
    except Exception as e:
        flash(f'Erro ao excluir frete: {str(e)}', 'danger')
    
    return redirect(url_for('fretes.lista'))

@bp.route('/editar/<int:id>', methods=['GET', 'POST'])
@login_required
def editar(id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        if request.method == 'POST':
            cursor.execute("""
                UPDATE fretes 
                SET clientes_id=%s, fornecedores_id=%s, motoristas_id=%s, veiculos_id=%s, 
                    quantidade_id=%s, origem_id=%s, destino_id=%s, preco_produto_unitario=%s, 
                    total_nf_compra=%s, preco_por_litro=%s, valor_total_frete=%s, 
                    comissao_motorista=%s, valor_cte=%s, comissao_cte=%s, lucro=%s, 
                    data_frete=%s, status=%s, observacoes=%s
                WHERE id=%s
            """, (
                request.form.get('clientes_id'),
                request.form.get('fornecedores_id'),
                request.form.get('motoristas_id'),
                request.form.get('veiculos_id'),
                request.form.get('quantidade_id'),
                request.form.get('origem_id'),
                request.form.get('destino_id'),
                request.form.get('preco_produto_unitario'),
                request.form.get('total_nf_compra'),
                request.form.get('preco_por_litro'),
                request.form.get('valor_total_frete'),
                request.form.get('comissao_motorista'),
                request.form.get('valor_cte'),
                request.form.get('comissao_cte'),
                request.form.get('lucro'),
                request.form.get('data_frete'),
                request.form.get('status'),
                request.form.get('observacoes'),
                id
            ))
            conn.commit()
            cursor.close()
            conn.close()
            flash('Frete atualizado com sucesso!', 'success')
            return redirect(url_for('fretes.lista'))
        
        # GET - Carrega dados para edição
        cursor.execute('SELECT * FROM fretes WHERE id = %s', (id,))
        frete = cursor.fetchone()
        
        cursor.execute("""
            SELECT id, razao_social, paga_comissao, percentual_cte 
            FROM clientes 
            ORDER BY razao_social
        """)
        clientes = cursor.fetchall()
        
        cursor.execute("""
            SELECT id, razao_social 
            FROM fornecedores 
            ORDER BY razao_social
        """)
        fornecedores = cursor.fetchall()
        
        cursor.execute("""
            SELECT id, nome, paga_comissao 
            FROM motoristas 
            ORDER BY nome
        """)
        motoristas = cursor.fetchall()
        
        cursor.execute("""
            SELECT id, caminhao, placa 
            FROM veiculos 
            ORDER BY placa
        """)
        veiculos = cursor.fetchall()
        
        cursor.execute("""
            SELECT id, valor, descricao 
            FROM quantidades 
            ORDER BY valor
        """)
        quantidades = cursor.fetchall()
        
        cursor.execute("""
            SELECT id, nome 
            FROM origens 
            ORDER BY nome
        """)
        origens = cursor.fetchall()
        
        cursor.execute("""
            SELECT id, nome 
            FROM destinos 
            ORDER BY nome
        """)
        destinos = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        return render_template(
            'fretes/editar.html',
            frete=frete,
            clientes=clientes,
            fornecedores=fornecedores,
            motoristas=motoristas,
            veiculos=veiculos,
            quantidades=quantidades,
            origens=origens,
            destinos=destinos
        )
    except Exception as e:
        print(f'Erro ao editar frete: {e}')
        flash(f'Erro ao editar frete: {str(e)}', 'danger')
        return redirect(url_for('fretes.lista'))
