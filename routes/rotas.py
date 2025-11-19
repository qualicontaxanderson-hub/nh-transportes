from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from utils.db import get_db_connection
from utils.decorators import admin_required

bp = Blueprint('rotas', __name__, url_prefix='/rotas')

@bp.route('/')
@login_required
def lista():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT r.*, 
               o.nome AS origem_nome, 
               d.nome AS destino_nome
        FROM rotas r
        LEFT JOIN origens o ON r.origem_id = o.id
        LEFT JOIN destinos d ON r.destino_id = d.id
        ORDER BY r.id DESC
    """)
    rotas = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('rotas/lista.html', rotas=rotas)

@bp.route('/novo', methods=['GET', 'POST'])
@login_required
@admin_required
def novo():
    if request.method == 'POST':
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Converter valor para decimal
        def converter_para_decimal(valor):
            if not valor:
                return 0
            return float(str(valor).replace('.', '').replace(',', '.'))
        
        valor_por_litro = converter_para_decimal(request.form.get('valor_por_litro'))
        ativo = 1 if request.form.get('ativo') in ['on', '1', 1, True] else 0
        
        cursor.execute("""
            INSERT INTO rotas (origem_id, destino_id, valor_por_litro, ativo)
            VALUES (%s, %s, %s, %s)
        """, (
            request.form.get('origem_id'),
            request.form.get('destino_id'),
            valor_por_litro,
            ativo
        ))
        conn.commit()
        cursor.close()
        conn.close()
        flash('Rota cadastrada com sucesso!', 'success')
        return redirect(url_for('rotas.lista'))
    
    # GET - Carregar origens e destinos
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("SELECT * FROM origens ORDER BY nome")
    origens = cursor.fetchall()
    
    cursor.execute("SELECT * FROM destinos ORDER BY nome")
    destinos = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('rotas/novo.html', origens=origens, destinos=destinos)

@bp.route('/editar/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar(id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    if request.method == 'POST':
        # Converter valor para decimal
        def converter_para_decimal(valor):
            if not valor:
                return 0
            return float(str(valor).replace('.', '').replace(',', '.'))
        
        valor_por_litro = converter_para_decimal(request.form.get('valor_por_litro'))
        ativo = 1 if request.form.get('ativo') in ['on', '1', 1, True] else 0
        
        cursor.execute("""
            UPDATE rotas 
            SET origem_id=%s, destino_id=%s, valor_por_litro=%s, ativo=%s
            WHERE id=%s
        """, (
            request.form.get('origem_id'),
            request.form.get('destino_id'),
            valor_por_litro,
            ativo,
            id
        ))
        conn.commit()
        cursor.close()
        conn.close()
        flash('Rota atualizada com sucesso!', 'success')
        return redirect(url_for('rotas.lista'))
    
    # GET - Carregar dados
    cursor.execute("SELECT * FROM rotas WHERE id = %s", (id,))
    rota = cursor.fetchone()
    
    cursor.execute("SELECT * FROM origens ORDER BY nome")
    origens = cursor.fetchall()
    
    cursor.execute("SELECT * FROM destinos ORDER BY nome")
    destinos = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('rotas/editar.html', rota=rota, origens=origens, destinos=destinos)

@bp.route('/excluir/<int:id>', methods=['POST'])
@login_required
@admin_required
def excluir(id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM rotas WHERE id = %s", (id,))
        conn.commit()
        cursor.close()
        conn.close()
        flash('Rota excluída com sucesso!', 'success')
    except Exception as e:
        flash(f'Erro ao excluir rota: {str(e)}', 'danger')
    return redirect(url_for('rotas.lista'))
