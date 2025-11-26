from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
import mysql.connector

bp = Blueprint('arla', __name__, url_prefix='/arla')

def get_db():
    return mysql.connector.connect(
        host='centerbeam.proxy.rlwy.net',
        port=56026,
        user='root',
        password='CYTzzRYLVmEJGDexxXpgepWgpvebdSrV',
        database='railway'
    )

# Página principal/resumo ARLA
@bp.route('/')
@login_required
def index():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    # Busca saldo inicial
    cursor.execute("""
        SELECT * FROM arla_saldo_inicial ORDER BY data DESC LIMIT 1
    """)
    saldo = cursor.fetchone()
    
    # Busca lançamentos
    cursor.execute("""
        SELECT * FROM arla_lancamentos ORDER BY data DESC
    """)
    lancamentos = cursor.fetchall()
    
    # Busca compras
    cursor.execute("""
        SELECT * FROM arla_compras ORDER BY data DESC
    """)
    compras = cursor.fetchall()
    
    # Busca preço vigente
    cursor.execute("""
        SELECT * FROM arla_precos_venda ORDER BY data_inicio DESC LIMIT 1
    """)
    preco = cursor.fetchone()
    
    cursor.close()
    conn.close()
    
    return render_template(
        'arla/index.html',
        saldo=saldo,
        lancamentos=lancamentos,
        compras=compras,
        preco=preco
    )

# Cadastro do saldo inicial
@bp.route('/saldo-inicial', methods=['GET', 'POST'])
@login_required
def saldo_inicial():
    if request.method == 'POST':
        data = request.form['data']
        volume_inicial = request.form['volume_inicial']
        preco_medio_compra = request.form['preco_medio_compra']
        encerrante_inicial = request.form['encerrante_inicial']

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO arla_saldo_inicial (data, volume_inicial, preco_medio_compra, encerrante_inicial)
            VALUES (%s, %s, %s, %s)
        """, (data, volume_inicial, preco_medio_compra, encerrante_inicial))
        conn.commit()
        cursor.close()
        conn.close()

        flash('Saldo inicial cadastrado com sucesso!', 'success')
        return redirect(url_for('arla.index'))

    return render_template('arla/saldo_inicial.html')

# Cadastro de compras
@bp.route('/compras', methods=['GET', 'POST'])
@login_required
def compras():
    if request.method == 'POST':
        data = request.form['data']
        quantidade = request.form['quantidade']
        preco_compra = request.form['preco_compra']

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO arla_compras (data, quantidade, preco_compra)
            VALUES (%s, %s, %s)
        """, (data, quantidade, preco_compra))
        conn.commit()
        cursor.close()
        conn.close()

        flash('Compra registrada com sucesso!', 'success')
        return redirect(url_for('arla.index'))

    return render_template('arla/compras.html')

# Cadastro/alteração de preço de venda
@bp.route('/preco-venda', methods=['GET', 'POST'])
@login_required
def preco_venda():
    if request.method == 'POST':
        data_inicio = request.form['data_inicio']
        preco_venda = request.form['preco_venda']

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO arla_precos_venda (data_inicio, preco_venda)
            VALUES (%s, %s)
        """, (data_inicio, preco_venda))
        conn.commit()
        cursor.close()
        conn.close()

        flash('Preço de venda alterado com sucesso!', 'success')
        return redirect(url_for('arla.index'))

    return render_template('arla/preco_venda.html')

# Cadastro de lançamento diário
@bp.route('/lancamento', methods=['GET', 'POST'])
@login_required
def lancamento():
    if request.method == 'POST':
        data = request.form['data']
        encerrante_final = float(request.form['encerrante_final'])

        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        
        # Busca o encerrante anterior (registro vigente mais recente)
        cursor.execute("""
            SELECT encerrante_final FROM arla_lancamentos
            WHERE data < %s
            ORDER BY data DESC LIMIT 1
        """, (data,))
        ante = cursor.fetchone()
        
        encerrante_anterior = ante['encerrante_final'] if ante else None
        
        if encerrante_anterior is None:
            cursor.execute("""
                SELECT encerrante_inicial FROM arla_saldo_inicial
                WHERE data <= %s ORDER BY data DESC LIMIT 1
            """, (data,))
            saldo_ini = cursor.fetchone()
            encerrante_anterior = saldo_ini['encerrante_inicial'] if saldo_ini else 0

        quantidade_vendida = encerrante_final - float(encerrante_anterior)

        # Busca o preço vigente naquele dia
        cursor.execute("""
            SELECT preco_venda FROM arla_precos_venda WHERE data_inicio <= %s
            ORDER BY data_inicio DESC LIMIT 1
        """, (data,))
        preco_row = cursor.fetchone()
        preco_venda = preco_row['preco_venda'] if preco_row else 0

        cursor.execute("""
            INSERT INTO arla_lancamentos
            (data, encerrante_final, quantidade_vendida, preco_venda_aplicado)
            VALUES (%s, %s, %s, %s)
        """, (data, encerrante_final, quantidade_vendida, preco_venda))
        conn.commit()
        cursor.close()
        conn.close()
        
        flash('Lançamento registrado com sucesso!', 'success')
        return redirect(url_for('arla.index'))

    return render_template('arla/lancamento.html')
