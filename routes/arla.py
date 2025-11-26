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

@bp.route('/saldo-inicial', methods=['GET', 'POST'])
@login_required
def saldo_inicial():
    if request.method == 'POST':
        # Recebe dados do formulário
        data = request.form['data']
        volume_inicial = request.form['volume_inicial']
        preco_medio_compra = request.form['preco_medio_compra']
        encerrante_inicial = request.form['encerrante_inicial']

        # Inserir no banco
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
        return redirect(url_for('arla.saldo_inicial'))

    # GET: exibe o formulário
    return render_template('arla/saldo_inicial.html')
