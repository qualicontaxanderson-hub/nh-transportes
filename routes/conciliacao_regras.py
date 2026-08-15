"""CRUD de regras de conciliação automática (bank_conciliacao_regras)."""

import logging
import pytz
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from utils.db import get_db_connection
from utils.conciliacao import reverter_varias
from utils.navegacao import destino_pos_acao

_BRASILIA = pytz.timezone('America/Sao_Paulo')

logger = logging.getLogger(__name__)

bp = Blueprint('conciliacao_regras', __name__, url_prefix='/banco/regras')

_bsm_descricao_chave_ready = False


def _ensure_descricao_chave():
    """Garante que bank_supplier_mapping.descricao_chave existe. Idempotente."""
    global _bsm_descricao_chave_ready
    if _bsm_descricao_chave_ready:
        return
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM information_schema.COLUMNS"
            " WHERE TABLE_SCHEMA = DATABASE()"
            " AND TABLE_NAME = 'bank_supplier_mapping'"
            " AND COLUMN_NAME = 'descricao_chave'"
        )
        col_exists = cursor.fetchone()[0] > 0
        if not col_exists:
            cursor.execute(
                "ALTER TABLE bank_supplier_mapping"
                " ADD COLUMN descricao_chave VARCHAR(100) NOT NULL DEFAULT ''"
                " COMMENT 'Prefixo normalizado da descrição para diferenciar entradas com mesmo CNPJ'"
            )
            try:
                cursor.execute("ALTER TABLE bank_supplier_mapping DROP INDEX uq_bsm_chave")
            except Exception:
                pass
            try:
                cursor.execute(
                    "ALTER TABLE bank_supplier_mapping"
                    " ADD UNIQUE KEY uq_bsm_chave (cnpj_cpf, descricao_chave)"
                )
            except Exception:
                pass
            try:
                cursor.execute("DROP TRIGGER IF EXISTS tr_learn_supplier_mapping")
            except Exception:
                pass
            conn.commit()
            logger.info("_ensure_descricao_chave (conciliacao_regras): coluna e índice criados")
        cursor.close()
        _bsm_descricao_chave_ready = True
    except Exception:
        logger.warning("_ensure_descricao_chave (conciliacao_regras): falhou", exc_info=True)
    finally:
        if conn:
            conn.close()


def _get_formas(cursor):
    cursor.execute("SELECT id, nome FROM formas_recebimento WHERE ativo=1 ORDER BY nome")
    return cursor.fetchall()


def _get_fornecedores(cursor):
    cursor.execute("SELECT id, razao_social FROM fornecedores ORDER BY razao_social")
    return cursor.fetchall()


def _get_clientes(cursor):
    cursor.execute(
        """SELECT DISTINCT c.id, c.razao_social
           FROM clientes c
           INNER JOIN cliente_produtos cp ON c.id = cp.cliente_id
           WHERE cp.ativo = 1
           ORDER BY c.razao_social"""
    )
    return cursor.fetchall()


def _get_titulos_simples(cursor):
    """Retorna lista simples de títulos (sem JSON embutido — evita bug de aspas duplas)."""
    cursor.execute(
        "SELECT id, nome FROM titulos_despesas WHERE ativo=1 ORDER BY ordem, nome"
    )
    return cursor.fetchall()


def _get_contas(cursor):
    """Retorna contas bancárias ativas para o select de conta corrente."""
    cursor.execute(
        """SELECT ba.id, CONCAT(ba.banco_nome, ' - ', ba.apelido,
                  ' [', IFNULL(c.razao_social,''), ']') AS label
           FROM bank_accounts ba
           LEFT JOIN clientes c ON c.id = ba.cliente_id
           WHERE ba.ativo = 1
           ORDER BY ba.banco_nome, ba.apelido"""
    )
    return cursor.fetchall()


