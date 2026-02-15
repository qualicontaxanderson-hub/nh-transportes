from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from utils.db import get_db_connection
from utils.decorators import admin_required

bp = Blueprint('despesas_fornecedores', __name__, url_prefix='/despesas/fornecedores')


@bp.route('/')
@login_required
@admin_required
def lista():
    """Lista todos os fornecedores de despesas"""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Buscar todos os fornecedores com suas categorias e títulos
    cursor.execute("""
        SELECT 
            df.*,
            c.nome as categoria_nome,
            t.nome as titulo_nome
        FROM despesas_fornecedores df
        INNER JOIN categorias_despesas c ON df.categoria_id = c.id
        INNER JOIN titulos_despesas t ON c.titulo_id = t.id
        WHERE df.ativo = 1
        ORDER BY t.nome, c.nome, df.nome
    """)
    fornecedores = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('despesas_fornecedores/lista.html', fornecedores=fornecedores)


@bp.route('/novo', methods=['GET', 'POST'])
@login_required
@admin_required
def novo():
    """Criar novo fornecedor de despesa"""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    if request.method == 'POST':
        nome = request.form.get('nome', '').strip()
        categoria_id = request.form.get('categoria_id')
        
        # Validação
        if not nome:
            flash('Nome do fornecedor é obrigatório!', 'error')
        elif not categoria_id:
            flash('Categoria é obrigatória!', 'error')
        else:
            try:
                # Verificar se já existe
                cursor.execute("""
                    SELECT id FROM despesas_fornecedores 
                    WHERE nome = %s AND categoria_id = %s AND ativo = 1
                """, (nome, categoria_id))
                
                if cursor.fetchone():
                    flash('Fornecedor já existe nesta categoria!', 'warning')
                else:
                    # Inserir
                    cursor.execute("""
                        INSERT INTO despesas_fornecedores (nome, categoria_id, ativo)
                        VALUES (%s, %s, 1)
                    """, (nome, categoria_id))
                    conn.commit()
                    
                    flash(f'Fornecedor "{nome}" cadastrado com sucesso!', 'success')
                    
                    cursor.close()
                    conn.close()
                    return redirect(url_for('despesas_fornecedores.lista'))
                    
            except Exception as e:
                conn.rollback()
                flash(f'Erro ao cadastrar fornecedor: {str(e)}', 'error')
    
    # Buscar todas as categorias para o select
    cursor.execute("""
        SELECT 
            c.id,
            c.nome as categoria_nome,
            t.nome as titulo_nome,
            t.id as titulo_id
        FROM categorias_despesas c
        INNER JOIN titulos_despesas t ON c.titulo_id = t.id
        WHERE c.ativo = 1 AND t.ativo = 1
        ORDER BY t.ordem, t.nome, c.nome
    """)
    categorias = cursor.fetchall()
    
    # Agrupar por título
    titulos_dict = {}
    for cat in categorias:
        titulo_id = cat['titulo_id']
        if titulo_id not in titulos_dict:
            titulos_dict[titulo_id] = {
                'nome': cat['titulo_nome'],
                'categorias': []
            }
        titulos_dict[titulo_id]['categorias'].append(cat)
    
    cursor.close()
    conn.close()
    
    return render_template('despesas_fornecedores/novo.html', titulos_dict=titulos_dict)


