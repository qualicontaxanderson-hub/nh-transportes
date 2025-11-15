from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required
from config import Config
import mysql.connector

bp = Blueprint('veiculos', __name__, url_prefix='/veiculos')

def get_db_connection():
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
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM veiculos ORDER BY id DESC")
        veiculos = cursor.fetchall()
        cursor.close()
        conn.close()
        return render_template('veiculos/lista.html', veiculos=veiculos)
    except Exception as e:
        flash(f'Erro ao listar veículos: {str(e)}', 'danger')
        return render_template('veiculos/lista.html', veiculos=[])

@bp.route('/novo', methods=['GET', 'POST'])
@login_required
def novo():
    if request.method == 'POST':
        try:
            placa = request.form.get('placa')
            modelo = request.form.get('modelo')
            ano = request.form.get('ano')
            observacoes = request.form.get('observacoes')
            
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO veiculos (placa, modelo, ano, observacoes)
                VALUES (%s, %s, %s, %s)
            """, (placa, modelo, ano, observacoes))
            conn.commit()
            cursor.close()
            conn.close()
            
            flash('Veículo cadastrado com sucesso!', 'success')
            return redirect(url_for('veiculos.lista'))
        except Exception as e:
            flash(f'Erro ao cadastrar veículo: {str(e)}', 'danger')
    
    return render_template('veiculos/form.html')

@bp.route('/editar/<int:id>', methods=['GET', 'POST'])
@login_required
def editar(id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    if request.method == 'POST':
        try:
            placa = request.form.get('placa')
            modelo = request.form.get('modelo')
            ano = request.form.get('ano')
            observacoes = request.form.get('observacoes')
            
            cursor.execute("""
                UPDATE veiculos 
                SET placa = %s, modelo = %s, ano = %s, observacoes = %s
                WHERE id = %s
            """, (placa, modelo, ano, observacoes, id))
            conn.commit()
            cursor.close()
            conn.close()
            
            flash('Veículo atualizado com sucesso!', 'success')
            return redirect(url_for('veiculos.lista'))
        except Exception as e:
            flash(f'Erro ao atualizar veículo: {str(e)}', 'danger')
            return redirect(url_for('veiculos.lista'))
    
    cursor.execute("SELECT * FROM veiculos WHERE id = %s", (id,))
    veiculo = cursor.fetchone()
    cursor.close()
    conn.close()
    
    if not veiculo:
        flash('Veículo não encontrado!', 'warning')
        return redirect(url_for('veiculos.lista'))
    
    return render_template('veiculos/form.html', veiculo=veiculo)

@bp.route('/excluir/<int:id>', methods=['POST'])
@login_required
def excluir(id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) as total FROM lancamento_frete WHERE veiculos_id = %s", (id,))
        result = cursor.fetchone()
        
        if result[0] > 0:
            flash(f'Não é possível excluir! Existem {result[0]} frete(s) vinculado(s).', 'danger')
        else:
            cursor.execute("DELETE FROM veiculos WHERE id = %s", (id,))
            conn.commit()
            flash('Veículo excluído com sucesso!', 'success')
        
        cursor.close()
        conn.close()
    except Exception as e:
        flash(f'Erro ao excluir: {str(e)}', 'danger')
    
    return redirect(url_for('veiculos.lista'))

@bp.route('/api/buscar')
@login_required
def api_buscar():
    try:
        termo = request.args.get('q', '')
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT id, placa, modelo 
            FROM veiculos 
            WHERE placa LIKE %s OR modelo LIKE %s
            LIMIT 10
        """, (f'%{termo}%', f'%{termo}%'))
        veiculos = cursor.fetchall()
        cursor.close()
        conn.close()
        return jsonify(veiculos)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
