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

# =============================================
# PÁGINA PRINCIPAL / RESUMO ARLA
# =============================================
@bp.route('/')
@login_required
def index():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT * FROM arla_saldo_inicial ORDER BY data DESC LIMIT 1
    """)
    saldo = cursor.fetchone()
    
    cursor.execute("""
        SELECT * FROM arla_lancamentos ORDER BY data DESC
    """)
    lancamentos = cursor.fetchall()
    
    cursor.execute("""
        SELECT * FROM arla_compras ORDER BY data DESC
    """)
    compras = cursor.fetchall()
    
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

# =============================================
# SALDO INICIAL - CRIAR / VISUALIZAR
# =============================================
@bp.route('/saldo-inicial', methods=['GET', 'POST'])
@login_required
def saldo_inicial():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    if request.method == 'POST':
        data = request.form['data']
        volume_inicial = request.form['volume_inicial']
        preco_medio_compra = request.form['preco_medio_compra']
        encerrante_inicial = request.form['encerrante_inicial']

        cursor.execute("""
            INSERT INTO arla_saldo_inicial (data, volume_inicial, preco_medio_compra, encerrante_inicial)
            VALUES (%s, %s, %s, %s)
        """, (data, volume_inicial, preco_medio_compra, encerrante_inicial))
        conn.commit()
        cursor.close()
        conn.close()

        flash('Saldo inicial cadastrado com sucesso!', 'success')
        return redirect(url_for('arla.index'))

    # Busca saldo existente
    cursor.execute("SELECT * FROM arla_saldo_inicial ORDER BY data DESC LIMIT 1")
    saldo = cursor.fetchone()
    cursor.close()
    conn.close()

    return render_template('arla/saldo_inicial.html', saldo=saldo)

# =============================================
# SALDO INICIAL - EDITAR
# =============================================
@bp.route('/editar-saldo-inicial/<int:id>', methods=['GET', 'POST'])
@login_required
def editar_saldo_inicial(id):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    if request.method == 'POST':
        data = request.form['data']
        volume_inicial = request.form['volume_inicial']
        preco_medio_compra = request.form['preco_medio_compra']
        encerrante_inicial = request.form['encerrante_inicial']

        cursor.execute("""
            UPDATE arla_saldo_inicial
            SET data = %s, volume_inicial = %s, preco_medio_compra = %s, encerrante_inicial = %s
            WHERE id = %s
        """, (data, volume_inicial, preco_medio_compra, encerrante_inicial, id))
        conn.commit()
        cursor.close()
        conn.close()

        flash('Saldo inicial atualizado com sucesso!', 'success')
        return redirect(url_for('arla.index'))

    cursor.execute("SELECT * FROM arla_saldo_inicial WHERE id = %s", (id,))
    saldo = cursor.fetchone()
    cursor.close()
    conn.close()

    return render_template('arla/editar_saldo_inicial.html', saldo=saldo)

# =============================================
# COMPRAS - CRIAR
# =============================================
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

# =============================================
# COMPRAS - EDITAR
# =============================================
@bp.route('/editar-compra/<int:id>', methods=['GET', 'POST'])
@login_required
def editar_compra(id):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    if request.method == 'POST':
        data = request.form['data']
        quantidade = request.form['quantidade']
        preco_compra = request.form['preco_compra']

        cursor.execute("""
            UPDATE arla_compras
            SET data = %s, quantidade = %s, preco_compra = %s
            WHERE id = %s
        """, (data, quantidade, preco_compra, id))
        conn.commit()
        cursor.close()
        conn.close()

        flash('Compra atualizada com sucesso!', 'success')
        return redirect(url_for('arla.index'))

    cursor.execute("SELECT * FROM arla_compras WHERE id = %s", (id,))
    compra = cursor.fetchone()
    cursor.close()
    conn.close()

    return render_template('arla/editar_compra.html', compra=compra)

# =============================================
# PREÇO DE VENDA - CRIAR
# =============================================
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

# =============================================
# LANÇAMENTO DIÁRIO - CRIAR
# =============================================
@bp.route('/lancamento', methods=['GET', 'POST'])
@login_required
def lancamento():
    if request.method == 'POST':
        data = request.form['data']
        encerrante_final = float(request.form['encerrante_final'])

        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        
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

# =============================================
# LANÇAMENTO DIÁRIO - EDITAR
# =============================================
@bp.route('/editar-lancamento/<int:id>', methods=['GET', 'POST'])
@login_required
def editar_lancamento(id):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    if request.method == 'POST':
        data = request.form['data']
        encerrante_final = float(request.form['encerrante_final'])

        cursor.execute("""
            SELECT encerrante_final FROM arla_lancamentos
            WHERE data < %s AND id != %s
            ORDER BY data DESC LIMIT 1
        """, (data, id))
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

        cursor.execute("""
            SELECT preco_venda FROM arla_precos_venda WHERE data_inicio <= %s
            ORDER BY data_inicio DESC LIMIT 1
        """, (data,))
        preco_row = cursor.fetchone()
        preco_venda = preco_row['preco_venda'] if preco_row else 0

        cursor.execute("""
            UPDATE arla_lancamentos
            SET data = %s, encerrante_final = %s, quantidade_vendida = %s, preco_venda_aplicado = %s
            WHERE id = %s
        """, (data, encerrante_final, quantidade_vendida, preco_venda, id))
        conn.commit()
        cursor.close()
        conn.close()

        flash('Lançamento atualizado com sucesso!', 'success')
        return redirect(url_for('arla.index'))

    cursor.execute("SELECT * FROM arla_lancamentos WHERE id = %s", (id,))
    lancamento = cursor.fetchone()
    cursor.close()
    conn.close()

    return render_template('arla/editar_lancamento.html', lancamento=lancamento)
