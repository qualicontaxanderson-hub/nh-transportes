from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required
import mysql.connector
import os
from utils.boletos import emitir_boleto_frete

financeiro_bp = Blueprint('financeiro', __name__, url_prefix='/financeiro')

def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv('DB_HOST'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        database=os.getenv('DB_DATABASE'),
        port=int(os.getenv('DB_PORT', 3306))
    )

@financeiro_bp.route('/recebimentos/')
@login_required
def recebimentos():
    """Lista todos os recebimentos/boletos"""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    try:
        cursor.execute("""
            SELECT 
                r.*,
                f.id as frete_numero,
                c.razaosocial as cliente_nome,
                c.nomefantasia as cliente_fantasia
            FROM recebimentos r
            LEFT JOIN fretes f ON r.frete_id = f.id
            LEFT JOIN clientes c ON r.cliente_id = c.id
            ORDER BY r.data_vencimento DESC, r.created_at DESC
        """)
        recebimentos_lista = cursor.fetchall()
        
        return render_template('financeiro/recebimentos.html', recebimentos=recebimentos_lista)
    except Exception as e:
        flash(f'Erro ao carregar recebimentos: {str(e)}', 'danger')
        return render_template('financeiro/recebimentos.html', recebimentos=[])
    finally:
        cursor.close()
        conn.close()

@financeiro_bp.route('/emitir-boleto/<int:frete_id>', methods=['POST'])
@login_required
def emitir_boleto_route(frete_id):
    """Emite boleto para um frete específico"""
    try:
        resultado = emitir_boleto_frete(frete_id)
        
        if resultado.get('success'):
            flash(f'Boleto emitido com sucesso! Charge ID: {resultado.get("charge_id")}', 'success')
            return redirect(url_for('financeiro.recebimentos'))
        else:
            flash(f'Erro ao emitir boleto: {resultado.get("error")}', 'danger')
            return redirect(url_for('fretes.lista'))
    except Exception as e:
        flash(f'Erro ao processar boleto: {str(e)}', 'danger')
        return redirect(url_for('fretes.lista'))
