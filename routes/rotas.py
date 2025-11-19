from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from models import db

bp = Blueprint('rotas', __name__, url_prefix='/rotas')

def converter_para_decimal(valor):
    """Converte valores do formato brasileiro (1.234,56) para decimal (1234.56)"""
    if isinstance(valor, str):
        valor = valor.replace('.', '').replace(',', '.')
    return valor

@bp.route('/')
@login_required
def lista():
    cursor = db.cursor(dictionary=True)
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
    return render_template('rotas/lista.html', rotas=rotas)

@bp.route('/novo', methods=['GET', 'POST'])
@login_required
def novo():
    if request.method == 'POST':
        try:
            origem_id = request.form.get('origem_id')
            destino_id = request.form.get('destino_id')
            valor_por_litro = converter_para_decimal(request.form.get('valor_por_litro'))
            ativo = 1 if request.form.get('ativo') in ['on', '1', 1, True] else 0
            
            cursor = db.cursor()
            cursor.execute("""
                INSERT INTO rotas (origem_id, destino_id, valor_por_litro, ativo)
                VALUES (%s, %s, %s, %s)
            """, (origem_id, destino_id, valor_por_litro, ativo))
            
            db.commit()
            cursor.close()
            
            flash('Rota cadastrada com sucesso!', 'success')
            return redirect(url_for('rotas.lista'))
        except Exception as e:
            flash(f'Erro ao cadastrar rota: {str(e)}', 'danger')
            db.rollback()
    
    # GET - Carregar origens e destinos
    cursor = db.cursor(dictionary=True)
    
    cursor.execute("SELECT * FROM origens ORDER BY nome")
    origens = cursor.fetchall()
    
    cursor.execute("SELECT * FROM destinos ORDER BY nome")
    destinos = cursor.fetchall()
    
    cursor.close()
    
    return render_template('rotas/novo.html', origens=origens, destinos=destinos)

@bp.route('/editar/<int:id>', methods=['GET', 'POST'])
@login_required
def editar(id):
    cursor = db.cursor(dictionary=True)
    
    if request.method == 'POST':
        try:
            origem_id = request.form.get('origem_id')
            destino_id = request.form.get('destino_id')
            valor_por_litro = converter_para_decimal(request.form.get('valor_por_litro'))
            ativo = 1 if request.form.get('ativo') in ['on', '1', 1, True] else 0
            
            cursor.execute("""
                UPDATE rotas 
                SET origem_id=%s, destino_id=%s, valor_por_litro=%s, ativo=%s
                WHERE id=%s
            """, (origem_id, destino_id, valor_por_litro, ativo, id))
            
            db.commit()
            cursor.close()
            
            flash('Rota atualizada com sucesso!', 'success')
            return redirect(url_for('rotas.lista'))
        except Exception as e:
            flash(f'Erro ao atualizar rota: {str(e)}', 'danger')
            db.rollback()
    
    # GET - Carregar dados
    cursor.execute("SELECT * FROM rotas WHERE id = %s", (id,))
    rota = cursor.fetchone()
    
    if not rota:
        flash('Rota não encontrada!', 'danger')
        return redirect(url_for('rotas.lista'))
    
    cursor.execute("SELECT * FROM origens ORDER BY nome")
    origens = cursor.fetchall()
    
    cursor.execute("SELECT * FROM destinos ORDER BY nome")
    destinos = cursor.fetchall()
    
    cursor.close()
    
    return render_template('rotas/editar.html', rota=rota, origens=origens, destinos=destinos)

@bp.route('/excluir/<int:id>')
@login_required
def excluir(id):
    try:
        cursor = db.cursor()
        cursor.execute("DELETE FROM rotas WHERE id = %s", (id,))
        db.commit()
        cursor.close()
        flash('Rota excluída com sucesso!', 'success')
    except Exception as e:
        flash(f'Erro ao excluir rota: {str(e)}', 'danger')
        db.rollback()
    
    return redirect(url_for('rotas.lista'))
