import os
import datetime as _dt

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from utils.db import get_db_connection

bp = Blueprint('bank_import', __name__, url_prefix='/banco')


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _get_accounts(cursor):
    cursor.execute(
        "SELECT id, banco_nome, agencia, conta, apelido FROM bank_accounts WHERE ativo = 1 ORDER BY apelido, banco_nome"
    )
    return cursor.fetchall()


def _get_fornecedores(cursor):
    cursor.execute(
        "SELECT id, razao_social, cnpj FROM fornecedores ORDER BY razao_social"
    )
    return cursor.fetchall()


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@bp.route('/')
@login_required
def index():
    """Página principal – dashboard de importação bancária."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    contas = _get_accounts(cursor)

    # Summary counts
    cursor.execute("SELECT COUNT(*) AS total FROM bank_transactions WHERE status = 'pendente'")
    pendentes = cursor.fetchone()['total']
    cursor.execute("SELECT COUNT(*) AS total FROM bank_transactions WHERE status = 'conciliado'")
    conciliados = cursor.fetchone()['total']
    cursor.execute("SELECT COUNT(*) AS total FROM bank_transactions")
    total = cursor.fetchone()['total']

    cursor.close()
    conn.close()

    return render_template(
        'bank_import/index.html',
        contas=contas,
        pendentes=pendentes,
        conciliados=conciliados,
        total=total,
    )


@bp.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    """Upload e importação de arquivo OFX."""
    if request.method == 'GET':
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        contas = _get_accounts(cursor)
        cursor.close()
        conn.close()
        return render_template('bank_import/index.html',
                               contas=contas, pendentes=0, conciliados=0, total=0)

    # POST – process uploaded file
    arquivo = request.files.get('ofx_file')
    account_id = request.form.get('account_id')

    if not arquivo or not arquivo.filename:
        flash('Nenhum arquivo selecionado.', 'warning')
        return redirect(url_for('bank_import.index'))

    if not account_id:
        flash('Selecione uma conta bancária.', 'warning')
        return redirect(url_for('bank_import.index'))

    try:
        content = arquivo.read().decode('latin-1', errors='replace')
    except Exception as exc:
        flash(f'Erro ao ler arquivo: {exc}', 'danger')
        return redirect(url_for('bank_import.index'))

    from integrations.ofx_parser import OFXParser
    parser = OFXParser(content)
    transactions = parser.get_transactions()

    if not transactions:
        flash('Nenhuma transação encontrada no arquivo OFX.', 'warning')
        return redirect(url_for('bank_import.index'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    inseridos = 0
    duplicados = 0

    for tx in transactions:
        # Check deduplication
        cursor.execute(
            "SELECT id FROM bank_transactions WHERE hash_dedup = %s",
            (tx['hash_dedup'],),
        )
        if cursor.fetchone():
            duplicados += 1
            continue

        # Check for existing mapping to auto-reconcile
        fornecedor_id = None
        status = 'pendente'
        if tx.get('cnpj_cpf'):
            cursor.execute(
                "SELECT fornecedor_id FROM bank_supplier_mapping WHERE cnpj_cpf = %s",
                (tx['cnpj_cpf'],),
            )
            mapping = cursor.fetchone()
            if mapping:
                fornecedor_id = mapping['fornecedor_id']
                status = 'conciliado'

        cursor.execute(
            """INSERT INTO bank_transactions
               (account_id, hash_dedup, data_transacao, tipo, valor, descricao,
                cnpj_cpf, memo, fitid, status, fornecedor_id, conciliado_em, conciliado_por)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                account_id,
                tx['hash_dedup'],
                tx['data_transacao'],
                tx['tipo'],
                tx['valor'],
                tx['descricao'],
                tx.get('cnpj_cpf'),
                tx.get('memo'),
                tx.get('fitid'),
                status,
                fornecedor_id,
                None if status == 'pendente' else _dt.datetime.now(),
                None if status == 'pendente' else 'auto',
            ),
        )
        inseridos += 1

    conn.commit()
    cursor.close()
    conn.close()

    flash(
        f'Importação concluída: {inseridos} transação(ões) importada(s), {duplicados} duplicata(s) ignorada(s).',
        'success',
    )
    return redirect(url_for('bank_import.index'))


