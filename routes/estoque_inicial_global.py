from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from routes.auth import admin_required
from utils.db import get_db_connection

bp = Blueprint('estoque_inicial_global', __name__, url_prefix='/estoque-inicial')


@bp.route('/', methods=['GET'])
@login_required
@admin_required
def list_entries():
    """Lista os registros de estoque inicial global, com filtro opcional por cliente."""
    cliente_id = request.args.get('cliente_id', type=int)

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT id, razao_social, nome_fantasia FROM clientes ORDER BY razao_social"
        )
        clientes = cur.fetchall()

        where = "WHERE 1=1"
        args = []
        if cliente_id:
            where += " AND eig.cliente_id = %s"
            args.append(cliente_id)

        cur.execute(f"""
            SELECT eig.id, eig.cliente_id, eig.produto_id, eig.data_inicio,
                   eig.quantidade_inicial, eig.created_at,
                   c.razao_social AS cliente_nome, c.nome_fantasia,
                   p.nome AS produto_nome
            FROM estoque_inicial_global eig
            INNER JOIN clientes c ON c.id = eig.cliente_id
            INNER JOIN produto p ON p.id = eig.produto_id
            {where}
            ORDER BY eig.data_inicio DESC, c.razao_social, p.nome
        """, args)
        entradas = cur.fetchall()
    finally:
        cur.close()
        conn.close()

    return render_template(
        'estoque_inicial_global/index.html',
        entradas=entradas,
        clientes=clientes,
        cliente_id=cliente_id,
    )


@bp.route('/novo', methods=['GET', 'POST'])
@login_required
@admin_required
def create_entry():
    """Cria um novo registro de estoque inicial (imutável após gravação)."""
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT id, razao_social, nome_fantasia FROM clientes ORDER BY razao_social"
        )
        clientes = cur.fetchall()
        cur.execute("SELECT id, nome FROM produto ORDER BY nome")
        produtos = cur.fetchall()
    finally:
        cur.close()
        conn.close()

    if request.method == 'POST':
        cliente_id = request.form.get('cliente_id', type=int)
        produto_id = request.form.get('produto_id', type=int)
        data_inicio = request.form.get('data_inicio', '').strip()
        quantidade_str = request.form.get('quantidade_inicial', '0').strip().replace(',', '.')

        if not cliente_id or not produto_id or not data_inicio:
            flash('Preencha todos os campos obrigatórios.', 'danger')
            return render_template(
                'estoque_inicial_global/novo.html',
                clientes=clientes, produtos=produtos,
            )

        try:
            quantidade = float(quantidade_str)
        except ValueError:
            flash('Quantidade inválida.', 'danger')
            return render_template(
                'estoque_inicial_global/novo.html',
                clientes=clientes, produtos=produtos,
            )

        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute(
                """INSERT INTO estoque_inicial_global
                   (cliente_id, produto_id, data_inicio, quantidade_inicial)
                   VALUES (%s, %s, %s, %s)""",
                (cliente_id, produto_id, data_inicio, quantidade),
            )
            conn.commit()
            flash('Estoque inicial registrado com sucesso.', 'success')
            return redirect(url_for('estoque_inicial_global.list_entries'))
        except Exception as exc:
            conn.rollback()
            # Unique constraint violation
            if 'uq_eig_cliente_produto' in str(exc) or '1062' in str(exc):
                flash('Já existe um registro de estoque inicial para este cliente e produto.', 'warning')
            else:
                flash(f'Erro ao salvar: {exc}', 'danger')
        finally:
            cur.close()
            conn.close()

    return render_template(
        'estoque_inicial_global/novo.html',
        clientes=clientes,
        produtos=produtos,
    )
