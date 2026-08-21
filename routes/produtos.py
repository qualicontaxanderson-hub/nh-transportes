from datetime import date
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


def _movimento_produtos(cursor):
    """O que cada produto move: frete (o que faturamos) e compra (a DFe).

    Era o que faltava nesta tela — ela listava nome e conta contabil sem
    dizer que o ETANOL responde por 672 fretes e o ARLA por um so, de
    dezembro de 2025.
    """
    frete, compra = {}, {}
    try:
        cursor.execute("""
            SELECT f.produto_id AS pid, COUNT(*) AS n,
                   COALESCE(SUM(f.valor_cte),0) AS total,
                   COUNT(DISTINCT f.clientes_id) AS clientes,
                   MAX(DATE(f.data_frete)) AS ultimo
              FROM fretes f WHERE f.produto_id IS NOT NULL
             GROUP BY f.produto_id
        """)
        frete = {r['pid']: {'n': int(r['n']), 'total': float(r['total'] or 0),
                            'clientes': int(r['clientes']),
                            'ultimo': r['ultimo']} for r in cursor.fetchall()}
    except Exception:
        pass
    try:
        cursor.execute("""
            SELECT i.produto_id AS pid, COUNT(*) AS n,
                   COALESCE(SUM(i.quantidade),0) AS litros,
                   COALESCE(SUM(i.valor_total),0) AS valor
              FROM dfe_itens i WHERE i.produto_id IS NOT NULL
             GROUP BY i.produto_id
        """)
        compra = {r['pid']: {'n': int(r['n']), 'litros': float(r['litros'] or 0),
                             'valor': float(r['valor'] or 0)}
                  for r in cursor.fetchall()}
    except Exception:
        pass
    return frete, compra


def _empresas_por_produto(cursor):
    """Quais empresas usam cada produto.

    Vem de `cliente_produtos` — o vinculo que EXISTE (13 linhas). A tela
    antiga filtrava por `produto_empresas`, que esta vazia, entao escolher
    uma empresa no filtro devolvia zero produtos, sempre.
    """
    try:
        cursor.execute("""
            SELECT cp.produto_id AS pid, cp.cliente_id AS cid,
                   COALESCE(c.nome_fantasia, c.razao_social) AS nome
              FROM cliente_produtos cp
              JOIN clientes c ON c.id = cp.cliente_id
             WHERE cp.ativo = 1
             ORDER BY nome
        """)
        saida = {}
        for r in cursor.fetchall():
            saida.setdefault(r['pid'], []).append(
                {'id': r['cid'], 'nome': r['nome']})
        return saida
    except Exception:
        return {}


@bp.route('/')
@login_required
def lista():
    _ensure_tables()
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    grupo_id = request.args.get('grupo_id', '').strip()
    cliente_id = request.args.get('cliente_id', '').strip()

    # A conta contabil por empresa entra como AGREGADO: o LEFT JOIN antigo
    # multiplicava a linha do produto por empresa vinculada (e, com a tabela
    # vazia, ainda zerava o resultado quando alguem filtrava por empresa).
    cursor.execute("""
        SELECT p.*,
               (SELECT GROUP_CONCAT(CONCAT(pcc.codigo, ' ', pcc.nome)
                        ORDER BY pcc.codigo SEPARATOR ' | ')
                  FROM produto_empresas pe
                  JOIN plano_contas_contas pcc ON pcc.id = pe.conta_contabil_id
                 WHERE pe.produto_id = p.id) AS contas,
               (SELECT COUNT(*) FROM produto_empresas pe
                 WHERE pe.produto_id = p.id AND pe.conta_contabil_id IS NOT NULL)
                 AS n_contas
          FROM produto p
         ORDER BY p.nome
    """)
    produtos = cursor.fetchall()

    frete, compra = _movimento_produtos(cursor)
    empresas_prod = _empresas_por_produto(cursor)
    cursor.close()

    maior = max([m['total'] for m in frete.values()] or [0]) or 1
    for p in produtos:
        fr = frete.get(p['id']) or {'n': 0, 'total': 0.0, 'clientes': 0,
                                    'ultimo': None}
        cp = compra.get(p['id']) or {'n': 0, 'litros': 0.0, 'valor': 0.0}
        p['fre_n'] = fr['n']
        p['fre_total'] = fr['total']
        p['fre_clientes'] = fr['clientes']
        p['fre_ultimo'] = fr['ultimo']
        p['cmp_n'] = cp['n']
        p['cmp_litros'] = cp['litros']
        p['cmp_valor'] = cp['valor']
        p['cmp_medio'] = (cp['valor'] / cp['litros']) if cp['litros'] else 0.0
        p['peso'] = round(100.0 * fr['total'] / maior, 1)
        p['empresas'] = empresas_prod.get(p['id'], [])
        p['sem_conta'] = not p.get('n_contas')
        # Parado e por TEMPO, nao por zero: o ARLA tem 1 frete — de dezembro de
        # 2025. Contar so quem tem zero deixava ele passar como ativo.
        p['parado'] = (not fr['ultimo']) or (
            (date.today() - fr['ultimo']).days > 90)
        p['dias_parado'] = ((date.today() - fr['ultimo']).days
                            if fr['ultimo'] else None)

    totais = {
        'produtos': len(produtos),
        'faturado': sum(p['fre_total'] for p in produtos),
        'parados': sum(1 for p in produtos if p['parado']),
        'sem_conta': sum(1 for p in produtos if p['sem_conta']),
        'litros': sum(p['cmp_litros'] for p in produtos),
    }

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
                           totais=totais, grupos=grupos, grupo_id=grupo_id,
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