@bp.route('/conciliar', methods=['GET', 'POST'])
@login_required
def conciliar():
    """Interface de conciliação manual de transações pendentes."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    if request.method == 'POST':
        tx_id = request.form.get('transaction_id')
        fornecedor_id = request.form.get('fornecedor_id')
        acao = request.form.get('acao', 'conciliar')

        if tx_id:
            if acao == 'ignorar':
                cursor.execute(
                    "UPDATE bank_transactions SET status='ignorado' WHERE id=%s", (tx_id,)
                )
                conn.commit()
                flash('Transação marcada como ignorada.', 'info')
            elif fornecedor_id:
                cursor.execute(
                    """UPDATE bank_transactions
                       SET status='conciliado', fornecedor_id=%s,
                           conciliado_em=%s, conciliado_por=%s
                       WHERE id=%s""",
                    (fornecedor_id, _dt.datetime.now(), current_user.email if hasattr(current_user, 'email') else 'manual', tx_id),
                )
                # Learn the mapping if CNPJ is known
                cursor.execute("SELECT cnpj_cpf FROM bank_transactions WHERE id=%s", (tx_id,))
                row = cursor.fetchone()
                if row and row.get('cnpj_cpf'):
                    cursor.execute(
                        """INSERT INTO bank_supplier_mapping (fornecedor_id, cnpj_cpf, tipo_chave, total_conciliacoes)
                           VALUES (%s, %s, 'cnpj', 1)
                           ON DUPLICATE KEY UPDATE fornecedor_id=%s, total_conciliacoes=total_conciliacoes+1, atualizado_em=NOW()""",
                        (fornecedor_id, row['cnpj_cpf'], fornecedor_id),
                    )
                conn.commit()
                flash('Transação conciliada com sucesso!', 'success')
            else:
                flash('Selecione um fornecedor para conciliar.', 'warning')

    # List pending transactions
    page = request.args.get('page', 1, type=int)
    per_page = 20
    offset = (page - 1) * per_page

    cursor.execute(
        """SELECT bt.*, ba.apelido AS conta_apelido, ba.banco_nome
           FROM bank_transactions bt
           INNER JOIN bank_accounts ba ON bt.account_id = ba.id
           WHERE bt.status = 'pendente'
           ORDER BY bt.data_transacao DESC
           LIMIT %s OFFSET %s""",
        (per_page, offset),
    )
    transacoes = cursor.fetchall()

    cursor.execute("SELECT COUNT(*) AS total FROM bank_transactions WHERE status='pendente'")
    total = cursor.fetchone()['total']

    fornecedores = _get_fornecedores(cursor)

    cursor.close()
    conn.close()

    total_pages = (total + per_page - 1) // per_page

    return render_template(
        'bank_import/conciliar.html',
        transacoes=transacoes,
        fornecedores=fornecedores,
        page=page,
        total_pages=total_pages,
        total=total,
    )


@bp.route('/relatorio')
@login_required
def relatorio():
    """Relatório de transações com filtros."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    contas = _get_accounts(cursor)

    # Filters
    account_id = request.args.get('account_id', '')
    status = request.args.get('status', '')
    data_ini = request.args.get('data_ini', '')
    data_fim = request.args.get('data_fim', '')

    # Build safe parameterized query using only hardcoded clause strings
    # (user values go into the params list, never into the SQL string itself)
    _ALLOWED_STATUSES = {'pendente', 'conciliado', 'ignorado'}
    base_where = 'WHERE 1=1'
    extra_clauses = []
    params = []

    if account_id:
        extra_clauses.append('AND bt.account_id = %s')
        params.append(account_id)
    if status and status in _ALLOWED_STATUSES:
        extra_clauses.append('AND bt.status = %s')
        params.append(status)
    if data_ini:
        extra_clauses.append('AND bt.data_transacao >= %s')
        params.append(data_ini)
    if data_fim:
        extra_clauses.append('AND bt.data_transacao <= %s')
        params.append(data_fim)

    where_clauses = ' '.join([base_where] + extra_clauses)

    cursor.execute(
        """SELECT bt.*, ba.apelido AS conta_apelido, ba.banco_nome,
                   f.razao_social AS fornecedor_nome
            FROM bank_transactions bt
            INNER JOIN bank_accounts ba ON bt.account_id = ba.id
            LEFT JOIN fornecedores f ON bt.fornecedor_id = f.id
            """
        + where_clauses
        + """ ORDER BY bt.data_transacao DESC LIMIT 500""",
        params,
    )
    transacoes = cursor.fetchall()

    # Totals
    cursor.execute(
        """SELECT
               SUM(CASE WHEN tipo='DEBIT' THEN valor ELSE 0 END) AS total_debitos,
               SUM(CASE WHEN tipo='CREDIT' THEN valor ELSE 0 END) AS total_creditos,
               COUNT(*) AS total_transacoes
            FROM bank_transactions bt
            """
        + where_clauses,
        params,
    )
    totais = cursor.fetchone()

    cursor.close()
    conn.close()

    return render_template(
        'bank_import/relatorio.html',
        transacoes=transacoes,
        contas=contas,
        totais=totais,
        filtros={
            'account_id': account_id,
            'status': status,
            'data_ini': data_ini,
            'data_fim': data_fim,
        },
    )


