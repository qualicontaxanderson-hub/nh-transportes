"""
Módulo de Preços por Forma de Recebimento.

Permite cadastrar formas de recebimento globais com acréscimos-padrão,
configurar acréscimos específicos por empresa e gerar texto formatado
para envio no WhatsApp.
"""

from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify
from flask_login import login_required
from utils.db import get_db_connection
import logging

bp = Blueprint('precos_posto', __name__, url_prefix='/precos')
logger = logging.getLogger(__name__)

_tables_ready = False

# Mapeamento de produto para abreviação usada no texto do WhatsApp
_PRODUTO_ABREV = [
    ('gasolina aditivada', 'Gás Aditivada'),
    ('gasolina',           'Gás'),
    ('etanol',             'Eta'),
    ('s-500',              'S-500'),
    ('s-10',               'S-10'),
    ('s500',               'S-500'),
    ('s10',                'S-10'),
    ('arla',               'ARLA'),
]


def _abrev_produto(nome):
    n = nome.lower().strip()
    for chave, abrev in _PRODUTO_ABREV:
        if chave in n:
            return abrev
    return nome


def _ensure_tables():
    global _tables_ready
    if _tables_ready:
        return
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS precos_formas_recebimento (
                id               INT AUTO_INCREMENT PRIMARY KEY,
                nome             VARCHAR(150) NOT NULL,
                acrescimo_padrao DECIMAL(10,4) NOT NULL DEFAULT 0.0000,
                is_base          TINYINT(1)   NOT NULL DEFAULT 0,
                ordem            INT          NOT NULL DEFAULT 99,
                ativo            TINYINT(1)   NOT NULL DEFAULT 1
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS precos_acrescimos_empresa (
                id          INT AUTO_INCREMENT PRIMARY KEY,
                cliente_id  INT          NOT NULL,
                forma_id    INT          NOT NULL,
                acrescimo   DECIMAL(10,4) NOT NULL DEFAULT 0.0000,
                UNIQUE KEY uk_clie_forma (cliente_id, forma_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS precos_produtos_empresa (
                id          INT AUTO_INCREMENT PRIMARY KEY,
                cliente_id  INT          NOT NULL,
                produto_id  INT          NOT NULL,
                preco_base  DECIMAL(10,4) NOT NULL DEFAULT 0.0000,
                UNIQUE KEY uk_clie_prod (cliente_id, produto_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS precos_forma_produtos_ocultos (
                forma_id   INT NOT NULL,
                produto_id INT NOT NULL,
                PRIMARY KEY (forma_id, produto_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        # Seed formas padrão caso a tabela esteja vazia
        cur.execute("SELECT COUNT(*) FROM precos_formas_recebimento")
        if cur.fetchone()[0] == 0:
            cur.execute("""
                INSERT INTO precos_formas_recebimento
                    (nome, acrescimo_padrao, is_base, ordem)
                VALUES
                    ('PIX / Dinheiro / Cheque Transportadora', 0.0000, 1, 1),
                    ('Cartão Débito',                          0.0500, 0, 2),
                    ('Cartão Crédito',                         0.1500, 0, 3),
                    ('X7 Bank',                                0.1000, 0, 4)
            """)
        conn.commit()
        cur.close()
        _tables_ready = True
    except Exception:
        logger.exception("precos_posto: _ensure_tables falhou")
        conn.rollback()
    finally:
        conn.close()


def _load_empresas_com_produtos(cur):
    cur.execute("""
        SELECT c.id,
               COALESCE(c.nome_fantasia, c.razao_social) AS nome
          FROM clientes c
          JOIN cliente_produtos cp ON cp.cliente_id = c.id AND cp.ativo = 1
         GROUP BY c.id, nome
         ORDER BY nome
    """)
    return cur.fetchall()


def _load_formas(cur):
    cur.execute("""
        SELECT id, nome, acrescimo_padrao, is_base, ordem
          FROM precos_formas_recebimento
         WHERE ativo = 1
         ORDER BY ordem, id
    """)
    return cur.fetchall()


# ── Rota principal ────────────────────────────────────────────────────────────

@bp.route('/', methods=['GET'])
@login_required
def index():
    _ensure_tables()
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        empresas = _load_empresas_com_produtos(cur)
        formas   = _load_formas(cur)

        cliente_id     = request.args.get('empresa', type=int)
        empresa_sel    = None
        produtos_lista = []
        acrescimos_emp = {}   # {forma_id: acrescimo}

        if cliente_id:
            empresa_sel = next((e for e in empresas if e['id'] == cliente_id), None)
            if empresa_sel:
                cur.execute("""
                    SELECT p.id, p.nome,
                           COALESCE(ppe.preco_base, 0) AS preco_base
                      FROM produto p
                      JOIN cliente_produtos cp
                           ON cp.produto_id = p.id AND cp.ativo = 1
                      LEFT JOIN precos_produtos_empresa ppe
                           ON ppe.cliente_id = %s AND ppe.produto_id = p.id
                     WHERE cp.cliente_id = %s
                     ORDER BY p.nome
                """, (cliente_id, cliente_id))
                produtos_raw = cur.fetchall()
                for p in produtos_raw:
                    p['abrev'] = _abrev_produto(p['nome'])
                produtos_lista = produtos_raw

                cur.execute("""
                    SELECT forma_id, acrescimo
                      FROM precos_acrescimos_empresa
                     WHERE cliente_id = %s
                """, (cliente_id,))
                for row in cur.fetchall():
                    acrescimos_emp[row['forma_id']] = float(row['acrescimo'])

        # Produtos ocultos por forma (global – independente de empresa selecionada)
        cur.execute("SELECT forma_id, produto_id FROM precos_forma_produtos_ocultos")
        ocultos_por_forma = {}
        for row in cur.fetchall():
            ocultos_por_forma.setdefault(row['forma_id'], []).append(row['produto_id'])
    finally:
        cur.close()
        conn.close()

    return render_template(
        'precos_posto/index.html',
        empresas=empresas,
        formas=formas,
        cliente_id=cliente_id,
        empresa_sel=empresa_sel,
        produtos_lista=produtos_lista,
        acrescimos_emp=acrescimos_emp,
        ocultos_por_forma=ocultos_por_forma,
    )


@bp.route('/salvar', methods=['POST'])
@login_required
def salvar():
    _ensure_tables()
    cliente_id = request.form.get('cliente_id', type=int)
    if not cliente_id:
        flash('Selecione uma empresa.', 'warning')
        return redirect(url_for('precos_posto.index'))

    conn = get_db_connection()
    cur  = conn.cursor()
    try:
        # Salvar preços base dos produtos
        produto_ids = request.form.getlist('produto_id[]')
        precos_base = request.form.getlist('preco_base[]')
        for pid_s, preco_s in zip(produto_ids, precos_base):
            try:
                pid   = int(pid_s)
                preco = float(preco_s.replace(',', '.'))
            except (ValueError, AttributeError):
                continue
            cur.execute("""
                INSERT INTO precos_produtos_empresa (cliente_id, produto_id, preco_base)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE preco_base = VALUES(preco_base)
            """, (cliente_id, pid, preco))

        # Salvar acréscimos por forma para esta empresa
        forma_ids  = request.form.getlist('forma_id[]')
        acrescimos = request.form.getlist('acrescimo[]')
        for fid_s, acr_s in zip(forma_ids, acrescimos):
            try:
                fid = int(fid_s)
                acr = float(acr_s.replace(',', '.'))
            except (ValueError, AttributeError):
                continue
            cur.execute("""
                INSERT INTO precos_acrescimos_empresa (cliente_id, forma_id, acrescimo)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE acrescimo = VALUES(acrescimo)
            """, (cliente_id, fid, acr))

        conn.commit()
        flash('Preços salvos com sucesso!', 'success')
    except Exception:
        conn.rollback()
        logger.exception("precos_posto.salvar: erro")
        flash('Erro ao salvar preços.', 'danger')
    finally:
        cur.close()
        conn.close()

    return redirect(url_for('precos_posto.index', empresa=cliente_id))


# ── Gerenciar formas de recebimento (ADMIN) ───────────────────────────────────

@bp.route('/formas', methods=['GET'])
@login_required
def formas():
    _ensure_tables()
    conn = get_db_connection()
    cur  = conn.cursor(dictionary=True)
    try:
        cur.execute("""
            SELECT id, nome, acrescimo_padrao, is_base, ordem, ativo
              FROM precos_formas_recebimento
             ORDER BY ordem, id
        """)
        formas_list = cur.fetchall()

        cur.execute("""
            SELECT DISTINCT p.id, p.nome
              FROM produto p
              JOIN cliente_produtos cp ON cp.produto_id = p.id AND cp.ativo = 1
             ORDER BY p.nome
        """)
        todos_produtos = cur.fetchall()
        for p in todos_produtos:
            p['abrev'] = _abrev_produto(p['nome'])

        cur.execute("SELECT forma_id, produto_id FROM precos_forma_produtos_ocultos")
        ocultos_por_forma = {}
        for row in cur.fetchall():
            ocultos_por_forma.setdefault(row['forma_id'], []).append(row['produto_id'])
    finally:
        cur.close()
        conn.close()
    return render_template('precos_posto/formas.html',
                           formas=formas_list,
                           todos_produtos=todos_produtos,
                           ocultos_por_forma=ocultos_por_forma)


@bp.route('/formas/nova', methods=['POST'])
@login_required
def formas_nova():
    _ensure_tables()
    nome     = request.form.get('nome', '').strip()
    acrescimo = request.form.get('acrescimo', '0').replace(',', '.')
    is_base  = 1 if request.form.get('is_base') else 0
    ordem    = request.form.get('ordem', '99')
    if not nome:
        flash('Nome é obrigatório.', 'warning')
        return redirect(url_for('precos_posto.formas'))
    try:
        acrescimo = float(acrescimo)
        ordem     = int(ordem)
    except ValueError:
        acrescimo, ordem = 0.0, 99

    conn = get_db_connection()
    cur  = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO precos_formas_recebimento (nome, acrescimo_padrao, is_base, ordem)
            VALUES (%s, %s, %s, %s)
        """, (nome, acrescimo, is_base, ordem))
        conn.commit()
        flash('Forma de recebimento criada.', 'success')
    except Exception:
        conn.rollback()
        flash('Erro ao criar forma de recebimento.', 'danger')
    finally:
        cur.close()
        conn.close()
    return redirect(url_for('precos_posto.formas'))


@bp.route('/formas/<int:forma_id>/editar', methods=['POST'])
@login_required
def formas_editar(forma_id):
    nome      = request.form.get('nome', '').strip()
    acrescimo = request.form.get('acrescimo', '0').replace(',', '.')
    is_base   = 1 if request.form.get('is_base') else 0
    ordem     = request.form.get('ordem', '99')
    try:
        acrescimo = float(acrescimo)
        ordem     = int(ordem)
    except ValueError:
        acrescimo, ordem = 0.0, 99

    conn = get_db_connection()
    cur  = conn.cursor()
    try:
        cur.execute("""
            UPDATE precos_formas_recebimento
               SET nome = %s, acrescimo_padrao = %s, is_base = %s, ordem = %s
             WHERE id = %s
        """, (nome, acrescimo, is_base, ordem, forma_id))
        conn.commit()
        flash('Forma de recebimento atualizada.', 'success')
    except Exception:
        conn.rollback()
        flash('Erro ao atualizar forma.', 'danger')
    finally:
        cur.close()
        conn.close()
    return redirect(url_for('precos_posto.formas'))


@bp.route('/formas/<int:forma_id>/excluir', methods=['POST'])
@login_required
def formas_excluir(forma_id):
    conn = get_db_connection()
    cur  = conn.cursor()
    try:
        # Não permite excluir forma base
        cur.execute(
            "DELETE FROM precos_formas_recebimento WHERE id = %s AND is_base = 0",
            (forma_id,)
        )
        conn.commit()
        flash('Forma de recebimento removida.', 'success')
    except Exception:
        conn.rollback()
        flash('Erro ao remover forma.', 'danger')
    finally:
        cur.close()
        conn.close()
    return redirect(url_for('precos_posto.formas'))


@bp.route('/formas/<int:forma_id>/toggle-produto', methods=['POST'])
@login_required
def formas_toggle_produto(forma_id):
    """Alterna visibilidade de um produto no texto do WhatsApp para uma forma."""
    data       = request.get_json(force=True) or {}
    produto_id = data.get('produto_id')
    visivel    = data.get('visivel')
    if produto_id is None or visivel is None:
        return jsonify({'success': False, 'error': 'Parâmetros inválidos'}), 400
    conn = get_db_connection()
    cur  = conn.cursor()
    try:
        if visivel:
            cur.execute(
                "DELETE FROM precos_forma_produtos_ocultos"
                " WHERE forma_id = %s AND produto_id = %s",
                (forma_id, int(produto_id))
            )
        else:
            cur.execute(
                "INSERT IGNORE INTO precos_forma_produtos_ocultos (forma_id, produto_id)"
                " VALUES (%s, %s)",
                (forma_id, int(produto_id))
            )
        conn.commit()
        return jsonify({'success': True})
    except Exception:
        conn.rollback()
        logger.exception("formas_toggle_produto: erro")
        return jsonify({'success': False, 'error': 'Erro interno'}), 500
    finally:
        cur.close()
        conn.close()
