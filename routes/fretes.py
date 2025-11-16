from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from utils.db import get_db_connection
from utils.decorators import admin_required
from datetime import datetime

bp = Blueprint('fretes', __name__, url_prefix='/fretes')

@bp.route('/')
@login_required
def lista():
    # Receber filtros
    data_inicio = request.args.get('data_inicio', '')
    data_fim = request.args.get('data_fim', '')
    cliente_id = request.args.get('cliente_id', '')
    motorista_id = request.args.get('motorista_id', '')
    status_id = request.args.get('status_id', '')
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Construir query com filtros
    query = """
        SELECT lf.*, 
               c.razao_social as cliente_nome,
               m.nome as motorista_nome,
               p.nome as produto_nome,
               fp.status as situacao_nome,
               v.placa as veiculo_placa
        FROM lancamento_frete lf
        LEFT JOIN clientes c ON lf.clientes_id = c.id
        LEFT JOIN motoristas m ON lf.motoristas_id = m.id
        LEFT JOIN produto p ON lf.produto_id = p.id
        LEFT JOIN forma_pagamento fp ON lf.forma_pagamento_id = fp.id
        LEFT JOIN veiculos v ON lf.veiculos_id = v.id
        WHERE 1=1
    """
    params = []
    
    if data_inicio:
        query += " AND lf.data_frete >= %s"
        params.append(data_inicio)
    if data_fim:
        query += " AND lf.data_frete <= %s"
        params.append(data_fim)
    if cliente_id:
        query += " AND lf.clientes_id = %s"
        params.append(cliente_id)
    if motorista_id:
        query += " AND lf.motoristas_id = %s"
        params.append(motorista_id)
    if status_id:
        query += " AND lf.forma_pagamento_id = %s"
        params.append(status_id)
    
    query += " ORDER BY lf.data_frete DESC"
    
    cursor.execute(query, params)
    fretes = cursor.fetchall()
    
    # Carregar dados para os filtros
    cursor.execute("SELECT id, razao_social FROM clientes ORDER BY razao_social")
    clientes = cursor.fetchall()
    
    cursor.execute("SELECT id, nome FROM motoristas ORDER BY nome")
    motoristas = cursor.fetchall()
    
    cursor.execute("SELECT id, status FROM forma_pagamento")
    situacoes = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('fretes/lista.html', 
                         fretes=fretes,
                         clientes=clientes,
                         motoristas=motoristas,
                         situacoes=situacoes,
                         data_inicio=data_inicio,
                         data_fim=data_fim,
                         cliente_id=cliente_id,
                         motorista_id=motorista_id,
                         status_id=status_id)