# ---------------------------------------------------------------------------
# REST API endpoints
# ---------------------------------------------------------------------------

@bp.route('/api/transacoes-pendentes')
@login_required
def api_transacoes_pendentes():
    """API: retorna lista JSON de transações pendentes."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        """SELECT bt.id, bt.data_transacao, bt.tipo, bt.valor, bt.descricao,
                  bt.cnpj_cpf, bt.status, ba.apelido AS conta_apelido
           FROM bank_transactions bt
           INNER JOIN bank_accounts ba ON bt.account_id = ba.id
           WHERE bt.status = 'pendente'
           ORDER BY bt.data_transacao DESC
           LIMIT 200"""
    )
    rows = cursor.fetchall()

    cursor.close()
    conn.close()

    # Convert date objects to ISO strings for JSON serialisation
    for row in rows:
        if row.get('data_transacao'):
            row['data_transacao'] = str(row['data_transacao'])
        if row.get('valor') is not None:
            row['valor'] = float(row['valor'])

    return jsonify(rows)


@bp.route('/api/auto-reconcile', methods=['POST'])
@login_required
def api_auto_reconcile():
    """API: força a auto-conciliação de transações pendentes com mapeamento."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        """SELECT bt.id, bsm.fornecedor_id
           FROM bank_transactions bt
           INNER JOIN bank_supplier_mapping bsm ON bt.cnpj_cpf = bsm.cnpj_cpf
           WHERE bt.status = 'pendente' AND bt.cnpj_cpf IS NOT NULL AND bt.cnpj_cpf != ''"""
    )
    rows = cursor.fetchall()

    updated = 0
    for row in rows:
        cursor.execute(
            """UPDATE bank_transactions
               SET status='conciliado', fornecedor_id=%s, conciliado_em=%s, conciliado_por='auto'
               WHERE id=%s""",
            (row['fornecedor_id'], _dt.datetime.now(), row['id']),
        )
        updated += 1

    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({'success': True, 'conciliados': updated})


@bp.route('/api/contas', methods=['GET'])
@login_required
def api_contas():
    """API: lista contas bancárias cadastradas."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    contas = _get_accounts(cursor)
    cursor.close()
    conn.close()
    return jsonify(contas)


@bp.route('/api/contas', methods=['POST'])
@login_required
def api_criar_conta():
    """API: cria uma nova conta bancária."""
    data = request.get_json() or {}
    banco_nome = (data.get('banco_nome') or '').strip()
    if not banco_nome:
        return jsonify({'success': False, 'message': 'banco_nome é obrigatório'}), 400

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        """INSERT INTO bank_accounts (banco_nome, agencia, conta, apelido)
           VALUES (%s, %s, %s, %s)""",
        (banco_nome, data.get('agencia'), data.get('conta'), data.get('apelido')),
    )
    conn.commit()
    new_id = cursor.lastrowid
    cursor.close()
    conn.close()

    return jsonify({'success': True, 'id': new_id}), 201


