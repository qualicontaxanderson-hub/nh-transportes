from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from utils.db import get_db_connection
from utils.decorators import admin_required

bp = Blueprint('despesas', __name__, url_prefix='/despesas')

@bp.route('/')
@login_required
def index():
    """Lista todos os títulos de despesas"""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT t.*, 
               COUNT(DISTINCT c.id) as total_categorias
        FROM titulos_despesas t
        LEFT JOIN categorias_despesas c ON t.id = c.titulo_id AND c.ativo = 1
        WHERE t.ativo = 1
        GROUP BY t.id
        ORDER BY t.ordem, t.nome
    """)
    titulos = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('despesas/index.html', titulos=titulos)


@bp.route('/titulo/<int:titulo_id>')
@login_required
def titulo_detalhes(titulo_id):
    """Mostra categorias de um título específico"""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Buscar título
    cursor.execute("SELECT * FROM titulos_despesas WHERE id = %s", (titulo_id,))
    titulo = cursor.fetchone()
    
    if not titulo:
        flash('Título não encontrado!', 'error')
        return redirect(url_for('despesas.index'))
    
    # Buscar categorias do título
    cursor.execute("""
        SELECT c.*, 
               COUNT(DISTINCT s.id) as total_subcategorias
        FROM categorias_despesas c
        LEFT JOIN subcategorias_despesas s ON c.id = s.categoria_id AND s.ativo = 1
        WHERE c.titulo_id = %s AND c.ativo = 1
        GROUP BY c.id
        ORDER BY c.ordem, c.nome
    """, (titulo_id,))
    categorias = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('despesas/titulo_detalhes.html', titulo=titulo, categorias=categorias)


@bp.route('/categoria/<int:categoria_id>')
@login_required
def categoria_detalhes(categoria_id):
    """Mostra subcategorias de uma categoria específica"""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Buscar categoria e título
    cursor.execute("""
        SELECT c.*, t.nome as titulo_nome, t.id as titulo_id
        FROM categorias_despesas c
        LEFT JOIN titulos_despesas t ON c.titulo_id = t.id
        WHERE c.id = %s
    """, (categoria_id,))
    categoria = cursor.fetchone()
    
    if not categoria:
        flash('Categoria não encontrada!', 'error')
        return redirect(url_for('despesas.index'))
    
    # Buscar subcategorias da categoria
    cursor.execute("""
        SELECT * FROM subcategorias_despesas
        WHERE categoria_id = %s AND ativo = 1
        ORDER BY ordem, nome
    """, (categoria_id,))
    subcategorias = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('despesas/categoria_detalhes.html', 
                         categoria=categoria, 
                         subcategorias=subcategorias)


# Rotas de gerenciamento de títulos
@bp.route('/titulos/novo', methods=['GET', 'POST'])
@login_required
@admin_required
def novo_titulo():
    """Criar novo título de despesa"""
    if request.method == 'POST':
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO titulos_despesas (nome, descricao, ordem, ativo)
            VALUES (%s, %s, %s, %s)
        """, (
            request.form.get('nome'),
            request.form.get('descricao'),
            request.form.get('ordem', 0),
            1
        ))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        flash('Título criado com sucesso!', 'success')
        return redirect(url_for('despesas.index'))
    
    return render_template('despesas/titulo_form.html', titulo=None)


