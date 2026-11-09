"""Lançamentos > Migração Contábil (pedido 08/11/2026).

Transferência entre EMPRESAS do grupo: no financeiro é uma linha só, no contábil
sai no livro das duas. Aqui o usuário escolhe a conta de cada lado:
  - uma regra por empresa + contraparte + sentido ("NH envia para Prest"),
    com "Aplicar a todos";
  - exceção por lançamento (abre a linha e troca só aquele);
  - "Sem origem": o que entrou/saiu como transferência sem a outra conta,
    classificado um por um.
O exportar contábil (bank_import.exportar_contabil) lê o que for gravado aqui.
"""
import logging
from collections import OrderedDict
from datetime import date

from flask import Blueprint, jsonify, render_template, request
from flask_login import current_user, login_required

from utils.db import get_db_connection
from utils.decorators import admin_required
from utils import contabil_transf as ct

logger = logging.getLogger(__name__)

bp = Blueprint('migracao_contabil', __name__, url_prefix='/lancamentos/migracao-contabil')


def _usuario():
    return (getattr(current_user, 'username', None) or getattr(current_user, 'nome', None) or '?')[:80]


def _contas_da_empresa(cur, empresa_id):
    cur.execute("""SELECT pc.id, pc.codigo, pc.nome, pc.tipo_grupo FROM clientes c
                     JOIN plano_contas_contas pc ON pc.grupo_id = c.grupo_contabil_id
                    WHERE c.id = %s AND pc.ativo = 1 ORDER BY pc.codigo""", (empresa_id,))
    return cur.fetchall()


@bp.route('/')
@login_required
@admin_required
def index():
    try:
        ano = int(request.args.get('ano') or date.today().year)
    except ValueError:
        ano = date.today().year
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        ct.ensure_tables(cur)
        cur.execute("SELECT id, COALESCE(NULLIF(TRIM(nome_fantasia),''), razao_social) AS nome FROM clientes "
                    "WHERE id IN (SELECT cliente_id FROM bank_accounts)")
        nomes = {r['id']: r['nome'] for r in cur.fetchall()}
        regras, exc = ct.mapas(cur)
        ls = ct.linhas(cur, date(ano, 1, 1), date(ano, 12, 31))

        grupos = OrderedDict()
        sem_origem = []
        for l in ls:
            l['valor'] = float(l['valor'] or 0)
            l['excecao'] = exc.get(l['id'])
            if not l['contraparte_id']:
                sem_origem.append(l)
                continue
            k = (l['empresa_id'], l['contraparte_id'], l['sentido'])
            g = grupos.get(k)
            if not g:
                g = grupos[k] = {'empresa_id': k[0], 'contraparte_id': k[1], 'sentido': k[2],
                                 'empresa': nomes.get(k[0], k[0]), 'contraparte': nomes.get(k[1], k[1]),
                                 'regra': regras.get(k), 'linhas': [], 'total': 0.0, 'n_exc': 0}
            g['linhas'].append(l)
            g['total'] += l['valor']
            g['n_exc'] += 1 if l['excecao'] else 0
        lista = sorted(grupos.values(), key=lambda g: (str(g['empresa']), g['sentido'], -g['total']))
        sem_origem.sort(key=lambda l: (l['empresa_id'], l['data_transacao']))
        for l in sem_origem:
            l['empresa'] = nomes.get(l['empresa_id'], l['empresa_id'])

        empresas = sorted({g['empresa_id'] for g in lista} | {l['empresa_id'] for l in sem_origem})
        contas = {e: _contas_da_empresa(cur, e) for e in empresas}

        # vínculos antigos (Gerenciar contas > coligadas), só para mostrar
        antigos = {}
        try:
            cur.execute("""SELECT ba.cliente_id empresa, bac.coligada_cliente_id outra, ba.apelido,
                                  pd.codigo dc, pd.nome dn, pc.codigo cc, pc.nome cn
                             FROM bank_account_coligadas bac JOIN bank_accounts ba ON ba.id = bac.bank_account_id
                        LEFT JOIN plano_contas_contas pd ON pd.id = bac.conta_debito_id
                        LEFT JOIN plano_contas_contas pc ON pc.id = bac.conta_credito_id""")
            for r in cur.fetchall():
                txt = f"{r['apelido']}: débito {r['dc'] or '—'} {r['dn'] or ''} · crédito {r['cc'] or '—'} {r['cn'] or ''}"
                antigos.setdefault((r['empresa'], r['outra']), []).append(txt)
                antigos.setdefault((r['outra'], r['empresa']), []).append(txt)
        except Exception:
            logger.warning('migracao_contabil: coligadas', exc_info=True)
        for g in lista:
            g['antigos'] = antigos.get((g['empresa_id'], g['contraparte_id']), [])

        resumo = {'grupos': len(lista), 'sem_regra': sum(1 for g in lista if not g['regra']),
                  'sem_origem': len(sem_origem),
                  'sem_origem_ok': sum(1 for l in sem_origem if l['excecao'])}
        anos = list(range(date.today().year, 2024, -1))
        return render_template('migracao_contabil/index.html', grupos=lista, sem_origem=sem_origem,
                               contas=contas, nomes=nomes, ano=ano, anos=anos, resumo=resumo)
    finally:
        cur.close()
        conn.close()