# ---------------------------------------------------------------------------
# Watch-folder / OFX inbox endpoints
# ---------------------------------------------------------------------------

def _get_inbox_dir() -> str:
    """Return the configured OFX inbox directory, creating it if absent."""
    from config import Config
    inbox = Config.OFX_INBOX_DIR
    os.makedirs(inbox, exist_ok=True)
    os.makedirs(os.path.join(inbox, 'processados'), exist_ok=True)
    return inbox


@bp.route('/api/inbox-files')
@login_required
def api_inbox_files():
    """API: lista arquivos OFX encontrados na pasta de entrada."""
    import os as _os

    inbox = _get_inbox_dir()
    files = []
    try:
        for name in sorted(_os.listdir(inbox)):
            if not name.lower().endswith('.ofx'):
                continue
            full = _os.path.join(inbox, name)
            if not _os.path.isfile(full):
                continue
            stat = _os.stat(full)
            files.append({
                'nome': name,
                'tamanho': stat.st_size,
                'modificado': _dt.datetime.fromtimestamp(stat.st_mtime).strftime('%d/%m/%Y %H:%M'),
            })
    except OSError as exc:
        return jsonify({'success': False, 'message': str(exc), 'files': []}), 500

    return jsonify({'success': True, 'pasta': inbox, 'files': files})


@bp.route('/api/inbox-upload', methods=['POST'])
@login_required
def api_inbox_upload():
    """
    Salva um arquivo OFX na pasta de entrada SEM processar imediatamente.

    Útil no Railway (container efêmero): o usuário faz upload pelo navegador,
    o arquivo fica na pasta inbox aguardando, e pode ser importado depois
    clicando em "Importar" na seção "Pasta de Entrada OFX".
    """
    arquivo = request.files.get('ofx_file')
    if not arquivo or not arquivo.filename:
        return jsonify({'success': False, 'message': 'Nenhum arquivo enviado'}), 400

    nome = os.path.basename(arquivo.filename)
    if not nome.lower().endswith('.ofx'):
        return jsonify({'success': False, 'message': 'Apenas arquivos .ofx são aceitos'}), 400

    inbox = _get_inbox_dir()
    dest = os.path.join(inbox, nome)

    # Avoid overwriting an existing file – prefix with timestamp
    if os.path.exists(dest):
        ts = _dt.datetime.now().strftime('%Y%m%d%H%M%S_')
        nome = ts + nome
        dest = os.path.join(inbox, nome)

    try:
        arquivo.save(dest)
    except OSError as exc:
        return jsonify({'success': False, 'message': f'Erro ao salvar arquivo: {exc}'}), 500

    return jsonify({'success': True, 'nome': nome, 'message': f'Arquivo "{nome}" salvo na pasta de entrada.'})


