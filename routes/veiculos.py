from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from utils.db import get_db_connection
from utils.decorators import admin_required

bp = Blueprint('veiculos', __name__, url_prefix='/veiculos')

@bp.route('/')
@login_required
def lista():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM veiculos ORDER BY placa")
    veiculos = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('veiculos/lista.html', veiculos=veiculos)

@bp.route('/novo', methods=['GET', 'POST'])
@login_required
@admin_required
def novo():
    if request.method == 'POST':
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO veiculos (placa, modelo, ano, observacoes)
            VALUES (%s, %s, %s, %s)
        """, (
            request.form.get('placa'),
            request.form.get('modelo'),
            request.form.get('ano'),
            request.form.get('observacoes')
        ))
        conn.commit()
        cursor.close()
        conn.close()
        flash('Veículo cadastrado com sucesso!', 'success')
        return redirect(url_for('veiculos.lista'))
    return render_template('veiculos/novo.html')
