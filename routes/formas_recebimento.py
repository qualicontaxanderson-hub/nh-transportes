from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required
from utils.db import get_db_connection
from utils.decorators import admin_required

bp = Blueprint('formas_recebimento', __name__, url_prefix='/formas_recebimento')

_tables_ready = False


def _ensure_tables():
    """Garante que as colunas/tabelas extras de formas_recebimento existem. Idempotente."""
    global _tables_ready
    if _tables_ready:
        return
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        # Tabela junction formas_recebimento_empresas com conta_contabil_id por empresa
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS formas_recebimento_empresas (
                forma_recebimento_id INT NOT NULL,
                cliente_id           INT NOT NULL,
                conta_contabil_id    INT NULL,
                PRIMARY KEY (forma_recebimento_id, cliente_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        conn.commit()
        # Adicionar conta_contabil_id caso a tabela já exista sem ela
        cursor.execute(
            "SELECT COUNT(*) FROM information_schema.COLUMNS"
            " WHERE TABLE_SCHEMA = DATABASE()"
            " AND TABLE_NAME = 'formas_recebimento_empresas'"
            " AND COLUMN_NAME = 'conta_contabil_id'"
        )
        if cursor.fetchone()[0] == 0:
            cursor.execute(
                "ALTER TABLE formas_recebimento_empresas"
                " ADD COLUMN conta_contabil_id INT NULL"
            )
            conn.commit()
        cursor.close()
        _tables_ready = True
    finally:
        conn.close()


def _load_form_data(conn):
    """Carrega empresas com produtos e mapeamento empresa→contas contábeis."""
    cursor = conn.cursor(dictionary=True)
    # Apenas empresas que têm pelo menos um produto ativo em cliente_produtos
    cursor.execute(
        """SELECT DISTINCT c.id,
                  COALESCE(c.nome_fantasia, c.razao_social) AS nome,
                  c.grupo_contabil_id
             FROM clientes c
             JOIN cliente_produtos cp ON cp.cliente_id = c.id AND cp.ativo = 1
            ORDER BY nome"""
    )
    empresas = cursor.fetchall()
    # Contas contábeis agrupadas por grupo
    cursor.execute(
        """SELECT c.id, c.grupo_id, c.codigo, c.nome AS conta_nome,
                  g.codigo AS grupo_codigo, g.nome AS grupo_nome
             FROM plano_contas_contas c
             JOIN plano_contas_grupos g ON g.id = c.grupo_id
            WHERE c.ativo = 1
            ORDER BY g.codigo, c.codigo"""
    )
    contas_raw = cursor.fetchall()
    cursor.close()
    # Indexar contas por grupo_id para uso no JS
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
def lista():
    """Lista todas as formas de recebimento."""
    _ensure_tables()
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT id, nome, eh_cartao, tipo_cartao, ativo FROM formas_recebimento ORDER BY nome"
    )
    formas = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('formas_recebimento/lista.html', formas=formas)


@bp.route('/api/contas-by-empresa/<int:empresa_id>')
@login_required
def api_contas_by_empresa(empresa_id):
    """Retorna as contas contábeis vinculadas ao grupo contábil da empresa."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT grupo_contabil_id FROM clientes WHERE id = %s", (empresa_id,)
    )
    row = cursor.fetchone()
    if not row or not row['grupo_contabil_id']:
        cursor.close()
        conn.close()
        return jsonify([])
    grupo_id = row['grupo_contabil_id']
    cursor.execute(
        """SELECT c.id,
                  CONCAT(c.codigo, ' ', c.nome) AS label
             FROM plano_contas_contas c
             JOIN plano_contas_grupos g ON g.id = c.grupo_id
            WHERE c.grupo_id = %s AND c.ativo = 1
            ORDER BY c.codigo""",
        (grupo_id,)
    )
    contas = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify(contas)


@bp.route('/novo', methods=['GET', 'POST'])
@login_required
@admin_required
def novo():
    """Cria nova forma de recebimento."""
    _ensure_tables()
    conn = get_db_connection()
    if request.method == 'POST':
        nome = request.form.get('nome', '').strip()
        eh_cartao = 1 if request.form.get('eh_cartao') == '1' else 0
        tipo_cartao = request.form.get('tipo_cartao') or None
        if not eh_cartao:
            tipo_cartao = None
        # Pares empresa+conta vindos do formulário dinâmico
        empresa_ids = request.form.getlist('empresa_id[]')
        conta_ids = request.form.getlist('conta_contabil_id[]')
        if not nome:
            flash('Nome é obrigatório.', 'danger')
            empresas, contas_por_grupo = _load_form_data(conn)
            conn.close()
            return render_template('formas_recebimento/novo.html',
                                   empresas=empresas, contas_por_grupo=contas_por_grupo,
                                   vinculos=[])
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO formas_recebimento (nome, eh_cartao, tipo_cartao, ativo)"
                " VALUES (%s, %s, %s, 1)",
                (nome, eh_cartao, tipo_cartao),
            )
            forma_id = cursor.lastrowid
            seen = set()
            for eid, cid in zip(empresa_ids, conta_ids):
                eid = eid.strip() if eid else ''
                cid = (cid.strip() if cid else None) or None
                if eid and eid not in seen:
                    seen.add(eid)
                    cursor.execute(
                        "INSERT INTO formas_recebimento_empresas"
                        " (forma_recebimento_id, cliente_id, conta_contabil_id)"
                        " VALUES (%s, %s, %s)"
                        " ON DUPLICATE KEY UPDATE conta_contabil_id = VALUES(conta_contabil_id)",
                        (forma_id, int(eid), int(cid) if cid else None),
                    )
            conn.commit()
            flash(f'Forma de recebimento "{nome}" criada com sucesso!', 'success')
            return redirect(url_for('formas_recebimento.lista'))
        except Exception as e:
            conn.rollback()
            flash(f'Erro ao criar: {e}', 'danger')
        finally:
            cursor.close()
    empresas, contas_por_grupo = _load_form_data(conn)
    conn.close()
    return render_template('formas_recebimento/novo.html',
                           empresas=empresas, contas_por_grupo=contas_por_grupo,
                           vinculos=[])


@bp.route('/editar/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar(id):
    """Edita forma de recebimento existente."""
    _ensure_tables()
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM formas_recebimento WHERE id = %s", (id,))
    forma = cursor.fetchone()
    if not forma:
        cursor.close()
        conn.close()
        flash('Forma de recebimento não encontrada.', 'danger')
        return redirect(url_for('formas_recebimento.lista'))

    if request.method == 'POST':
        nome = request.form.get('nome', '').strip()
        eh_cartao = 1 if request.form.get('eh_cartao') == '1' else 0
        tipo_cartao = request.form.get('tipo_cartao') or None
        if not eh_cartao:
            tipo_cartao = None
        ativo = 1 if request.form.get('ativo') == '1' else 0
        empresa_ids = request.form.getlist('empresa_id[]')
        conta_ids = request.form.getlist('conta_contabil_id[]')
        if not nome:
            flash('Nome é obrigatório.', 'danger')
        else:
            cursor.execute(
                "UPDATE formas_recebimento SET nome=%s, eh_cartao=%s, tipo_cartao=%s, ativo=%s WHERE id=%s",
                (nome, eh_cartao, tipo_cartao, ativo, id),
            )
            cursor.execute(
                "DELETE FROM formas_recebimento_empresas WHERE forma_recebimento_id = %s", (id,)
            )
            seen = set()
            for eid, cid in zip(empresa_ids, conta_ids):
                eid = eid.strip() if eid else ''
                cid = (cid.strip() if cid else None) or None
                if eid and eid not in seen:
                    seen.add(eid)
                    cursor.execute(
                        "INSERT INTO formas_recebimento_empresas"
                        " (forma_recebimento_id, cliente_id, conta_contabil_id)"
                        " VALUES (%s, %s, %s)",
                        (id, int(eid), int(cid) if cid else None),
                    )
            conn.commit()
            flash('Atualizado com sucesso!', 'success')
            cursor.close()
            conn.close()
            return redirect(url_for('formas_recebimento.lista'))

    # Vínculos existentes
    cursor.execute(
        """SELECT fre.cliente_id, fre.conta_contabil_id,
                  COALESCE(c.nome_fantasia, c.razao_social) AS empresa_nome,
                  c.grupo_contabil_id
             FROM formas_recebimento_empresas fre
             JOIN clientes c ON c.id = fre.cliente_id
            WHERE fre.forma_recebimento_id = %s""",
        (id,)
    )
    vinculos = cursor.fetchall()
    cursor.close()
    empresas, contas_por_grupo = _load_form_data(conn)
    conn.close()
    return render_template('formas_recebimento/editar.html',
                           forma=forma,
                           empresas=empresas,
                           contas_por_grupo=contas_por_grupo,
                           vinculos=vinculos)


@bp.route('/excluir/<int:id>', methods=['POST'])
@login_required
@admin_required
def excluir(id):
    """Exclui forma de recebimento se não houver vínculos."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT COUNT(*) AS total FROM bank_transactions WHERE forma_recebimento_id = %s",
        (id,)
    )
    if cursor.fetchone()['total'] > 0:
        cursor.close()
        conn.close()
        return jsonify({'success': False, 'message': 'Não é possível excluir: há transações bancárias vinculadas a esta forma de recebimento.'})
    cursor.execute(
        "SELECT COUNT(*) AS total FROM bank_supplier_mapping WHERE forma_recebimento_id = %s",
        (id,)
    )
    if cursor.fetchone()['total'] > 0:
        cursor.close()
        conn.close()
        return jsonify({'success': False, 'message': 'Não é possível excluir: há mapeamentos automáticos vinculados. Edite ou remova-os primeiro.'})
    cursor.execute(
        "SELECT COUNT(*) AS total FROM bank_conciliacao_regras WHERE forma_recebimento_id = %s",
        (id,)
    )
    if cursor.fetchone()['total'] > 0:
        cursor.close()
        conn.close()
        return jsonify({'success': False, 'message': 'Não é possível excluir: há regras de conciliação vinculadas. Edite ou remova-as primeiro.'})
    cursor.execute("DELETE FROM formas_recebimento WHERE id = %s", (id,))
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({'success': True})


@bp.route('/api/listar')
@login_required
def api_listar():
    """API JSON — formas ativas para uso em modais."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT id, nome FROM formas_recebimento WHERE ativo=1 ORDER BY nome"
    )
    formas = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify(formas)