@bp.route('/')
@login_required
def lista():
    """Lista as regras de conciliação.

    O filtro é o mesmo passo a passo das outras telas do Banco, e por isso
    vive todo na URL: empresa, banco, busca no padrão, tipo de transação e
    para onde a regra manda. Ativas x desativadas viraram aba — antes era
    uma coluna que, na visão padrão, dizia "Ativa" em todas as linhas.
    """
    mostrar_inativos = request.args.get('inativos', '0') == '1'
    filtro_banco     = request.args.get('banco', '').strip()
    filtro_empresa   = request.args.get('empresa', '').strip()
    filtro_q         = request.args.get('q', '').strip()
    filtro_tipo      = request.args.get('tipo', '').strip().upper()
    filtro_destino   = request.args.get('destino', '').strip()

    if filtro_tipo not in ('CREDIT', 'DEBIT', 'AMBOS'):
        filtro_tipo = ''

    # Cada destino é uma coluna de vínculo; "nenhum" é a regra que casa com a
    # transação e não faz nada com ela — o caso que interessa achar.
    _DESTINOS = {
        'forma':      'r.forma_recebimento_id IS NOT NULL',
        'cliente':    'r.cliente_id IS NOT NULL',
        'fornecedor': 'r.fornecedor_id IS NOT NULL',
        'despesa':    'r.titulo_id IS NOT NULL',
        'nenhum':     ('r.forma_recebimento_id IS NULL AND r.cliente_id IS NULL'
                       ' AND r.fornecedor_id IS NULL AND r.titulo_id IS NULL'),
    }
    if filtro_destino not in _DESTINOS:
        filtro_destino = ''

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Tudo menos o ativo/inativo: as duas abas contam sob o MESMO filtro, senão
    # o número da aba vizinha mente.
    where, params = [], []
    # A regra sem conta vale para TODAS as contas, então ela pertence a
    # qualquer empresa e a qualquer banco: filtrar por igualdade a escondia
    # justamente onde ela também age.
    if filtro_banco:
        where.append("(ba.banco_nome = %s OR r.account_id IS NULL)")
        params.append(filtro_banco)
    if filtro_empresa:
        where.append("(ba.cliente_id = %s OR r.account_id IS NULL)")
        params.append(filtro_empresa)
    if filtro_q:
        where.append("(r.padrao_descricao LIKE %s OR r.padrao_secundario LIKE %s)")
        params += ['%' + filtro_q + '%'] * 2
    if filtro_tipo:
        where.append("r.tipo_transacao = %s")
        params.append(filtro_tipo)
    if filtro_destino:
        where.append('(' + _DESTINOS[filtro_destino] + ')')

    where_comum = ("WHERE " + " AND ".join(where)) if where else ""
    de_para = """FROM bank_conciliacao_regras r
                 LEFT JOIN bank_accounts ba ON ba.id = r.account_id"""

    cursor.execute(
        f"""SELECT SUM(r.ativo = 1) AS ativas, SUM(r.ativo = 0) AS inativas
            {de_para} {where_comum}""",
        params or None,
    )
    tot = cursor.fetchone() or {}
    n_ativas   = int(tot.get('ativas') or 0)
    n_inativas = int(tot.get('inativas') or 0)

    where_lista = where + ["r.ativo = %s"]
    params_lista = params + [0 if mostrar_inativos else 1]

    cursor.execute(
        f"""SELECT r.*,
                  fr.nome AS forma_nome,
                  f.razao_social AS fornecedor_nome,
                  c.razao_social AS cliente_nome,
                  td.nome AS titulo_nome,
                  cd.nome AS categoria_nome,
                  ba.banco_nome AS conta_banco,
                  ba.apelido AS conta_apelido
           FROM bank_conciliacao_regras r
           LEFT JOIN formas_recebimento fr ON fr.id = r.forma_recebimento_id
           LEFT JOIN fornecedores f ON f.id = r.fornecedor_id
           LEFT JOIN clientes c ON c.id = r.cliente_id
           LEFT JOIN titulos_despesas td ON td.id = r.titulo_id
           LEFT JOIN categorias_despesas cd ON cd.id = r.categoria_id
           LEFT JOIN bank_accounts ba ON ba.id = r.account_id
           WHERE {" AND ".join(where_lista)}
           ORDER BY r.total_aplicacoes DESC, r.padrao_descricao""",
        params_lista,
    )
    regras = cursor.fetchall()

    # Opções dos passos do filtro
    cursor.execute(
        "SELECT DISTINCT banco_nome FROM bank_accounts WHERE ativo=1 ORDER BY banco_nome"
    )
    bancos = [row['banco_nome'] for row in cursor.fetchall()]

    cursor.execute(
        """SELECT DISTINCT cl.id, cl.razao_social
           FROM clientes cl
           INNER JOIN bank_accounts ba ON ba.cliente_id = cl.id
           WHERE ba.ativo = 1
           ORDER BY cl.razao_social"""
    )
    empresas = cursor.fetchall()

    cursor.close()
    conn.close()
    return render_template(
        'bank_import/regras/lista.html',
        regras=regras,
        bancos=bancos,
        empresas=empresas,
        mostrar_inativos=mostrar_inativos,
        filtro_banco=filtro_banco,
        filtro_empresa=filtro_empresa,
        filtro_q=filtro_q,
        filtro_tipo=filtro_tipo,
        filtro_destino=filtro_destino,
        n_ativas=n_ativas,
        n_inativas=n_inativas,
    )


