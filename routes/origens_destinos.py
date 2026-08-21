from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from utils.db import get_db_connection

bp = Blueprint('origens_destinos', __name__, url_prefix='/origens_destinos')

def get_db():
    """Usa a conexão centralizada com credenciais seguras"""
    return get_db_connection()

# ==================== ROOT / INDEX ====================

def _rotas_e_fretes(cursor, campo):
    """Rotas e fretes por origem (campo='origem_id') ou destino ('destino_id').

    Devolve (rotas, fretes) indexados pelo id. As rotas vem com o outro lado
    e o valor por litro — e o que dá sentido ao cadastro.
    """
    outro = 'destino_id' if campo == 'origem_id' else 'origem_id'
    tab_outro = 'destinos' if campo == 'origem_id' else 'origens'
    rotas = {}
    try:
        cursor.execute("""
            SELECT r.%s AS id, o.nome AS outro_nome, r.valor_por_litro AS valor,
                   r.ativo
              FROM rotas r
              LEFT JOIN %s o ON o.id = r.%s
             ORDER BY r.valor_por_litro
        """ % (campo, tab_outro, outro))
        for r in cursor.fetchall():
            rotas.setdefault(r['id'], []).append({
                'outro': r['outro_nome'] or '?',
                'valor': float(r['valor'] or 0),
                'ativo': bool(r['ativo'])})
    except Exception:
        pass
    fretes = {}
    try:
        cursor.execute("""
            SELECT f.%s AS id, COUNT(*) AS n,
                   COALESCE(SUM(f.valor_cte),0) AS cte,
                   MAX(DATE(f.data_frete)) AS ultimo
              FROM fretes f WHERE f.%s IS NOT NULL
             GROUP BY f.%s
        """ % (campo, campo, campo))
        fretes = {r['id']: {'n': int(r['n']), 'cte': float(r['cte'] or 0),
                            'ultimo': r['ultimo']} for r in cursor.fetchall()}
    except Exception:
        pass
    return rotas, fretes


def _monta_od(itens, rotas, fretes, clientes=None):
    """Pendura rotas/fretes em cada origem ou destino e devolve os totais."""
    maior = max([f['n'] for f in fretes.values()] or [0]) or 1
    for it in itens:
        rs = rotas.get(it['id'], [])
        fr = fretes.get(it['id']) or {'n': 0, 'cte': 0.0, 'ultimo': None}
        it['rotas'] = rs
        it['n_rotas'] = len(rs)
        it['fre_n'] = fr['n']
        it['fre_cte'] = fr['cte']
        it['fre_ultimo'] = fr['ultimo']
        it['peso'] = round(100.0 * fr['n'] / maior, 1)
        it['clientes'] = (clientes or {}).get(it['id'], 0)
        # O caso que dói: roda frete e nao tem rota — o valor por litro do
        # CT-e teve que ser digitado a mao em cada lancamento.
        it['sem_rota_com_frete'] = (fr['n'] > 0 and not rs)
        it['nunca_usado'] = (fr['n'] == 0)

    return {
        'itens': len(itens),
        'com_rota': sum(1 for i in itens if i['n_rotas']),
        'sem_rota': sum(1 for i in itens if not i['n_rotas']),
        'sem_rota_com_frete': sum(1 for i in itens if i['sem_rota_com_frete']),
        'nunca_usados': sum(1 for i in itens if i['nunca_usado']),
        'fretes': sum(i['fre_n'] for i in itens),
        'estados': sorted({(i.get('estado') or '—') for i in itens}),
    }


@bp.route('/')
@login_required
def index():
    """Redireciona para a página de origens"""
    return redirect(url_for('origens_destinos.lista_origens'))

# ==================== ORIGENS ====================

@bp.route('/origens')
@login_required
def lista_origens():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM origens ORDER BY nome")
    origens = cursor.fetchall()
    rotas, fretes = _rotas_e_fretes(cursor, 'origem_id')
    cursor.close()
    conn.close()
    totais = _monta_od(origens, rotas, fretes)
    return render_template('origens_destinos/lista_origens.html',
                           origens=origens, totais=totais)