@bp.route('/novo', methods=['GET', 'POST'])
@login_required
@admin_required
def novo():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    if request.method == 'POST':
        try:
            cursor.execute("""
                INSERT INTO lancamento_frete (
                    data_frete, clientes_id, produto_id, quantidade_id,
                    preco_produto_unitario, total_nf_compra, fornecedores_id,
                    origem_produto_id, preco_litro, vlr_total_frete,
                    motoristas_id, veiculos_id, comissao_motorista,
                    vlr_cte, comissao_cte, lucro, forma_pagamento_id
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                request.form.get('data_frete'),
                request.form.get('cliente_id') or None,
                request.form.get('produto_id') or None,
                request.form.get('quantidade_id') or None,
                request.form.get('preco_produto_unitario') or None,
                request.form.get('total_nf_compra') or None,
                request.form.get('fornecedor_id') or None,
                request.form.get('origem_produto_id') or None,
                request.form.get('preco_litro') or None,
                request.form.get('vlr_total_frete') or None,
                request.form.get('motorista_id') or None,
                request.form.get('veiculo_id') or None,
                request.form.get('comissao_motorista') or None,
                request.form.get('vlr_cte') or None,
                request.form.get('comissao_cte') or None,
                request.form.get('lucro') or None,
                request.form.get('forma_pagamento_id') or None
            ))
            conn.commit()
            flash('Frete cadastrado com sucesso!', 'success')
            cursor.close()
            conn.close()
            return redirect(url_for('fretes.lista'))
        except Exception as e:
            flash(f'Erro ao cadastrar frete: {str(e)}', 'danger')
    
    # Carregar dados para os combobox
    cursor.execute("SELECT id, razao_social FROM clientes ORDER BY razao_social")
    clientes = cursor.fetchall()
    
    cursor.execute("SELECT id, razao_social FROM fornecedores ORDER BY razao_social")
    fornecedores = cursor.fetchall()
    
    cursor.execute("SELECT id, nome FROM motoristas ORDER BY nome")
    motoristas = cursor.fetchall()
    
    cursor.execute("SELECT id, caminhao, placa FROM veiculos ORDER BY placa")
    veiculos = cursor.fetchall()
    
    cursor.execute("SELECT id, nome FROM produto ORDER BY nome")
    produtos = cursor.fetchall()
    
    cursor.execute("SELECT id, valor FROM quantidade ORDER BY id")
    quantidades = cursor.fetchall()
    
    cursor.execute("SELECT id, nome FROM origem_produto ORDER BY nome")
    origens = cursor.fetchall()
    
    cursor.execute("SELECT id, percentual FROM comissao_cte ORDER BY id")
    comissoes_cte = cursor.fetchall()
    
    cursor.execute("SELECT id, status FROM forma_pagamento")
    situacoes = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    data_hoje = datetime.now().strftime('%Y-%m-%d')
    
    return render_template('fretes/novo.html',
                         clientes=clientes,
                         fornecedores=fornecedores,
                         motoristas=motoristas,
                         veiculos=veiculos,
                         produtos=produtos,
                         quantidades=quantidades,
                         origens=origens,
                         comissoes_cte=comissoes_cte,
                         situacoes=situacoes,
                         data_hoje=data_hoje)

@bp.route('/editar/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar(id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    if request.method == 'POST':
        try:
            cursor.execute("""
                UPDATE lancamento_frete SET
                    data_frete=%s, clientes_id=%s, produto_id=%s, quantidade_id=%s,
                    preco_produto_unitario=%s, total_nf_compra=%s, fornecedores_id=%s,
                    origem_produto_id=%s, preco_litro=%s, vlr_total_frete=%s,
                    motoristas_id=%s, veiculos_id=%s, comissao_motorista=%s,
                    vlr_cte=%s, comissao_cte=%s, lucro=%s, forma_pagamento_id=%s
                WHERE id=%s
            """, (
                request.form.get('data_frete'),
                request.form.get('cliente_id') or None,
                request.form.get('produto_id') or None,
                request.form.get('quantidade_id') or None,
                request.form.get('preco_produto_unitario') or None,
                request.form.get('total_nf_compra') or None,
                request.form.get('fornecedor_id') or None,
                request.form.get('origem_produto_id') or None,
                request.form.get('preco_litro') or None,
                request.form.get('vlr_total_frete') or None,
                request.form.get('motorista_id') or None,
                request.form.get('veiculo_id') or None,
                request.form.get('comissao_motorista') or None,
                request.form.get('vlr_cte') or None,
                request.form.get('comissao_cte') or None,
                request.form.get('lucro') or None,
                request.form.get('forma_pagamento_id') or None,
                id
            ))
            conn.commit()
            flash('Frete atualizado com sucesso!', 'success')
            cursor.close()
            conn.close()
            return redirect(url_for('fretes.lista'))
        except Exception as e:
            flash(f'Erro ao atualizar frete: {str(e)}', 'danger')
    
    # Buscar o frete
    cursor.execute("SELECT * FROM lancamento_frete WHERE id = %s", (id,))
    frete = cursor.fetchone()
    
    # Carregar dados para os combobox
    cursor.execute("SELECT id, razao_social FROM clientes ORDER BY razao_social")
    clientes = cursor.fetchall()
    
    cursor.execute("SELECT id, razao_social FROM fornecedores ORDER BY razao_social")
    fornecedores = cursor.fetchall()
    
    cursor.execute("SELECT id, nome FROM motoristas ORDER BY nome")
    motoristas = cursor.fetchall()
    
    cursor.execute("SELECT id, caminhao, placa FROM veiculos ORDER BY placa")
    veiculos = cursor.fetchall()
    
    cursor.execute("SELECT id, nome FROM produto ORDER BY nome")
    produtos = cursor.fetchall()
    
    cursor.execute("SELECT id, valor FROM quantidade ORDER BY id")
    quantidades = cursor.fetchall()
    
    cursor.execute("SELECT id, nome FROM origem_produto ORDER BY nome")
    origens = cursor.fetchall()
    
    cursor.execute("SELECT id, percentual FROM comissao_cte ORDER BY id")
    comissoes_cte = cursor.fetchall()
    
    cursor.execute("SELECT id, status FROM forma_pagamento")
    situacoes = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('fretes/editar.html',
                         frete=frete,
                         clientes=clientes,
                         fornecedores=fornecedores,
                         motoristas=motoristas,
                         veiculos=veiculos,
                         produtos=produtos,
                         quantidades=quantidades,
                         origens=origens,
                         comissoes_cte=comissoes_cte,
                         situacoes=situacoes)

@bp.route('/excluir/<int:id>', methods=['POST'])
@login_required
@admin_required
def excluir(id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM lancamento_frete WHERE id = %s", (id,))
        conn.commit()
        cursor.close()
        conn.close()
        flash('Frete excluído com sucesso!', 'success')
    except Exception as e:
        flash(f'Erro ao excluir frete: {str(e)}', 'danger')
    return redirect(url_for('fretes.lista'))