@bp.route('/novo', methods=['GET', 'POST'])
@login_required
def novo():
    """Cria nova regra de conciliação."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    if request.method == 'POST':
        padrao           = request.form.get('padrao_descricao', '').strip()
        padrao2          = request.form.get('padrao_secundario', '').strip() or None
        tipo_match       = request.form.get('tipo_match', 'contem')
        tipo_transacao   = request.form.get('tipo_transacao', 'AMBOS')
        forma_id         = request.form.get('forma_recebimento_id') or None
        fornecedor_id    = request.form.get('fornecedor_id') or None
        cliente_id       = request.form.get('cliente_id') or None
        titulo_id        = request.form.get('titulo_id') or None
        categoria_id     = request.form.get('categoria_id') or None
        subcategoria_id  = request.form.get('subcategoria_id') or None
        account_id       = request.form.get('account_id') or None

        if not padrao:
            flash('Padrão de descrição é obrigatório.', 'warning')
        else:
            cursor.execute(
                """INSERT INTO bank_conciliacao_regras
                   (padrao_descricao, padrao_secundario, tipo_match, tipo_transacao,
                    forma_recebimento_id, fornecedor_id, cliente_id, titulo_id,
                    categoria_id, subcategoria_id, account_id)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (padrao, padrao2, tipo_match, tipo_transacao,
                 forma_id, fornecedor_id, cliente_id, titulo_id,
                 categoria_id, subcategoria_id, account_id),
            )
            conn.commit()
            flash('Regra criada com sucesso!', 'success')
            cursor.close()
            conn.close()
            return redirect(url_for('conciliacao_regras.lista'))

    formas       = _get_formas(cursor)
    fornecedores = _get_fornecedores(cursor)
    clientes     = _get_clientes(cursor)
    titulos      = _get_titulos_simples(cursor)
    contas       = _get_contas(cursor)
    cursor.close()
    conn.close()
    return render_template('bank_import/regras/form.html',
                           regra=None, formas=formas,
                           fornecedores=fornecedores, clientes=clientes,
                           titulos=titulos, contas=contas, acao='Criar')


