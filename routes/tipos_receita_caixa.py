from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from database import get_db_connection
import traceback

# Create blueprint
bp = Blueprint('tipos_receita_caixa', __name__, url_prefix='/tipos_receita_caixa')
tipos_receita_caixa_bp = bp  # Alias for compatibility

@bp.route('/')
def lista():
    """Lista todos os tipos de receita de caixa"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        cursor.execute("""
            SELECT id, nome, tipo, ativo, criado_em
            FROM tipos_receita_caixa
            ORDER BY nome
        """)
        
        tipos_receita = cursor.fetchall()
        cursor.close()
        conn.close()
        
        return render_template('tipos_receita_caixa/lista.html', tipos_receita=tipos_receita)
        
    except Exception as e:
        error_msg = f"Erro ao carregar tipos de receita: {str(e)}"
        print(f"Error in tipos_receita_caixa lista: {traceback.format_exc()}")
        flash(error_msg, 'danger')
        return render_template('tipos_receita_caixa/lista.html', tipos_receita=[], error=error_msg)


@bp.route('/novo', methods=['GET', 'POST'])
def novo():
    """Cria um novo tipo de receita de caixa"""
    if request.method == 'POST':
        try:
            nome = request.form.get('nome', '').strip().upper()  # Força MAIÚSCULAS
            tipo = request.form.get('tipo', '').strip()
            ativo = 1 if request.form.get('ativo') == '1' else 0
            
            if not nome:
                flash('Nome é obrigatório', 'danger')
                return redirect(url_for('tipos_receita_caixa.novo'))
            
            conn = get_db_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO tipos_receita_caixa (nome, tipo, ativo)
                VALUES (%s, %s, %s)
            """, (nome, tipo if tipo else None, ativo))
            
            conn.commit()
            cursor.close()
            conn.close()
            
            flash(f'Tipo de receita "{nome}" criado com sucesso!', 'success')
            return redirect(url_for('tipos_receita_caixa.lista'))
            
        except Exception as e:
            error_msg = f"Erro ao criar tipo de receita: {str(e)}"
            print(f"Error in tipos_receita_caixa novo: {traceback.format_exc()}")
            flash(error_msg, 'danger')
            return redirect(url_for('tipos_receita_caixa.novo'))
    
    # GET request
    return render_template('tipos_receita_caixa/novo.html')


@bp.route('/editar/<int:id>', methods=['GET', 'POST'])
def editar(id):
    """Edita um tipo de receita de caixa existente"""
    if request.method == 'POST':
        try:
            nome = request.form.get('nome', '').strip().upper()  # Força MAIÚSCULAS
            tipo = request.form.get('tipo', '').strip()
            ativo = 1 if request.form.get('ativo') == '1' else 0
            
            if not nome:
                flash('Nome é obrigatório', 'danger')
                return redirect(url_for('tipos_receita_caixa.editar', id=id))
            
            conn = get_db_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                UPDATE tipos_receita_caixa
                SET nome = %s, tipo = %s, ativo = %s
                WHERE id = %s
            """, (nome, tipo if tipo else None, ativo, id))
            
            conn.commit()
            cursor.close()
            conn.close()
            
            flash(f'Tipo de receita "{nome}" atualizado com sucesso!', 'success')
            return redirect(url_for('tipos_receita_caixa.lista'))
            
        except Exception as e:
            error_msg = f"Erro ao atualizar tipo de receita: {str(e)}"
            print(f"Error in tipos_receita_caixa editar: {traceback.format_exc()}")
            flash(error_msg, 'danger')
            return redirect(url_for('tipos_receita_caixa.editar', id=id))
    
    # GET request
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        cursor.execute("""
            SELECT id, nome, tipo, ativo
            FROM tipos_receita_caixa
            WHERE id = %s
        """, (id,))
        
        tipo_receita = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if not tipo_receita:
            flash('Tipo de receita não encontrado', 'danger')
            return redirect(url_for('tipos_receita_caixa.lista'))
        
        return render_template('tipos_receita_caixa/editar.html', tipo_receita=tipo_receita)
        
    except Exception as e:
        error_msg = f"Erro ao carregar tipo de receita: {str(e)}"
        print(f"Error in tipos_receita_caixa editar GET: {traceback.format_exc()}")
        flash(error_msg, 'danger')
        return redirect(url_for('tipos_receita_caixa.lista'))


@bp.route('/toggle/<int:id>', methods=['POST'])
def toggle(id):
    """Ativa/desativa um tipo de receita de caixa"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Get current status
        cursor.execute("SELECT ativo, nome FROM tipos_receita_caixa WHERE id = %s", (id,))
        tipo_receita = cursor.fetchone()
        
        if not tipo_receita:
            return jsonify({'success': False, 'message': 'Tipo de receita não encontrado'}), 404
        
        # Toggle status
        novo_status = 0 if tipo_receita['ativo'] == 1 else 1
        cursor.execute("UPDATE tipos_receita_caixa SET ativo = %s WHERE id = %s", (novo_status, id))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        status_texto = 'ativado' if novo_status == 1 else 'desativado'
        return jsonify({
            'success': True,
            'message': f'Tipo de receita "{tipo_receita["nome"]}" {status_texto} com sucesso!',
            'novo_status': novo_status
        })
        
    except Exception as e:
        error_msg = f"Erro ao alterar status: {str(e)}"
        print(f"Error in tipos_receita_caixa toggle: {traceback.format_exc()}")
        return jsonify({'success': False, 'message': error_msg}), 500
