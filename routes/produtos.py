from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from utils.db import get_db_connection

bp = Blueprint('produtos', __name__, url_prefix='/produtos')

_column_ready = False


def _ensure_column():
    """Adds conta_contabil_id column to produto table if not present. Idempotent."""
    global _column_ready
    if _column_ready:
        return
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'produto'
              AND COLUMN_NAME = 'conta_contabil_id'
        """)
        if cursor.fetchone()[0] == 0:
            cursor.execute(
                "ALTER TABLE produto ADD COLUMN conta_contabil_id INT NULL"
            )
        conn.commit()
        cursor.close()
        _column_ready = True
    finally:
        conn.close()


def _load_contas(conn):
    """Loads all active plano_contas_contas with their group info, for use in forms."""
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT c.id, c.grupo_id, c.codigo, c.nome AS conta_nome,
                   g.codigo AS grupo_codigo, g.nome AS grupo_nome
              FROM plano_contas_contas c
              JOIN plano_contas_grupos g ON g.id = c.grupo_id
             WHERE c.ativo = 1
             ORDER BY g.codigo, c.codigo
        """)
        return cursor.fetchall()
    except Exception:
        return []
    finally:
        cursor.close()


def _load_grupos(conn):
    """Loads active plano_contas_grupos for the filter dropdown."""
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT id, codigo, nome FROM plano_contas_grupos WHERE ativo = 1 ORDER BY codigo"
        )
        return cursor.fetchall()
    except Exception:
        return []
    finally:
        cursor.close()


@bp.route('/')
@login_required
def lista():
    _ensure_column()
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    grupo_id = request.args.get('grupo_id', '').strip()

    query = """
        SELECT p.*,
               c.codigo AS conta_codigo,
               c.nome   AS conta_nome,
               g.codigo AS grupo_codigo,
               g.nome   AS grupo_nome
        FROM produto p
        LEFT JOIN plano_contas_contas c ON c.id = p.conta_contabil_id
        LEFT JOIN plano_contas_grupos g ON g.id = c.grupo_id
    """
    params = []
    if grupo_id:
        query += " WHERE c.grupo_id = %s"
        params.append(int(grupo_id))
    query += " ORDER BY p.nome"

    cursor.execute(query, params)
    produtos = cursor.fetchall()
    cursor.close()

    grupos = _load_grupos(conn)
    conn.close()
    return render_template('produtos/lista.html', produtos=produtos,
                           grupos=grupos, grupo_id=grupo_id)


@bp.route('/novo', methods=['GET', 'POST'])
@login_required
def novo():
    _ensure_column()
    conn = None
    cursor = None

    if request.method == 'POST':
        nome = request.form.get('nome')
        conta_id_raw = request.form.get('conta_contabil_id')
        conta_contabil_id = int(conta_id_raw) if conta_id_raw else None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO produto (nome, conta_contabil_id) VALUES (%s, %s)",
                (nome, conta_contabil_id)
            )
            conn.commit()
            flash('Produto cadastrado com sucesso!', 'success')
            return redirect(url_for('produtos.lista'))
        except Exception as e:
            if conn:
                conn.rollback()
            flash(f'Erro ao cadastrar produto: {str(e)}', 'danger')
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    conn = get_db_connection()
    contas = _load_contas(conn)
    conn.close()
    return render_template('produtos/novo.html', contas=contas)


@bp.route('/editar/<int:id>', methods=['GET', 'POST'])
@login_required
def editar(id):
    _ensure_column()
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    if request.method == 'POST':
        nome = request.form.get('nome')
        conta_id_raw = request.form.get('conta_contabil_id')
        conta_contabil_id = int(conta_id_raw) if conta_id_raw else None
        try:
            cursor.execute(
                "UPDATE produto SET nome=%s, conta_contabil_id=%s WHERE id=%s",
                (nome, conta_contabil_id, id)
            )
            conn.commit()
            cursor.close()
            conn.close()
            flash('Produto atualizado com sucesso!', 'success')
            return redirect(url_for('produtos.lista'))
        except Exception as e:
            if conn:
                conn.rollback()
            flash(f'Erro ao atualizar produto: {str(e)}', 'danger')

    cursor.execute("SELECT * FROM produto WHERE id = %s", (id,))
    produto = cursor.fetchone()
    cursor.close()

    contas = _load_contas(conn)
    conn.close()

    if not produto:
        flash('Produto não encontrado!', 'danger')
        return redirect(url_for('produtos.lista'))

    return render_template('produtos/editar.html', produto=produto, contas=contas)


@bp.route('/excluir/<int:id>')
@login_required
def excluir(id):
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM produto WHERE id = %s", (id,))
        conn.commit()
        flash('Produto excluído com sucesso!', 'success')
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao excluir produto: {str(e)}', 'danger')
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
    return redirect(url_for('produtos.lista'))