@bp.route('/<int:regra_id>/editar', methods=['GET', 'POST'])
@login_required
def editar(regra_id):
    """Edita regra existente."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM bank_conciliacao_regras WHERE id=%s", (regra_id,))
    regra = cursor.fetchone()
    if not regra:
        flash('Regra não encontrada.', 'warning')
        cursor.close()
        conn.close()
        return redirect(url_for('conciliacao_regras.lista'))

    if request.method == 'POST':
        padrao         = request.form.get('padrao_descricao', '').strip()
        padrao2        = request.form.get('padrao_secundario', '').strip() or None
        tipo_match     = request.form.get('tipo_match', 'contem')
        tipo_transacao = request.form.get('tipo_transacao', 'AMBOS')
        forma_id       = request.form.get('forma_recebimento_id') or None
        fornecedor_id  = request.form.get('fornecedor_id') or None
        cliente_id     = request.form.get('cliente_id') or None
        titulo_id      = request.form.get('titulo_id') or None
        categoria_id   = request.form.get('categoria_id') or None
        subcategoria_id = request.form.get('subcategoria_id') or None
        account_id     = request.form.get('account_id') or None

        if not padrao:
            flash('Padrão de descrição é obrigatório.', 'warning')
        else:
            cursor.execute(
                """UPDATE bank_conciliacao_regras
                   SET padrao_descricao=%s, padrao_secundario=%s, tipo_match=%s,
                       tipo_transacao=%s, forma_recebimento_id=%s, fornecedor_id=%s,
                       cliente_id=%s, titulo_id=%s, categoria_id=%s, subcategoria_id=%s,
                       account_id=%s
                   WHERE id=%s""",
                (padrao, padrao2, tipo_match, tipo_transacao,
                 forma_id, fornecedor_id, cliente_id, titulo_id,
                 categoria_id, subcategoria_id, account_id, regra_id),
            )
            conn.commit()
            flash('Regra atualizada!', 'success')
            cursor.close()
            conn.close()
            return redirect(url_for('conciliacao_regras.lista'))

    formas       = _get_formas(cursor)
    fornecedores = _get_fornecedores(cursor)
    clientes     = _get_clientes(cursor)
    titulos      = _get_titulos_simples(cursor)
    contas       = _get_contas(cursor)
    cursor.close()
    conn.close()
    return render_template('bank_import/regras/form.html',
                           regra=regra, formas=formas,
                           fornecedores=fornecedores, clientes=clientes,
                           titulos=titulos, contas=contas, acao='Salvar')


@bp.route('/<int:regra_id>/toggle', methods=['POST'])
@login_required
def toggle(regra_id):
    """Ativa ou desativa uma regra."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT ativo FROM bank_conciliacao_regras WHERE id=%s", (regra_id,))
    r = cursor.fetchone()
    if r:
        novo_status = 0 if r['ativo'] else 1
        cursor.execute("UPDATE bank_conciliacao_regras SET ativo=%s WHERE id=%s",
                       (novo_status, regra_id))
        conn.commit()
        flash('Regra ' + ('ativada' if novo_status else 'desativada') + '.', 'info')
    cursor.close()
    conn.close()
    return redirect(destino_pos_acao() or url_for('conciliacao_regras.lista'))


