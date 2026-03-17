import logging

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from utils.db import get_db_connection
from utils.decorators import admin_required

bp = Blueprint('despesas', __name__, url_prefix='/despesas')

_tables_ready = False


def _ensure_tables():
    """Garante que a tabela categoria_despesa_contas existe. Idempotente."""
    global _tables_ready
    if _tables_ready:
        return
    log = logging.getLogger(__name__)
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS categoria_despesa_contas (
                id                INT          AUTO_INCREMENT PRIMARY KEY,
                categoria_id      INT          NOT NULL,
                cliente_id        INT          NOT NULL,
                conta_contabil_id INT          NULL,
                UNIQUE KEY uq_cdc_cat_cliente (categoria_id, cliente_id),
                CONSTRAINT fk_cdc_categoria FOREIGN KEY (categoria_id)
                    REFERENCES categorias_despesas(id) ON DELETE CASCADE,
                CONSTRAINT fk_cdc_cliente FOREIGN KEY (cliente_id)
                    REFERENCES clientes(id) ON DELETE CASCADE,
                CONSTRAINT fk_cdc_conta FOREIGN KEY (conta_contabil_id)
                    REFERENCES plano_contas_contas(id) ON DELETE SET NULL
            ) COMMENT='Vínculo por empresa entre categorias de despesas e contas contábeis'
        """)
        conn.commit()
        _tables_ready = True
    except Exception:
        log.exception('_ensure_tables despesas: falha ao inicializar tabelas')
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        cursor.close()
        conn.close()


def _load_form_data(conn):
    """Carrega empresas e o mapeamento grupo→contas contábeis para o formulário de categoria."""
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """SELECT DISTINCT c.id,
                  COALESCE(c.nome_fantasia, c.razao_social) AS nome,
                  c.grupo_contabil_id
             FROM clientes c
             INNER JOIN cliente_produtos cp ON cp.cliente_id = c.id AND cp.ativo = 1
            ORDER BY nome"""
    )
    empresas = cursor.fetchall()
    cursor.execute(
        """SELECT c.id, c.grupo_id, c.codigo, c.nome AS conta_nome
             FROM plano_contas_contas c
             JOIN plano_contas_grupos g ON g.id = c.grupo_id
            WHERE c.ativo = 1
            ORDER BY g.codigo, c.codigo"""
    )
    contas_raw = cursor.fetchall()
    cursor.close()
    contas_por_grupo = {}
    for c in contas_raw:
        gid = c['grupo_id']
        if gid not in contas_por_grupo:
            contas_por_grupo[gid] = []
        contas_por_grupo[gid].append({
            'id': c['id'],
            'label': f"{c['codigo']} {c['conta_nome']}",
        })
    return empresas, contas_por_grupo


@bp.route('/')
@login_required
@admin_required
def index():
    """Lista todos os títulos de despesas"""
    _ensure_tables()
    cliente_id = request.args.get('cliente_id', '').strip()
    try:
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

        # Companies with active products for the filter dropdown
        cursor.execute(
            """SELECT DISTINCT c.id,
                      COALESCE(c.nome_fantasia, c.razao_social) AS nome
                 FROM clientes c
                 INNER JOIN cliente_produtos cp ON cp.cliente_id = c.id AND cp.ativo = 1
                ORDER BY nome"""
        )
        empresas = cursor.fetchall()

        # Report: categories + contas contábeis for the selected company
        relatorio = []
        empresa_selecionada = None
        if cliente_id:
            cursor.execute(
                """SELECT t.nome AS titulo_nome,
                          cat.nome AS categoria_nome,
                          pcc.codigo AS conta_codigo,
                          pcc.nome AS conta_nome
                     FROM categorias_despesas cat
                     JOIN titulos_despesas t ON t.id = cat.titulo_id AND t.ativo = 1
                     LEFT JOIN categoria_despesa_contas cdc
                            ON cdc.categoria_id = cat.id AND cdc.cliente_id = %s
                     LEFT JOIN plano_contas_contas pcc ON pcc.id = cdc.conta_contabil_id
                    WHERE cat.ativo = 1
                    ORDER BY t.ordem, t.nome, cat.nome""",
                (int(cliente_id),)
            )
            relatorio = cursor.fetchall()
            for emp in empresas:
                if str(emp['id']) == cliente_id:
                    empresa_selecionada = emp
                    break

        cursor.close()
        conn.close()
        return render_template('despesas/index.html',
                               titulos=titulos,
                               empresas=empresas,
                               relatorio=relatorio,
                               cliente_id=cliente_id,
                               empresa_selecionada=empresa_selecionada)
    except Exception as e:
        import logging
        logging.getLogger(__name__).exception('index despesas error')
        flash(f'Erro ao carregar despesas: {str(e)}', 'danger')
        return render_template('despesas/index.html',
                               titulos=[],
                               empresas=[],
                               relatorio=[],
                               cliente_id='',
                               empresa_selecionada=None)


@bp.route('/titulo/<int:titulo_id>')
@login_required
@admin_required
def titulo_detalhes(titulo_id):
    """Mostra categorias de um título específico"""
    _ensure_tables()
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM titulos_despesas WHERE id = %s", (titulo_id,))
    titulo = cursor.fetchone()

    if not titulo:
        flash('Título não encontrado!', 'error')
        cursor.close()
        conn.close()
        return redirect(url_for('despesas.index'))

    empresa_id = current_user.cliente_id if hasattr(current_user, 'cliente_id') else None
    cursor.execute("""
        SELECT c.*,
               COUNT(DISTINCT s.id) as total_subcategorias,
               pcc.codigo as conta_codigo,
               pcc.nome   as conta_nome
        FROM categorias_despesas c
        LEFT JOIN subcategorias_despesas s ON c.id = s.categoria_id AND s.ativo = 1
        LEFT JOIN categoria_despesa_contas cdc
               ON cdc.categoria_id = c.id AND cdc.cliente_id = %s
        LEFT JOIN plano_contas_contas pcc ON pcc.id = cdc.conta_contabil_id
        WHERE c.titulo_id = %s AND c.ativo = 1
        GROUP BY c.id
        ORDER BY c.nome
    """, (empresa_id, titulo_id,))
    categorias = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template('despesas/titulo_detalhes.html', titulo=titulo, categorias=categorias)


@bp.route('/categoria/<int:categoria_id>')
@login_required
@admin_required
def categoria_detalhes(categoria_id):
    """Mostra subcategorias de uma categoria específica"""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT c.*, t.nome as titulo_nome, t.id as titulo_id
        FROM categorias_despesas c
        LEFT JOIN titulos_despesas t ON c.titulo_id = t.id
        WHERE c.id = %s
    """, (categoria_id,))
    categoria = cursor.fetchone()

    if not categoria:
        flash('Categoria não encontrada!', 'error')
        cursor.close()
        conn.close()
        return redirect(url_for('despesas.index'))

    cursor.execute("""
        SELECT * FROM subcategorias_despesas
        WHERE categoria_id = %s AND ativo = 1
        ORDER BY nome
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
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        if request.method == 'POST':
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
            flash('Título criado com sucesso!', 'success')
            return redirect(url_for('despesas.index'))

        return render_template('despesas/titulo_form.html', titulo=None)
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao salvar título: {str(e)}', 'danger')
        return redirect(url_for('despesas.index'))
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@bp.route('/titulos/editar/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar_titulo(id):
    """Editar título de despesa"""
    conn = None
    cursor = None
    try:
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
            flash('Título atualizado com sucesso!', 'success')
            return redirect(url_for('despesas.index'))

        cursor.execute("SELECT * FROM titulos_despesas WHERE id = %s", (id,))
        titulo = cursor.fetchone()
        return render_template('despesas/titulo_form.html', titulo=titulo)
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao editar título: {str(e)}', 'danger')
        return redirect(url_for('despesas.index'))
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


# Rotas de gerenciamento de categorias
@bp.route('/categorias/nova', methods=['GET', 'POST'])
@login_required
@admin_required
def nova_categoria():
    """Criar nova categoria de despesa"""
    _ensure_tables()
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        if request.method == 'POST':
            titulo_id = request.form.get('titulo_id')
            cursor.execute("""
                INSERT INTO categorias_despesas (titulo_id, nome, ordem, ativo)
                VALUES (%s, %s, %s, %s)
            """, (
                titulo_id,
                request.form.get('nome'),
                request.form.get('ordem', 0),
                1
            ))
            conn.commit()
            nova_id = cursor.lastrowid

            # Salvar vínculos empresa + conta contábil
            empresa_ids = request.form.getlist('empresa_id[]')
            conta_ids = request.form.getlist('conta_contabil_id[]')
            for eid, cid in zip(empresa_ids, conta_ids):
                if eid:
                    conta_id = int(cid) if cid else None
                    cursor.execute(
                        """INSERT INTO categoria_despesa_contas
                               (categoria_id, cliente_id, conta_contabil_id)
                           VALUES (%s, %s, %s)
                           ON DUPLICATE KEY UPDATE conta_contabil_id = VALUES(conta_contabil_id)""",
                        (nova_id, int(eid), conta_id)
                    )
            conn.commit()

            flash('Categoria criada com sucesso!', 'success')
            return redirect(url_for('despesas.titulo_detalhes', titulo_id=titulo_id))

        # Buscar títulos para o dropdown
        cursor.execute("SELECT * FROM titulos_despesas WHERE ativo = 1 ORDER BY ordem, nome")
        titulos = cursor.fetchall()

        empresas, contas_por_grupo = _load_form_data(conn)

        titulo_id = request.args.get('titulo_id')
        return render_template('despesas/categoria_form.html',
                             categoria=None,
                             titulos=titulos,
                             empresas=empresas,
                             contas_por_grupo=contas_por_grupo,
                             vinculos=[],
                             titulo_id_pre=titulo_id)
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao salvar categoria: {str(e)}', 'danger')
        return redirect(url_for('despesas.index'))
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@bp.route('/categorias/editar/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar_categoria(id):
    """Editar categoria de despesa"""
    _ensure_tables()
    conn = None
    cursor = None
    try:
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

            # Atualizar vínculos empresa + conta contábil
            cursor.execute("DELETE FROM categoria_despesa_contas WHERE categoria_id = %s", (id,))
            empresa_ids = request.form.getlist('empresa_id[]')
            conta_ids = request.form.getlist('conta_contabil_id[]')
            for eid, cid in zip(empresa_ids, conta_ids):
                if eid:
                    conta_id = int(cid) if cid else None
                    cursor.execute(
                        """INSERT INTO categoria_despesa_contas
                               (categoria_id, cliente_id, conta_contabil_id)
                           VALUES (%s, %s, %s)
                           ON DUPLICATE KEY UPDATE conta_contabil_id = VALUES(conta_contabil_id)""",
                        (id, int(eid), conta_id)
                    )
            conn.commit()

            cursor.execute("SELECT titulo_id FROM categorias_despesas WHERE id = %s", (id,))
            result = cursor.fetchone()
            titulo_id = result['titulo_id']

            flash('Categoria atualizada com sucesso!', 'success')
            return redirect(url_for('despesas.titulo_detalhes', titulo_id=titulo_id))

        cursor.execute("SELECT * FROM categorias_despesas WHERE id = %s", (id,))
        categoria = cursor.fetchone()

        cursor.execute("SELECT * FROM titulos_despesas WHERE ativo = 1 ORDER BY ordem, nome")
        titulos = cursor.fetchall()

        cursor.execute(
            """SELECT cdc.cliente_id, cdc.conta_contabil_id, c.grupo_contabil_id
                 FROM categoria_despesa_contas cdc
                 JOIN clientes c ON c.id = cdc.cliente_id
                WHERE cdc.categoria_id = %s""",
            (id,)
        )
        vinculos = cursor.fetchall()

        empresas, contas_por_grupo = _load_form_data(conn)

        return render_template('despesas/categoria_form.html',
                             categoria=categoria,
                             titulos=titulos,
                             empresas=empresas,
                             contas_por_grupo=contas_por_grupo,
                             vinculos=vinculos,
                             titulo_id_pre=None)
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao editar categoria: {str(e)}', 'danger')
        return redirect(url_for('despesas.index'))
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


# Rotas de gerenciamento de subcategorias
@bp.route('/subcategorias/nova', methods=['GET', 'POST'])
@login_required
@admin_required
def nova_subcategoria():
    """Criar nova subcategoria de despesa"""
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        if request.method == 'POST':
            categoria_id = request.form.get('categoria_id')
            cursor.execute("""
                INSERT INTO subcategorias_despesas (categoria_id, nome, ordem, ativo)
                VALUES (%s, %s, %s, %s)
            """, (
                categoria_id,
                request.form.get('nome'),
                request.form.get('ordem', 0),
                1
            ))

            conn.commit()
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

        return render_template('despesas/subcategoria_form.html',
                             subcategoria=None,
                             categorias=categorias,
                             categoria_pre=categoria)
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao salvar subcategoria: {str(e)}', 'danger')
        return redirect(url_for('despesas.index'))
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@bp.route('/subcategorias/editar/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar_subcategoria(id):
    """Editar subcategoria de despesa"""
    conn = None
    cursor = None
    try:
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

        return render_template('despesas/subcategoria_form.html',
                             subcategoria=subcategoria,
                             categorias=categorias,
                             categoria_pre=categoria)
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao editar subcategoria: {str(e)}', 'danger')
        return redirect(url_for('despesas.index'))
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


# Rotas de exclusão (soft delete)
@bp.route('/titulos/excluir/<int:id>', methods=['POST'])
@login_required
@admin_required
def excluir_titulo(id):
    """Desativar título de despesa"""
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("UPDATE titulos_despesas SET ativo = 0 WHERE id = %s", (id,))
        conn.commit()

        flash('Título desativado com sucesso!', 'success')
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao desativar título: {str(e)}', 'danger')
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

    return redirect(url_for('despesas.index'))


@bp.route('/categorias/excluir/<int:id>', methods=['POST'])
@login_required
@admin_required
def excluir_categoria(id):
    """Desativar categoria de despesa"""
    conn = None
    cursor = None
    titulo_id = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Buscar titulo_id antes de excluir
        cursor.execute("SELECT titulo_id FROM categorias_despesas WHERE id = %s", (id,))
        result = cursor.fetchone()
        titulo_id = result['titulo_id'] if result else None

        cursor.execute("UPDATE categorias_despesas SET ativo = 0 WHERE id = %s", (id,))
        conn.commit()

        flash('Categoria desativada com sucesso!', 'success')
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao desativar categoria: {str(e)}', 'danger')
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

    if titulo_id:
        return redirect(url_for('despesas.titulo_detalhes', titulo_id=titulo_id))
    return redirect(url_for('despesas.index'))


@bp.route('/subcategorias/excluir/<int:id>', methods=['POST'])
@login_required
@admin_required
def excluir_subcategoria(id):
    """Desativar subcategoria de despesa"""
    conn = None
    cursor = None
    categoria_id = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Buscar categoria_id antes de excluir
        cursor.execute("SELECT categoria_id FROM subcategorias_despesas WHERE id = %s", (id,))
        result = cursor.fetchone()
        categoria_id = result['categoria_id'] if result else None

        cursor.execute("UPDATE subcategorias_despesas SET ativo = 0 WHERE id = %s", (id,))
        conn.commit()

        flash('Subcategoria desativada com sucesso!', 'success')
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao desativar subcategoria: {str(e)}', 'danger')
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

    if categoria_id:
        return redirect(url_for('despesas.categoria_detalhes', categoria_id=categoria_id))
    return redirect(url_for('despesas.index'))