@bp.route('/titulos/editar/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar_titulo(id):
    """Editar título de despesa"""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    if request.method == 'POST':
        cursor.execute("""
            UPDATE titulos_despesas 
            SET nome = %s, descricao = %s, ordem = %s
            WHERE id = %s
        """, (
            request.form.get('nome'),
            request.form.get('descricao'),
            request.form.get('ordem', 0),
            id
        ))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        flash('Título atualizado com sucesso!', 'success')
        return redirect(url_for('despesas.index'))
    
    cursor.execute("SELECT * FROM titulos_despesas WHERE id = %s", (id,))
    titulo = cursor.fetchone()
    
    cursor.close()
    conn.close()
    
    return render_template('despesas/titulo_form.html', titulo=titulo)


# Rotas de gerenciamento de categorias
@bp.route('/categorias/nova', methods=['GET', 'POST'])
@login_required
@admin_required
def nova_categoria():
    """Criar nova categoria de despesa"""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    if request.method == 'POST':
        cursor.execute("""
            INSERT INTO categorias_despesas (titulo_id, nome, ordem, ativo)
            VALUES (%s, %s, %s, %s)
        """, (
            request.form.get('titulo_id'),
            request.form.get('nome'),
            request.form.get('ordem', 0),
            1
        ))
        
        conn.commit()
        titulo_id = request.form.get('titulo_id')
        cursor.close()
        conn.close()
        
        flash('Categoria criada com sucesso!', 'success')
        return redirect(url_for('despesas.titulo_detalhes', titulo_id=titulo_id))
    
    # Buscar títulos para o dropdown
    cursor.execute("SELECT * FROM titulos_despesas WHERE ativo = 1 ORDER BY ordem, nome")
    titulos = cursor.fetchall()
    
    titulo_id = request.args.get('titulo_id')
    cursor.close()
    conn.close()
    
    return render_template('despesas/categoria_form.html', 
                         categoria=None, 
                         titulos=titulos, 
                         titulo_id_pre=titulo_id)


@bp.route('/categorias/editar/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar_categoria(id):
    """Editar categoria de despesa"""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    if request.method == 'POST':
        cursor.execute("""
            UPDATE categorias_despesas 
            SET titulo_id = %s, nome = %s, ordem = %s
            WHERE id = %s
        """, (
            request.form.get('titulo_id'),
            request.form.get('nome'),
            request.form.get('ordem', 0),
            id
        ))
        
        conn.commit()
        
        cursor.execute("SELECT titulo_id FROM categorias_despesas WHERE id = %s", (id,))
        result = cursor.fetchone()
        titulo_id = result['titulo_id']
        
        cursor.close()
        conn.close()
        
        flash('Categoria atualizada com sucesso!', 'success')
        return redirect(url_for('despesas.titulo_detalhes', titulo_id=titulo_id))
    
    cursor.execute("SELECT * FROM categorias_despesas WHERE id = %s", (id,))
    categoria = cursor.fetchone()
    
    cursor.execute("SELECT * FROM titulos_despesas WHERE ativo = 1 ORDER BY ordem, nome")
    titulos = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('despesas/categoria_form.html', 
                         categoria=categoria, 
                         titulos=titulos,
                         titulo_id_pre=None)


# Rotas de gerenciamento de subcategorias
@bp.route('/subcategorias/nova', methods=['GET', 'POST'])
@login_required
@admin_required
def nova_subcategoria():
    """Criar nova subcategoria de despesa"""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    if request.method == 'POST':
        cursor.execute("""
            INSERT INTO subcategorias_despesas (categoria_id, nome, ordem, ativo)
            VALUES (%s, %s, %s, %s)
        """, (
            request.form.get('categoria_id'),
            request.form.get('nome'),
            request.form.get('ordem', 0),
            1
        ))
        
        conn.commit()
        categoria_id = request.form.get('categoria_id')
        cursor.close()
        conn.close()
        
        flash('Subcategoria criada com sucesso!', 'success')
        return redirect(url_for('despesas.categoria_detalhes', categoria_id=categoria_id))
    
    categoria_id = request.args.get('categoria_id')
    
    # Buscar categoria
    if categoria_id:
        cursor.execute("""
            SELECT c.*, t.nome as titulo_nome
            FROM categorias_despesas c
            LEFT JOIN titulos_despesas t ON c.titulo_id = t.id
            WHERE c.id = %s
        """, (categoria_id,))
        categoria = cursor.fetchone()
    else:
        categoria = None
    
    # Buscar todas categorias para dropdown
    cursor.execute("""
        SELECT c.id, c.nome, t.nome as titulo_nome
        FROM categorias_despesas c
        LEFT JOIN titulos_despesas t ON c.titulo_id = t.id
        WHERE c.ativo = 1
        ORDER BY t.ordem, c.ordem, c.nome
    """)
    categorias = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('despesas/subcategoria_form.html', 
                         subcategoria=None, 
                         categorias=categorias,
                         categoria_pre=categoria)


@bp.route('/subcategorias/editar/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar_subcategoria(id):
    """Editar subcategoria de despesa"""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    if request.method == 'POST':
        cursor.execute("""
            UPDATE subcategorias_despesas 
            SET categoria_id = %s, nome = %s, ordem = %s
            WHERE id = %s
        """, (
            request.form.get('categoria_id'),
            request.form.get('nome'),
            request.form.get('ordem', 0),
            id
        ))
        
        conn.commit()
        
        cursor.execute("SELECT categoria_id FROM subcategorias_despesas WHERE id = %s", (id,))
        result = cursor.fetchone()
        categoria_id = result['categoria_id']
        
        cursor.close()
        conn.close()
        
        flash('Subcategoria atualizada com sucesso!', 'success')
        return redirect(url_for('despesas.categoria_detalhes', categoria_id=categoria_id))
    
    cursor.execute("SELECT * FROM subcategorias_despesas WHERE id = %s", (id,))
    subcategoria = cursor.fetchone()
    
    # Buscar categoria da subcategoria
    cursor.execute("""
        SELECT c.*, t.nome as titulo_nome
        FROM categorias_despesas c
        LEFT JOIN titulos_despesas t ON c.titulo_id = t.id
        WHERE c.id = %s
    """, (subcategoria['categoria_id'],))
    categoria = cursor.fetchone()
    
    # Buscar todas categorias para dropdown
    cursor.execute("""
        SELECT c.id, c.nome, t.nome as titulo_nome
        FROM categorias_despesas c
        LEFT JOIN titulos_despesas t ON c.titulo_id = t.id
        WHERE c.ativo = 1
        ORDER BY t.ordem, c.ordem, c.nome
    """)
    categorias = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('despesas/subcategoria_form.html', 
                         subcategoria=subcategoria, 
                         categorias=categorias,
                         categoria_pre=categoria)


# Rotas de exclusão (soft delete)
@bp.route('/titulos/excluir/<int:id>', methods=['POST'])
@login_required
@admin_required
def excluir_titulo(id):
    """Desativar título de despesa"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("UPDATE titulos_despesas SET ativo = 0 WHERE id = %s", (id,))
    conn.commit()
    
    cursor.close()
    conn.close()
    
    flash('Título desativado com sucesso!', 'success')
    return redirect(url_for('despesas.index'))


@bp.route('/categorias/excluir/<int:id>', methods=['POST'])
@login_required
@admin_required
def excluir_categoria(id):
    """Desativar categoria de despesa"""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Buscar titulo_id antes de excluir
    cursor.execute("SELECT titulo_id FROM categorias_despesas WHERE id = %s", (id,))
    result = cursor.fetchone()
    titulo_id = result['titulo_id'] if result else None
    
    cursor.execute("UPDATE categorias_despesas SET ativo = 0 WHERE id = %s", (id,))
    conn.commit()
    
    cursor.close()
    conn.close()
    
    flash('Categoria desativada com sucesso!', 'success')
    
    if titulo_id:
        return redirect(url_for('despesas.titulo_detalhes', titulo_id=titulo_id))
    return redirect(url_for('despesas.index'))


@bp.route('/subcategorias/excluir/<int:id>', methods=['POST'])
@login_required
@admin_required
def excluir_subcategoria(id):
    """Desativar subcategoria de despesa"""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Buscar categoria_id antes de excluir
    cursor.execute("SELECT categoria_id FROM subcategorias_despesas WHERE id = %s", (id,))
    result = cursor.fetchone()
    categoria_id = result['categoria_id'] if result else None
    
    cursor.execute("UPDATE subcategorias_despesas SET ativo = 0 WHERE id = %s", (id,))
    conn.commit()
    
    cursor.close()
    conn.close()
    
    flash('Subcategoria desativada com sucesso!', 'success')
    
    if categoria_id:
        return redirect(url_for('despesas.categoria_detalhes', categoria_id=categoria_id))
    return redirect(url_for('despesas.index'))