@bp.route('/<int:regra_id>/excluir', methods=['POST'])
@login_required
def excluir(regra_id):
    """Exclui uma regra; se já aplicada, apenas desativa."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT total_aplicacoes FROM bank_conciliacao_regras WHERE id=%s", (regra_id,))
    r = cursor.fetchone()
    if r:
        if r['total_aplicacoes'] > 0:
            cursor.execute("UPDATE bank_conciliacao_regras SET ativo=0 WHERE id=%s", (regra_id,))
            conn.commit()
            flash(f'Regra já foi aplicada {r["total_aplicacoes"]} vez(es) — foi desativada.', 'info')
        else:
            cursor.execute("DELETE FROM bank_conciliacao_regras WHERE id=%s", (regra_id,))
            conn.commit()
            flash('Regra excluída.', 'success')
    cursor.close()
    conn.close()
    return redirect(destino_pos_acao() or url_for('conciliacao_regras.lista'))


@bp.route('/excluir-lote', methods=['POST'])
@login_required
def excluir_lote():
    """Exclui em lote as regras selecionadas; regras já aplicadas são apenas desativadas."""
    ids_raw = request.form.getlist('regra_ids')
    ids = [int(i) for i in ids_raw if i.isdigit()]
    if not ids:
        flash('Nenhuma regra selecionada.', 'warning')
        return redirect(destino_pos_acao() or url_for('conciliacao_regras.lista'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # ids validated as integers above; f-string only builds %s placeholders, values stay parameterized
    ph = ','.join(['%s'] * len(ids))
    cursor.execute(
        f"SELECT id, total_aplicacoes FROM bank_conciliacao_regras WHERE id IN ({ph})",
        ids,
    )
    rows = cursor.fetchall()

    excluir_ids  = [r['id'] for r in rows if r['total_aplicacoes'] == 0]
    desativar_ids = [r['id'] for r in rows if r['total_aplicacoes'] > 0]

    if excluir_ids:
        ph2 = ','.join(['%s'] * len(excluir_ids))
        cursor.execute(f"DELETE FROM bank_conciliacao_regras WHERE id IN ({ph2})", excluir_ids)
    if desativar_ids:
        ph3 = ','.join(['%s'] * len(desativar_ids))
        cursor.execute(
            f"UPDATE bank_conciliacao_regras SET ativo=0 WHERE id IN ({ph3})",
            desativar_ids,
        )

    conn.commit()
    cursor.close()
    conn.close()

    partes = []
    if excluir_ids:
        partes.append(f'{len(excluir_ids)} regra(s) excluída(s)')
    if desativar_ids:
        partes.append(f'{len(desativar_ids)} regra(s) já aplicada(s) foram desativadas')
    flash('; '.join(partes) + '.', 'success')
    return redirect(destino_pos_acao() or url_for('conciliacao_regras.lista'))


# Quantas memorizações por página. São mais de 17 mil no banco: a tela antiga
# desenhava todas de uma vez, o que dava um HTML de dezenas de MB no celular.
_MEM_POR_PAGINA = 50

# Colunas que a busca varre. Ficam aqui porque a lista precisa casar com o que
# a tela promete no campo de busca.
_MEM_BUSCA = (
    "bsm.cnpj_cpf", "bsm.descricao_chave", "f.razao_social", "fr.nome",
    "td.nome", "cd.nome", "ba.apelido", "ba.banco_nome", "bsm.tipo_debito",
)

# O de/para completo. Precisa ser idêntico na contagem e na listagem, senão o
# total da paginação não bate com o que aparece.
_MEM_DE_PARA = """
    FROM bank_supplier_mapping bsm
    LEFT JOIN fornecedores f ON f.id = bsm.fornecedor_id
    LEFT JOIN formas_recebimento fr ON fr.id = bsm.forma_recebimento_id
    LEFT JOIN titulos_despesas td ON td.id = bsm.titulo_id
    LEFT JOIN categorias_despesas cd ON cd.id = bsm.categoria_id
    LEFT JOIN bank_accounts ba ON ba.id = bsm.conta_destino_id
