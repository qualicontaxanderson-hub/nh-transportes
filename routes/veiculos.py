from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required
from utils.db import get_db_connection
from utils.decorators import admin_required

bp = Blueprint('veiculos', __name__, url_prefix='/veiculos')

@bp.route('/')
@login_required
def lista():
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM veiculos ORDER BY placa")
        veiculos = cursor.fetchall()
        cursor.close()
        conn.close()
        return render_template('veiculos/lista.html', veiculos=veiculos)
    except Exception as e:
        flash(f'Erro ao carregar veículos: {str(e)}', 'danger')
        return render_template('veiculos/lista.html', veiculos=[])

@bp.route('/listar', methods=['GET'])
@login_required
def listar():
    """API endpoint para listar veículos em JSON"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM veiculos ORDER BY placa")
        veiculos = cursor.fetchall()
        cursor.close()
        conn.close()
        return jsonify(veiculos), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@bp.route('/novo', methods=['GET', 'POST'])
@login_required
@admin_required
def novo():
    if request.method == 'POST':
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO veiculos (caminhao, placa, modelo)
            VALUES (%s, %s, %s)
        """, (
            request.form.get('caminhao'),
            request.form.get('placa'),
            request.form.get('modelo')
        ))
        conn.commit()
        cursor.close()
        conn.close()
        flash('Veículo cadastrado com sucesso!', 'success')
        return redirect(url_for('veiculos.lista'))
    return render_template('veiculos/novo.html')

@bp.route('/editar/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar(id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    if request.method == 'POST':
        cursor.execute("""
            UPDATE veiculos SET caminhao=%s, placa=%s, modelo=%s
            WHERE id=%s
        """, (
            request.form.get('caminhao'),
            request.form.get('placa'),
            request.form.get('modelo'),
            id
        ))
        conn.commit()
        cursor.close()
        conn.close()
        flash('Veículo atualizado com sucesso!', 'success')
        return redirect(url_for('veiculos.lista'))
    
    cursor.execute("SELECT * FROM veiculos WHERE id = %s", (id,))
    veiculo = cursor.fetchone()
    cursor.close()
    conn.close()
    return render_template('veiculos/editar.html', veiculo=veiculo)

@bp.route('/excluir/<int:id>', methods=['POST'])
@login_required
@admin_required
def excluir(id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM veiculos WHERE id = %s", (id,))
        conn.commit()
        cursor.close()
        conn.close()
        flash('Veículo excluído com sucesso!', 'success')
    except Exception as e:
        flash(f'Erro ao excluir veículo: {str(e)}', 'danger')
    return redirect(url_for('veiculos.lista'))
