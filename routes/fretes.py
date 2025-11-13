from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from utils.db import get_db_connection
from datetime import datetime

bp = Blueprint('fretes', __name__, url_prefix='/fretes')

@bp.route('/')
@login_required
def lista():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT lf.*, c.razao_social as cliente_nome, p.nome as produto_nome,
               fp.status as situacao_nome, DATE_FORMAT(lf.data_frete, '%d/%m/%Y') as data_formatada
        FROM lancamento_frete lf
        LEFT JOIN clientes c ON lf.cliente_id = c.id
        LEFT JOIN produto p ON lf.produto_id = p.id
        LEFT JOIN forma_pagamento fp ON lf.situacao_financeira_id = fp.id
        ORDER BY lf.data_frete DESC
    """)
    fretes = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('fretes/lista.html', fretes=fretes)

@bp.route('/novo', methods=['GET', 'POST'])
@login_required
def novo():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    if request.method == 'POST':
        data_frete = request.form.get('data_frete')
        cliente_id = request.form.get('cliente_id')
        produto_id = request.form.get('produto_id')
        quantidade_id = request.form.get('quantidade_id')
        preco_produto_unitario = request.form.get('preco_produto_unitario')
        fornecedor_id = request.form.get('fornecedor_id') or None
        origem_produto_id = request.form.get('origem_produto_id') or None
        preco_litro_id = request.form.get('preco_litro_id')
        motorista_id = request.form.get('motorista_id')
        veiculo_id = request.form.get('veiculo_id')
        comissao_cte_id = request.form.get('comissao_cte_id')
        situacao_financeira_id = request.form.get('situacao_financeira_id')
        
        cursor.execute("SELECT litros FROM quantidade WHERE id = %s", (quantidade_id,))
        qtd_result = cursor.fetchone()
        qtd_litros = qtd_result['litros'] if qtd_result else 0
        
        cursor.execute("SELECT valor FROM preco_litro WHERE id = %s", (preco_litro_id,))
        preco_result = cursor.fetchone()
        preco_litro_valor = preco_result['valor'] if preco_result else 0
        
        vlr_total_frete = float(qtd_litros) * float(preco_litro_valor)
        comissao_motorista = vlr_total_frete * 0.10
        
        cursor.execute("SELECT percentual FROM comissao_cte WHERE id = %s", (comissao_cte_id,))
        cte_result = cursor.fetchone()
        if cte_result:
            cte_percent = float(cte_result['percentual'].replace('%', '')) / 100
            valor_comissao_cte = vlr_total_frete * cte_percent
        else:
            valor_comissao_cte = 0
        
        lucro = vlr_total_frete - comissao_motorista - valor_comissao_cte
        
        cursor.execute("""
            INSERT INTO lancamento_frete (
                data_frete, cliente_id, produto_id, quantidade_id,
                preco_produto_unitario, fornecedor_id, origem_produto_id,
                preco_litro_id, vlr_total_frete, motorista_id, veiculo_id,
                comissao_motorista, comissao_cte_id, lucro, situacao_financeira_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (data_frete, cliente_id, produto_id, quantidade_id, preco_produto_unitario,
              fornecedor_id, origem_produto_id, preco_litro_id, vlr_total_frete,
              motorista_id, veiculo_id, comissao_motorista, comissao_cte_id, lucro,
              situacao_financeira_id))
        conn.commit()
        cursor.close()
        conn.close()
        flash('Frete lançado com sucesso!', 'success')
        return redirect(url_for('fretes.lista'))
    
    cursor.execute("SELECT id, razao_social FROM clientes ORDER BY razao_social")
    clientes = cursor.fetchall()
    cursor.execute("SELECT id, nome FROM produto ORDER BY nome")
    produtos = cursor.fetchall()
    cursor.execute("SELECT id, litros FROM quantidade ORDER BY litros")
    quantidades = cursor.fetchall()
    cursor.execute("SELECT id, razao_social FROM fornecedores ORDER BY razao_social")
    fornecedores = cursor.fetchall()
    cursor.execute("SELECT id, nome FROM origem_produto ORDER BY nome")
    origens = cursor.fetchall()
    cursor.execute("SELECT id, valor FROM preco_litro ORDER BY valor")
    precos_litro = cursor.fetchall()
    cursor.execute("SELECT id, nome FROM motorista ORDER BY nome")
    motoristas = cursor.fetchall()
    cursor.execute("SELECT id, caminhao, placa FROM veiculos ORDER BY caminhao")
    veiculos = cursor.fetchall()
    cursor.execute("SELECT id, percentual FROM comissao_cte ORDER BY id")
    comissoes_cte = cursor.fetchall()
    cursor.execute("SELECT id, status FROM forma_pagamento ORDER BY id")
    situacoes = cursor.fetchall()
    cursor.close()
    conn.close()
    
    return render_template('fretes/novo.html', clientes=clientes, produtos=produtos,
                         quantidades=quantidades, fornecedores=fornecedores, origens=origens,
                         precos_litro=precos_litro, motoristas=motoristas, veiculos=veiculos,
                         comissoes_cte=comissoes_cte, situacoes=situacoes,
                         data_hoje=datetime.now().strftime('%Y-%m-%d'))