"""


@bp.route('/memorias')
@login_required
def memorias():
    """Lista as memorizações de conciliação (bank_supplier_mapping).

    Busca, ordenação e paginação são feitas no banco. A versão anterior trazia
    a tabela inteira para a memória, convertia o fuso de cada linha e filtrava
    em Python — com 17 mil registros isso custava caro dos dois lados.
    """
    _ensure_descricao_chave()

    filtro_q = (request.args.get('q') or '').strip()
    filtro_tipo = (request.args.get('tipo') or '').strip()
    filtro_destino = (request.args.get('destino') or '').strip()
    ordem = (request.args.get('ordem') or 'uso').strip()
    try:
        pagina = max(1, int(request.args.get('pagina') or 1))
    except ValueError:
        pagina = 1

    if filtro_tipo not in ('cnpj', 'texto'):
        filtro_tipo = ''

    _DESTINOS = {
        'forma':         "bsm.forma_recebimento_id IS NOT NULL",
        'fornecedor':    "bsm.fornecedor_id IS NOT NULL",
        'despesa':       "bsm.titulo_id IS NOT NULL",
        'transferencia': "bsm.conta_destino_id IS NOT NULL",
        'nenhum':        ("bsm.forma_recebimento_id IS NULL AND bsm.fornecedor_id IS NULL"
                          " AND bsm.titulo_id IS NULL AND bsm.conta_destino_id IS NULL"),
    }
    if filtro_destino not in _DESTINOS:
        filtro_destino = ''

    _ORDENS = {
        'uso':     "bsm.total_conciliacoes DESC, bsm.id DESC",
        'recente': "bsm.atualizado_em DESC, bsm.id DESC",
        'parada':  "bsm.total_conciliacoes ASC, bsm.atualizado_em ASC",
    }
    if ordem not in _ORDENS:
        ordem = 'uso'

    where, params = [], []
    if filtro_q:
        where.append("(" + " OR ".join(c + " LIKE %s" for c in _MEM_BUSCA) + ")")
        params += ['%' + filtro_q + '%'] * len(_MEM_BUSCA)
    if filtro_tipo:
        where.append("bsm.tipo_chave = %s")
        params.append(filtro_tipo)
    if filtro_destino:
        where.append("(" + _DESTINOS[filtro_destino] + ")")
    clausula = ("WHERE " + " AND ".join(where)) if where else ""

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    memorias_list, total, resumo = [], 0, {}
    try:
        cursor.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(bsm.total_conciliacoes),0) AS usos"
            + _MEM_DE_PARA + clausula,
            params or None,
        )
        linha = cursor.fetchone() or {}
        total = int(linha.get('n') or 0)
        resumo['usos'] = int(linha.get('usos') or 0)

        # Números do topo: sempre do conjunto inteiro, não da página.
        cursor.execute(
            "SELECT SUM(tipo_chave='cnpj') AS por_cnpj, SUM(tipo_chave='texto') AS por_texto,"
            " SUM(total_conciliacoes = 0 OR total_conciliacoes IS NULL) AS paradas"
            " FROM bank_supplier_mapping"
        )
        geral = cursor.fetchone() or {}
        resumo['por_cnpj'] = int(geral.get('por_cnpj') or 0)
        resumo['por_texto'] = int(geral.get('por_texto') or 0)
        resumo['paradas'] = int(geral.get('paradas') or 0)

        paginas = max(1, -(-total // _MEM_POR_PAGINA))
        pagina = min(pagina, paginas)
        cursor.execute(
            "SELECT bsm.id, bsm.cnpj_cpf, bsm.descricao_chave, bsm.tipo_chave,"
            " bsm.total_conciliacoes, bsm.criado_em, bsm.atualizado_em,"
            " bsm.tipo_debito,"
            " f.razao_social AS fornecedor_nome, fr.nome AS forma_nome,"
            " td.nome AS titulo_nome, cd.nome AS categoria_nome,"
            " ba.apelido AS conta_destino_apelido, ba.banco_nome AS conta_destino_banco"
            + _MEM_DE_PARA + clausula
            + " ORDER BY " + _ORDENS[ordem]
            + " LIMIT %s OFFSET %s",
            params + [_MEM_POR_PAGINA, (pagina - 1) * _MEM_POR_PAGINA],
        )
        memorias_list = cursor.fetchall()
    except Exception:
        logger.exception("Erro ao carregar memorizações de conciliação")
        memorias_list, total, paginas = [], 0, 1
    finally:
        cursor.close()
        conn.close()

    # UTC → Brasília. Agora só nas 50 linhas da página.
    for m in memorias_list:
        for campo in ('atualizado_em', 'criado_em'):
            val = m.get(campo)
            if val is not None:
                try:
                    utc_dt = pytz.utc.localize(val) if val.tzinfo is None else val
                    m[campo] = utc_dt.astimezone(_BRASILIA)
                except Exception:
                    pass

    paginas = max(1, -(-total // _MEM_POR_PAGINA))
    return render_template(
        'bank_import/regras/memorias.html',
        memorias=memorias_list,
        filtro_q=filtro_q,
        filtro_tipo=filtro_tipo,
        filtro_destino=filtro_destino,
        ordem=ordem,
        pagina=min(pagina, paginas),
        paginas=paginas,
        total=total,
        por_pagina=_MEM_POR_PAGINA,
        resumo=resumo,
    )


# Quais lançamentos uma memorização fechou.
#
# O sistema NÃO guarda essa ligação: nenhuma coluna diz "esta conciliação veio
# daquela memorização". Então o alcance é redescoberto aplicando o MESMO
# casamento do auto-conciliar (routes/bank_import.py, api_auto_reconcile).
#
# Duas restrições que evitam estrago:
#
#  - só o que a MÁQUINA fechou (conciliado_por começa com 'auto'). O que uma
#    pessoa conciliou na mão não foi decisão da memorização, e desfazer isso
#    seria apagar trabalho humano.
#  - só CNPJ preenchido, porque é assim que o casamento acontece de verdade.
#
# Mesmo assim o alcance pode surpreender: memorização com descrição-chave
# vazia pega QUALQUER descrição daquele CNPJ. Uma que diz ter feito 46
# conciliações alcança 447 lançamentos. Por isso a tela mostra o número e o
# valor ANTES de confirmar — a conta é aproximada, e quem decide é quem lê.
_SQL_ALCANCE = """
    FROM bank_transactions bt
    JOIN bank_supplier_mapping bsm ON bsm.id IN ({ph})
    WHERE bt.status = 'conciliado'
      AND bt.conciliado_por LIKE 'auto%%'
      AND bt.cnpj_cpf IS NOT NULL AND bt.cnpj_cpf <> ''
      AND bt.cnpj_cpf = bsm.cnpj_cpf
      AND bsm.descricao_chave IN ('', LEFT(UPPER(TRIM(bt.descricao)), 100))