def _conta_valida(cur, empresa_id, conta_id):
    cur.execute("""SELECT pc.id FROM clientes c JOIN plano_contas_contas pc ON pc.grupo_id = c.grupo_contabil_id
                    WHERE c.id = %s AND pc.id = %s""", (empresa_id, conta_id))
    return bool(cur.fetchone())


@bp.route('/regra', methods=['POST'])
@login_required
@admin_required
def salvar_regra():
    d = request.get_json(silent=True) or {}
    try:
        emp, outra, conta = int(d['empresa_id']), int(d['contraparte_id']), int(d['conta_id'])
        sentido = d['sentido']
        assert sentido in ('envia', 'recebe')
    except Exception:
        return jsonify(ok=False, erro='dados inválidos'), 400
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        ct.ensure_tables(cur)
        if not _conta_valida(cur, emp, conta):
            return jsonify(ok=False, erro='essa conta não é do plano desta empresa'), 400
        cur.execute("""INSERT INTO contabil_transf_regras (cliente_id, contraparte_cliente_id, sentido, conta_contabil_id, atualizado_por)
                       VALUES (%s,%s,%s,%s,%s)
                       ON DUPLICATE KEY UPDATE conta_contabil_id = VALUES(conta_contabil_id), atualizado_por = VALUES(atualizado_por)""",
                    (emp, outra, sentido, conta, _usuario()))
        conn.commit()
        cur.execute("SELECT codigo, nome FROM plano_contas_contas WHERE id = %s", (conta,))
        return jsonify(ok=True, conta=cur.fetchone())
    finally:
        cur.close()
        conn.close()


@bp.route('/excecao', methods=['POST'])
@login_required
@admin_required
def salvar_excecao():
    d = request.get_json(silent=True) or {}
    try:
        bt_id = int(d['bt_id'])
        conta = int(d['conta_id']) if d.get('conta_id') else None
    except Exception:
        return jsonify(ok=False, erro='dados inválidos'), 400
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        ct.ensure_tables(cur)
        if conta is None:
            cur.execute("DELETE FROM contabil_transf_excecoes WHERE bank_transaction_id = %s", (bt_id,))
            conn.commit()
            return jsonify(ok=True, conta=None)
        cur.execute("SELECT ba.cliente_id FROM bank_transactions bt JOIN bank_accounts ba ON ba.id = bt.account_id "
                    "WHERE bt.id = %s AND bt.tipo_conciliacao = 'transferencia'", (bt_id,))
        r = cur.fetchone()
        if not r:
            return jsonify(ok=False, erro='lançamento não é transferência'), 400
        if not _conta_valida(cur, r['cliente_id'], conta):
            return jsonify(ok=False, erro='essa conta não é do plano desta empresa'), 400
        cur.execute("""INSERT INTO contabil_transf_excecoes (bank_transaction_id, conta_contabil_id, atualizado_por)
                       VALUES (%s,%s,%s)
                       ON DUPLICATE KEY UPDATE conta_contabil_id = VALUES(conta_contabil_id), atualizado_por = VALUES(atualizado_por)""",
                    (bt_id, conta, _usuario()))
        conn.commit()
        cur.execute("SELECT codigo, nome FROM plano_contas_contas WHERE id = %s", (conta,))
        return jsonify(ok=True, conta=cur.fetchone())
    finally:
        cur.close()
        conn.close()
