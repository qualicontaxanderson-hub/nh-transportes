from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from utils.db import get_db_connection

bp = Blueprint('produtos', __name__, url_prefix='/produtos')

_tables_ready = False


def _ensure_tables():
    """Creates produto_empresas table and conta_contabil_id column if not present. Idempotent."""
    global _tables_ready
    if _tables_ready:
        return
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS produto_empresas (
                produto_id        INT NOT NULL,
                cliente_id        INT NOT NULL,
                conta_contabil_id INT NULL,
                PRIMARY KEY (produto_id, cliente_id),
                CONSTRAINT fk_pe_produto  FOREIGN KEY (produto_id)  REFERENCES produto(id)   ON DELETE CASCADE,
                CONSTRAINT fk_pe_cliente  FOREIGN KEY (cliente_id)  REFERENCES clientes(id)  ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        conn.commit()
        cursor.close()
        _tables_ready = True
    finally:
        conn.close()


def _load_form_data(conn):
    """Loads empresas with active products and contas_por_grupo mapping, same as fornecedores."""
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


def _load_grupos(conn):
    """Loads active plano_contas_grupos for the filter dropdown in lista."""
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
    _ensure_tables()
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    grupo_id = request.args.get('grupo_id', '').strip()
    cliente_id = request.args.get('cliente_id', '').strip()

    query = """
        SELECT DISTINCT p.*,
               pcc.codigo AS conta_codigo,
               pcc.nome   AS conta_nome,
               g.codigo   AS grupo_codigo,
               g.nome     AS grupo_nome,
               cl.id      AS empresa_id,
               COALESCE(cl.nome_fantasia, cl.razao_social) AS empresa_nome
        FROM produto p
        LEFT JOIN produto_empresas pe ON pe.produto_id = p.id
        LEFT JOIN clientes cl ON cl.id = pe.cliente_id
        LEFT JOIN plano_contas_contas pcc ON pcc.id = pe.conta_contabil_id
        LEFT JOIN plano_contas_grupos g ON g.id = pcc.grupo_id
    """
    params = []
    conditions = []
    if grupo_id:
        conditions.append("g.id = %s")
        params.append(int(grupo_id))
    if cliente_id:
        conditions.append("pe.cliente_id = %s")
        params.append(int(cliente_id))
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY p.nome"

    cursor.execute(query, params)
    produtos = cursor.fetchall()
    cursor.close()

    grupos = _load_grupos(conn)

    # Empresas for filter dropdown
    cursor2 = conn.cursor(dictionary=True)
    cursor2.execute(
        """SELECT DISTINCT c.id,
                  COALESCE(c.nome_fantasia, c.razao_social) AS nome
             FROM clientes c
             INNER JOIN cliente_produtos cp ON cp.cliente_id = c.id AND cp.ativo = 1
            ORDER BY nome"""
    )
    empresas = cursor2.fetchall()
    cursor2.close()

    conn.close()
    return render_template('produtos/lista.html', produtos=produtos,
                           grupos=grupos, grupo_id=grupo_id,
                           empresas=empresas, cliente_id=cliente_id)


@bp.route('/novo', methods=['GET', 'POST'])
@login_required
def novo():
    _ensure_tables()
    conn = None
    cursor = None

    if request.method == 'POST':
        nome = request.form.get('nome')
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("INSERT INTO produto (nome) VALUES (%s)", (nome,))
            conn.commit()
            novo_id = cursor.lastrowid

            empresa_ids = request.form.getlist('empresa_id[]')
            conta_ids = request.form.getlist('conta_contabil_id[]')
            for eid, cid in zip(empresa_ids, conta_ids):
                if eid:
                    conta_contabil_id = int(cid) if cid else None
                    cursor.execute(
                        """INSERT INTO produto_empresas
                               (produto_id, cliente_id, conta_contabil_id)
                           VALUES (%s, %s, %s)
                           ON DUPLICATE KEY UPDATE conta_contabil_id = VALUES(conta_contabil_id)""",
                        (novo_id, int(eid), conta_contabil_id)
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
    empresas, contas_por_grupo = _load_form_data(conn)
    conn.close()
    return render_template('produtos/novo.html', empresas=empresas,
                           contas_por_grupo=contas_por_grupo, vinculos=[])


@bp.route('/editar/<int:id>', methods=['GET', 'POST'])
@login_required
def editar(id):
    _ensure_tables()
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        if request.method == 'POST':
            nome = request.form.get('nome')
            cursor.execute("UPDATE produto SET nome=%s WHERE id=%s", (nome, id))
            conn.commit()

            cursor.execute("DELETE FROM produto_empresas WHERE produto_id = %s", (id,))
            empresa_ids = request.form.getlist('empresa_id[]')
            conta_ids = request.form.getlist('conta_contabil_id[]')
            for eid, cid in zip(empresa_ids, conta_ids):
                if eid:
                    conta_contabil_id = int(cid) if cid else None
                    cursor.execute(
                        """INSERT INTO produto_empresas
                               (produto_id, cliente_id, conta_contabil_id)
                           VALUES (%s, %s, %s)
                           ON DUPLICATE KEY UPDATE conta_contabil_id = VALUES(conta_contabil_id)""",
                        (id, int(eid), conta_contabil_id)
                    )
            conn.commit()
            flash('Produto atualizado com sucesso!', 'success')
            return redirect(url_for('produtos.lista'))

        cursor.execute("SELECT * FROM produto WHERE id = %s", (id,))
        produto = cursor.fetchone()
        if not produto:
            flash('Produto não encontrado!', 'danger')
            return redirect(url_for('produtos.lista'))

        cursor.execute(
            """SELECT pe.cliente_id, pe.conta_contabil_id, c.grupo_contabil_id
                 FROM produto_empresas pe
                 JOIN clientes c ON c.id = pe.cliente_id
                WHERE pe.produto_id = %s""",
            (id,)
        )
        vinculos = cursor.fetchall()

        empresas, contas_por_grupo = _load_form_data(conn)
        return render_template('produtos/editar.html', produto=produto,
                               empresas=empresas, contas_por_grupo=contas_por_grupo,
                               vinculos=vinculos)
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao editar produto: {str(e)}', 'danger')
        return redirect(url_for('produtos.lista'))
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


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