@bp.route('/scan-inbox', methods=['POST'])
@login_required
def scan_inbox():
    """
    Processa um arquivo OFX da pasta de entrada.

    Parâmetros POST (form ou JSON):
        account_id  – ID da conta bancária destino
        nome_arquivo – nome do arquivo dentro da pasta de entrada
    """
    import os as _os

    # Accept both form-data and JSON
    if request.is_json:
        data = request.get_json() or {}
    else:
        data = request.form

    account_id = data.get('account_id')
    nome_arquivo = (data.get('nome_arquivo') or '').strip()

    if not account_id:
        if request.is_json:
            return jsonify({'success': False, 'message': 'account_id é obrigatório'}), 400
        flash('Selecione uma conta bancária.', 'warning')
        return redirect(url_for('bank_import.index'))

    if not nome_arquivo:
        if request.is_json:
            return jsonify({'success': False, 'message': 'nome_arquivo é obrigatório'}), 400
        flash('Nenhum arquivo especificado.', 'warning')
        return redirect(url_for('bank_import.index'))

    # Security: only plain file names allowed – block any path traversal attempt
    if _os.sep in nome_arquivo or '/' in nome_arquivo or '\\' in nome_arquivo or '..' in nome_arquivo:
        if request.is_json:
            return jsonify({'success': False, 'message': 'Nome de arquivo inválido'}), 400
        flash('Nome de arquivo inválido.', 'danger')
        return redirect(url_for('bank_import.index'))

    inbox = _get_inbox_dir()
    filepath = _os.path.join(inbox, nome_arquivo)

    if not _os.path.isfile(filepath):
        if request.is_json:
            return jsonify({'success': False, 'message': f'Arquivo não encontrado: {nome_arquivo}'}), 404
        flash(f'Arquivo não encontrado: {nome_arquivo}', 'danger')
        return redirect(url_for('bank_import.index'))

    # Read and parse.
    # OFX v1.x (SGML) files commonly use Latin-1 / ISO-8859-1 encoding.
    # Using 'latin-1' with errors='replace' is the safest universal choice:
    # it maps all 256 byte values, so no byte is ever undecodable.
    try:
        with open(filepath, 'r', encoding='latin-1', errors='replace') as fh:
            content = fh.read()
    except OSError as exc:
        if request.is_json:
            return jsonify({'success': False, 'message': str(exc)}), 500
        flash(f'Erro ao ler arquivo: {exc}', 'danger')
        return redirect(url_for('bank_import.index'))

    from integrations.ofx_parser import OFXParser
    transactions = OFXParser(content).get_transactions()

    if not transactions:
        if request.is_json:
            return jsonify({'success': False, 'message': 'Nenhuma transação encontrada no arquivo OFX.'}), 422
        flash('Nenhuma transação encontrada no arquivo OFX.', 'warning')
        return redirect(url_for('bank_import.index'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    inseridos = 0
    duplicados = 0

    for tx in transactions:
        cursor.execute(
            "SELECT id FROM bank_transactions WHERE hash_dedup = %s",
            (tx['hash_dedup'],),
        )
        if cursor.fetchone():
            duplicados += 1
            continue

        fornecedor_id = None
        status = 'pendente'
        if tx.get('cnpj_cpf'):
            cursor.execute(
                "SELECT fornecedor_id FROM bank_supplier_mapping WHERE cnpj_cpf = %s",
                (tx['cnpj_cpf'],),
            )
            mapping = cursor.fetchone()
            if mapping:
                fornecedor_id = mapping['fornecedor_id']
                status = 'conciliado'

        cursor.execute(
            """INSERT INTO bank_transactions
               (account_id, hash_dedup, data_transacao, tipo, valor, descricao,
                cnpj_cpf, memo, fitid, status, fornecedor_id, conciliado_em, conciliado_por)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                account_id,
                tx['hash_dedup'],
                tx['data_transacao'],
                tx['tipo'],
                tx['valor'],
                tx['descricao'],
                tx.get('cnpj_cpf'),
                tx.get('memo'),
                tx.get('fitid'),
                status,
                fornecedor_id,
                None if status == 'pendente' else _dt.datetime.now(),
                None if status == 'pendente' else 'auto',
            ),
        )
        inseridos += 1

    conn.commit()
    cursor.close()
    conn.close()

    # Move file to processados/
    dest = _os.path.join(inbox, 'processados', nome_arquivo)
    # Avoid collision: prefix with timestamp if destination already exists
    if _os.path.exists(dest):
        ts = _dt.datetime.now().strftime('%Y%m%d%H%M%S_')
        dest = _os.path.join(inbox, 'processados', ts + nome_arquivo)
    try:
        _os.rename(filepath, dest)
    except OSError:
        pass  # Non-fatal – file processed even if move fails

    msg = f'{nome_arquivo}: {inseridos} transação(ões) importada(s), {duplicados} duplicata(s) ignorada(s).'
    if request.is_json:
        return jsonify({'success': True, 'message': msg, 'inseridos': inseridos, 'duplicados': duplicados})
    flash(msg, 'success')
    return redirect(url_for('bank_import.index'))