@bp.route('/editar/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar(id):
    """Editar fornecedor de despesa"""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Buscar fornecedor
    cursor.execute("""
        SELECT df.*, c.nome as categoria_nome, t.nome as titulo_nome
        FROM despesas_fornecedores df
        INNER JOIN categorias_despesas c ON df.categoria_id = c.id
        INNER JOIN titulos_despesas t ON c.titulo_id = t.id
        WHERE df.id = %s
    """, (id,))
    fornecedor = cursor.fetchone()
    
    if not fornecedor:
        flash('Fornecedor não encontrado!', 'error')
        cursor.close()
        conn.close()
        return redirect(url_for('despesas_fornecedores.lista'))
    
    if request.method == 'POST':
        nome = request.form.get('nome', '').strip()
        categoria_id = request.form.get('categoria_id')
        
        # Validação
        if not nome:
            flash('Nome do fornecedor é obrigatório!', 'error')
        elif not categoria_id:
            flash('Categoria é obrigatória!', 'error')
        else:
            try:
                # Verificar se já existe outro com mesmo nome na mesma categoria
                cursor.execute("""
                    SELECT id FROM despesas_fornecedores 
                    WHERE nome = %s AND categoria_id = %s AND ativo = 1 AND id != %s
                """, (nome, categoria_id, id))
                
                if cursor.fetchone():
                    flash('Já existe outro fornecedor com este nome nesta categoria!', 'warning')
                else:
                    # Atualizar
                    cursor.execute("""
                        UPDATE despesas_fornecedores 
                        SET nome = %s, categoria_id = %s
                        WHERE id = %s
                    """, (nome, categoria_id, id))
                    conn.commit()
                    
                    flash(f'Fornecedor "{nome}" atualizado com sucesso!', 'success')
                    
                    cursor.close()
                    conn.close()
                    return redirect(url_for('despesas_fornecedores.lista'))
                    
            except Exception as e:
                conn.rollback()
                flash(f'Erro ao atualizar fornecedor: {str(e)}', 'error')
    
    # Buscar todas as categorias para o select
    cursor.execute("""
        SELECT 
            c.id,
            c.nome as categoria_nome,
            t.nome as titulo_nome,
            t.id as titulo_id
        FROM categorias_despesas c
        INNER JOIN titulos_despesas t ON c.titulo_id = t.id
        WHERE c.ativo = 1 AND t.ativo = 1
        ORDER BY t.ordem, t.nome, c.nome
    """)
    categorias = cursor.fetchall()
    
    # Agrupar por título
    titulos_dict = {}
    for cat in categorias:
        titulo_id = cat['titulo_id']
        if titulo_id not in titulos_dict:
            titulos_dict[titulo_id] = {
                'nome': cat['titulo_nome'],
                'categorias': []
            }
        titulos_dict[titulo_id]['categorias'].append(cat)
    
    cursor.close()
    conn.close()
    
    return render_template('despesas_fornecedores/editar.html', 
                         fornecedor=fornecedor, 
                         titulos_dict=titulos_dict)


@bp.route('/excluir/<int:id>', methods=['POST'])
@login_required
@admin_required
def excluir(id):
    """Desativar fornecedor (soft delete)"""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    try:
        # Buscar nome do fornecedor
        cursor.execute("SELECT nome FROM despesas_fornecedores WHERE id = %s", (id,))
        fornecedor = cursor.fetchone()
        
        if not fornecedor:
            flash('Fornecedor não encontrado!', 'error')
        else:
            # Desativar
            cursor.execute("UPDATE despesas_fornecedores SET ativo = 0 WHERE id = %s", (id,))
            conn.commit()
            flash(f'Fornecedor "{fornecedor["nome"]}" desativado com sucesso!', 'success')
            
    except Exception as e:
        conn.rollback()
        flash(f'Erro ao desativar fornecedor: {str(e)}', 'error')
    
    cursor.close()
    conn.close()
    
    return redirect(url_for('despesas_fornecedores.lista'))


# ===== API ENDPOINTS =====

@bp.route('/api/por-categoria/<int:categoria_id>')
@login_required
@admin_required
def api_por_categoria(categoria_id):
    """API: Retorna fornecedores de uma categoria específica"""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT id, nome
        FROM despesas_fornecedores
        WHERE categoria_id = %s AND ativo = 1
        ORDER BY nome
    """, (categoria_id,))
    
    fornecedores = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return jsonify(fornecedores)


@bp.route('/api/criar-rapido', methods=['POST'])
@login_required
@admin_required
def api_criar_rapido():
    """API: Criar fornecedor rapidamente (para modal inline)"""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    try:
        data = request.get_json()
        nome = data.get('nome', '').strip()
        categoria_id = data.get('categoria_id')
        
        if not nome or not categoria_id:
            return jsonify({'success': False, 'message': 'Nome e categoria são obrigatórios'}), 400
        
        # Verificar se já existe
        cursor.execute("""
            SELECT id FROM despesas_fornecedores 
            WHERE nome = %s AND categoria_id = %s AND ativo = 1
        """, (nome, categoria_id))
        
        existing = cursor.fetchone()
        if existing:
            return jsonify({
                'success': True, 
                'id': existing['id'],
                'nome': nome,
                'message': 'Fornecedor já existe'
            })
        
        # Inserir
        cursor.execute("""
            INSERT INTO despesas_fornecedores (nome, categoria_id, ativo)
            VALUES (%s, %s, 1)
        """, (nome, categoria_id))
        conn.commit()
        
        new_id = cursor.lastrowid
        
        cursor.close()
        conn.close()
        
        return jsonify({
            'success': True,
            'id': new_id,
            'nome': nome,
            'message': 'Fornecedor criado com sucesso'
        })
        
    except Exception as e:
        conn.rollback()
        cursor.close()
        conn.close()
        return jsonify({'success': False, 'message': str(e)}), 500
