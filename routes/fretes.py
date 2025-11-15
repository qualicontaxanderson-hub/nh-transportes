from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from utils.db import get_db_connection
from utils.decorators import admin_required

bp = Blueprint('fretes', __name__, url_prefix='/fretes')

@bp.route('/')
@login_required
def lista():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT lf.*, c.razao_social as cliente_nome
        FROM lancamento_frete lf
        LEFT JOIN clientes c ON lf.cliente_id = c.id
        ORDER BY lf.data_frete DESC
    """)
    fretes = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('fretes/lista.html', fretes=fretes)

@bp.route('/novo', methods=['GET', 'POST'])
@login_required
@admin_required
def novo():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    if request.method == 'POST':
        cursor.execute("""
            INSERT INTO lancamento_frete (
                cliente_id, fornecedor_id, motorista_id, veiculo_id,
                data_frete, origem, destino, produto, quantidade,
                vlr_total_frete, vlr_adiantamento, lucro
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            request.form.get('cliente_id'),
            request.form.get('fornecedor_id'),
            request.form.get('motorista_id'),
            request.form.get('veiculo_id'),
            request.form.get('data_frete'),
            request.form.get('origem'),
            request.form.get('destino'),
            request.form.get('produto'),
            request.form.get('quantidade'),
            request.form.get('vlr_total_frete'),
            request.form.get('vlr_adiantamento'),
            request.form.get('lucro')
        ))
        conn.commit()
        cursor.close()
        conn.close()
        flash('Frete cadastrado com sucesso!', 'success')
        return redirect(url_for('fretes.lista'))
    
    cursor.execute("SELECT id, razao_social FROM clientes ORDER BY razao_social")
    clientes = cursor.fetchall()
    cursor.execute("SELECT id, nome FROM fornecedores")
    fornecedores = cursor.fetchall()
    cursor.execute("SELECT id, nome FROM motoristas")
    motoristas = cursor.fetchall()
    cursor.execute("SELECT id, placa FROM veiculos")
    veiculos = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('fretes/novo.html', 
                         clientes=clientes,
                         fornecedores=fornecedores,
                         motoristas=motoristas,
                         veiculos=veiculos)