@bp.route('/origens/nova', methods=['POST'])
@login_required
def nova_origem():
    nome = request.form.get('nome', '').strip().upper()
    estado = request.form.get('estado', '').strip().upper()

    if not nome or not estado:
        flash('Nome e Estado são obrigatórios!', 'danger')
        return redirect(url_for('origens_destinos.lista_origens'))

    conn = None
    cursor = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO origens (nome, estado) VALUES (%s, %s)", (nome, estado))
        conn.commit()
        flash('Origem cadastrada com sucesso!', 'success')
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao cadastrar origem: {str(e)}', 'danger')
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

    return redirect(url_for('origens_destinos.lista_origens'))

@bp.route('/origens/editar/<int:id>', methods=['POST'])
@login_required
def editar_origem(id):
    conn = None
    cursor = None
    try:
        nome = request.form.get('nome', '').strip().upper()
        estado = request.form.get('estado', '').strip().upper()

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("UPDATE origens SET nome = %s, estado = %s WHERE id = %s", (nome, estado, id))
        conn.commit()
        flash('Origem atualizada com sucesso!', 'success')
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao atualizar origem: {str(e)}', 'danger')
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

    return redirect(url_for('origens_destinos.lista_origens'))

@bp.route('/origens/excluir/<int:id>')
@login_required
def excluir_origem(id):
    conn = None
    cursor = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM origens WHERE id = %s", (id,))
        conn.commit()
        flash('Origem excluída com sucesso!', 'success')
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao excluir origem: {str(e)}', 'danger')
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

    return redirect(url_for('origens_destinos.lista_origens'))

# ==================== DESTINOS ====================

@bp.route('/destinos')
@login_required
def lista_destinos():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM destinos ORDER BY nome")
    destinos = cursor.fetchall()
    rotas, fretes = _rotas_e_fretes(cursor, 'destino_id')
    # Quantos clientes tem este destino como padrao (e dai que o frete
    # pre-preenche a rota).
    clientes = {}
    try:
        cursor.execute("""SELECT destino_id AS id, COUNT(*) AS n FROM clientes
                           WHERE destino_id IS NOT NULL GROUP BY destino_id""")
        clientes = {r['id']: int(r['n']) for r in cursor.fetchall()}
    except Exception:
        pass
    cursor.close()
    conn.close()
    totais = _monta_od(destinos, rotas, fretes, clientes)
    totais['clientes'] = sum(d['clientes'] for d in destinos)
    return render_template('origens_destinos/lista_destinos.html',
                           destinos=destinos, totais=totais)

@bp.route('/destinos/novo', methods=['POST'])
@login_required
def novo_destino():
    nome = request.form.get('nome', '').strip().upper()
    estado = request.form.get('estado', '').strip().upper()

    if not nome or not estado:
        flash('Nome e Estado são obrigatórios!', 'danger')
        return redirect(url_for('origens_destinos.lista_destinos'))

    conn = None
    cursor = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO destinos (nome, estado) VALUES (%s, %s)", (nome, estado))
        conn.commit()
        flash('Destino cadastrado com sucesso!', 'success')
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao cadastrar destino: {str(e)}', 'danger')
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

    return redirect(url_for('origens_destinos.lista_destinos'))

@bp.route('/destinos/editar/<int:id>', methods=['POST'])
@login_required
def editar_destino(id):
    conn = None
    cursor = None
    try:
        nome = request.form.get('nome', '').strip().upper()
        estado = request.form.get('estado', '').strip().upper()

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("UPDATE destinos SET nome = %s, estado = %s WHERE id = %s", (nome, estado, id))
        conn.commit()
        flash('Destino atualizado com sucesso!', 'success')
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao atualizar destino: {str(e)}', 'danger')
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

    return redirect(url_for('origens_destinos.lista_destinos'))

@bp.route('/destinos/excluir/<int:id>')
@login_required
def excluir_destino(id):
    conn = None
    cursor = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM destinos WHERE id = %s", (id,))
        conn.commit()
        flash('Destino excluído com sucesso!', 'success')
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Erro ao excluir destino: {str(e)}', 'danger')
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

    return redirect(url_for('origens_destinos.lista_destinos'))