"""


def _ids_validos(brutos):
    """Inteiros positivos, sem repetição e na ordem em que vieram."""
    ids, vistos = [], set()
    for bruto in brutos:
        try:
            n = int(bruto)
        except (TypeError, ValueError):
            continue
        if n > 0 and n not in vistos:
            ids.append(n)
            vistos.add(n)
    return ids


def _alcance(cursor, memoria_ids):
    """(quantidade, valor, [tx_ids]) que a reversão tocaria."""
    if not memoria_ids:
        return 0, 0.0, []
    ph = ','.join(['%s'] * len(memoria_ids))
    cursor.execute(
        "SELECT DISTINCT bt.id, bt.valor" + _SQL_ALCANCE.format(ph=ph),
        memoria_ids,
    )
    linhas = cursor.fetchall()
    total = sum(float(l['valor'] or 0) for l in linhas)
    return len(linhas), total, [l['id'] for l in linhas]


@bp.route('/memorias/alcance')
@login_required
def memorias_alcance():
    """Quanto a reversão tocaria, para a tela avisar ANTES de executar."""
    ids = _ids_validos((request.args.get('ids') or '').split(','))
    if not ids:
        return jsonify({'quantos': 0, 'valor': 0, 'contador': 0, 'memorias': 0})

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        quantos, valor, _ = _alcance(cursor, ids)
        ph = ','.join(['%s'] * len(ids))
        cursor.execute(
            "SELECT COALESCE(SUM(total_conciliacoes),0) AS c"
            " FROM bank_supplier_mapping WHERE id IN (" + ph + ")",
            ids,
        )
        contador = int((cursor.fetchone() or {}).get('c') or 0)
    except Exception:
        logger.exception("Erro ao calcular o alcance da reversão")
        return jsonify({'erro': 'Não deu para calcular o alcance.'}), 500
    finally:
        cursor.close()
        conn.close()

    return jsonify({'quantos': quantos, 'valor': valor,
                    'contador': contador, 'memorias': len(ids)})


def _esquecer(memoria_ids, reverter):
    """Apaga as memorizações e, se pedido, reabre o que elas fecharam.

    A ordem importa: os lançamentos são descobertos ANTES de apagar, porque o
    alcance depende da memorização existir.
    """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    tx_ids = []
    try:
        if reverter:
            _, _, tx_ids = _alcance(cursor, memoria_ids)
        ph = ','.join(['%s'] * len(memoria_ids))
        cursor.execute("DELETE FROM bank_supplier_mapping WHERE id IN (" + ph + ")",
                       memoria_ids)
        apagadas = cursor.rowcount
        conn.commit()
    except Exception as e:
        conn.rollback()
        cursor.close()
        conn.close()
        flash('Erro ao excluir: %s' % e, 'danger')
        return

    cursor.close()
    if not reverter:
        conn.close()
        flash('%d memorização(ões) esquecida(s). Os lançamentos já conciliados'
              ' ficaram como estavam.' % apagadas, 'success')
        return

    try:
        revertidos, erros = reverter_varias(conn, tx_ids, logger)
    except Exception as e:
        logger.exception("Erro ao reverter conciliações da memorização")
        flash('Memorizações excluídas, mas a reversão falhou: %s' % e, 'danger')
        return
    finally:
        conn.close()

    flash('%d memorização(ões) esquecida(s) e %d lançamento(s) reaberto(s).'
          % (apagadas, revertidos), 'success')
    if erros:
        flash('Não deu para reabrir %d: %s' % (len(erros), '; '.join(erros[:5])), 'warning')


@bp.route('/memorias/<int:memoria_id>/excluir', methods=['POST'])
@login_required
def excluir_memoria(memoria_id):
    """Esquece uma memorização. Com reverter=1, reabre também o que ela fechou."""
    _esquecer([memoria_id], (request.form.get('reverter') or '') == '1')
    return redirect(destino_pos_acao() or url_for('conciliacao_regras.memorias'))


@bp.route('/memorias/excluir-lote', methods=['POST'])
@login_required
def excluir_memorias_lote():
    """Esquece várias memorizações. Com reverter=1, reabre também o que fecharam."""
    memoria_ids = _ids_validos(request.form.getlist('memoria_ids[]'))
    if not memoria_ids:
        flash('Nenhuma memorização selecionada.', 'warning')
        return redirect(destino_pos_acao() or url_for('conciliacao_regras.memorias'))
    _esquecer(memoria_ids, (request.form.get('reverter') or '') == '1')
    return redirect(destino_pos_acao() or url_for('conciliacao_regras.memorias'))


@login_required
def api_criar_subcategoria():
    """Cria uma subcategoria inline durante o preenchimento da regra (AJAX)."""
    data = request.get_json(silent=True) or {}
    categoria_id = data.get('categoria_id')
    nome = (data.get('nome') or '').strip()
    if not categoria_id or not nome:
        return jsonify({'ok': False, 'msg': 'categoria_id e nome são obrigatórios'}), 400
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "INSERT INTO subcategorias_despesas (categoria_id, nome, ativo) VALUES (%s,%s,1)",
            (categoria_id, nome),
        )
        conn.commit()
        novo_id = cursor.lastrowid
        return jsonify({'ok': True, 'id': novo_id, 'nome': nome})
    except Exception as e:
        return jsonify({'ok': False, 'msg': str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@bp.route('/api/categorias/<int:titulo_id>')
@login_required
def api_categorias(titulo_id):
    """Retorna categorias de um título com subcategorias aninhadas."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT id, nome FROM categorias_despesas WHERE titulo_id=%s AND ativo=1 ORDER BY ordem, nome",
        (titulo_id,),
    )
    cats = cursor.fetchall()
    # Buscar subcategorias para cada categoria
    for cat in cats:
        try:
            cursor.execute(
                "SELECT id, nome FROM subcategorias_despesas WHERE categoria_id=%s AND ativo=1 ORDER BY nome",
                (cat['id'],),
            )
            cat['subcategorias'] = cursor.fetchall()
        except Exception:
            cat['subcategorias'] = []
    cursor.close()
    conn.close()
    return jsonify(cats)
