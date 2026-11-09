"""Migração Contábil das transferências entre EMPRESAS (pedido 08/11/2026).

No financeiro o grupo é um só: dinheiro que vai da NH para a Prest é
"transferência" e as duas pontas ficam ligadas (sem duplicar). No contábil
cada empresa tem o seu livro, e a mesma operação tem que aparecer nos DOIS:
  NH envia para Prest  -> na NH, débito na conta escolhida (ex.: Serviços PJ)
  Prest recebe da NH   -> na Prest, crédito na conta escolhida (ex.: Serviços)

Regra = empresa (dona do livro) + contraparte + sentido -> conta contábil.
Exceção = um lançamento só, com outra conta (ou o "sem origem" que o usuário
classifica um por um). Exceção vence a regra; sem as duas, o exportar segue
a lógica antiga.

Transferência entre contas da MESMA empresa não entra aqui (continua saindo
só pela saída, como sempre).
"""
import logging

logger = logging.getLogger(__name__)

QUALICONTAX = 53          # extrato dela não vem para cá (usuário, 08/11/2026): não tem livro aqui
ESPELHO = "(bt.hash_dedup LIKE 'TRANSFER%%' AND COALESCE(bt.fitid,'') = '')"

_ok = False


def ensure_tables(cursor):
    """CREATE TABLE faz commit implícito no MySQL: chamar antes de qualquer transação."""
    global _ok
    if _ok:
        return
    cursor.execute("""CREATE TABLE IF NOT EXISTS contabil_transf_regras (
        id INT AUTO_INCREMENT PRIMARY KEY,
        cliente_id INT NOT NULL COMMENT 'empresa dona do livro',
        contraparte_cliente_id INT NOT NULL,
        sentido VARCHAR(10) NOT NULL COMMENT 'envia | recebe',
        conta_contabil_id INT NOT NULL,
        atualizado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        atualizado_por VARCHAR(80) NULL,
        UNIQUE KEY uq_ctr (cliente_id, contraparte_cliente_id, sentido))""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS contabil_transf_excecoes (
        bank_transaction_id INT NOT NULL PRIMARY KEY,
        conta_contabil_id INT NOT NULL,
        atualizado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        atualizado_por VARCHAR(80) NULL)""")
    _ok = True


# Uma linha por lançamento entre empresas, já com empresa (livro), contraparte e sentido.
# contraparte NULL = não se sabe de onde veio / para onde foi ("sem origem").
_SQL_LINHAS = """
SELECT * FROM (
  SELECT bt.id, bt.data_transacao, bt.valor, bt.descricao, bt.account_id, ba.apelido AS conta,
         ba.cliente_id AS empresa_id, 'envia' AS sentido,
         bd.cliente_id AS contraparte_id, bd.apelido AS conta_outra
    FROM bank_transactions bt
    JOIN bank_accounts ba ON ba.id = bt.account_id
    LEFT JOIN bank_transactions mir ON mir.hash_dedup = CONCAT('TRANSFER_', bt.id)
    LEFT JOIN bank_accounts bd ON bd.id = COALESCE(bt.conta_destino_id, mir.account_id)
   WHERE bt.tipo = 'DEBIT' AND bt.status = 'conciliado' AND bt.tipo_conciliacao = 'transferencia'
     AND (bd.id IS NULL OR bd.cliente_id <> ba.cliente_id)
  UNION ALL
  SELECT bt.id, bt.data_transacao, bt.valor, bt.descricao, bt.account_id, ba.apelido,
         ba.cliente_id, 'recebe',
         bo.cliente_id, bo.apelido
    FROM bank_transactions bt
    JOIN bank_accounts ba ON ba.id = bt.account_id
    LEFT JOIN bank_accounts bo ON bo.id = bt.conta_origem_id
   WHERE bt.tipo = 'CREDIT' AND bt.status = 'conciliado' AND bt.tipo_conciliacao = 'transferencia'
     AND NOT """ + ESPELHO + """
     AND (bo.id IS NULL OR bo.cliente_id <> ba.cliente_id)
) x
WHERE x.empresa_id <> %s AND x.data_transacao BETWEEN %s AND %s
"""


def linhas(cursor, ini, fim, empresa_id=None):
    sql = _SQL_LINHAS
    params = [QUALICONTAX, ini, fim]
    if empresa_id:
        sql += " AND x.empresa_id = %s"
        params.append(empresa_id)
    cursor.execute(sql + " ORDER BY x.data_transacao, x.id", params)
    return cursor.fetchall()


def mapas(cursor):
    """(regras, excecoes): {(empresa, contraparte, sentido): conta}, {bt_id: conta}; conta = dict id/codigo/nome."""
    ensure_tables(cursor)
    cursor.execute("""SELECT r.cliente_id, r.contraparte_cliente_id, r.sentido, pc.id, pc.codigo, pc.nome
                        FROM contabil_transf_regras r JOIN plano_contas_contas pc ON pc.id = r.conta_contabil_id""")
    regras = {(r['cliente_id'], r['contraparte_cliente_id'], r['sentido']):
              {'id': r['id'], 'codigo': r['codigo'], 'nome': r['nome']} for r in cursor.fetchall()}
    cursor.execute("""SELECT e.bank_transaction_id, pc.id, pc.codigo, pc.nome
                        FROM contabil_transf_excecoes e JOIN plano_contas_contas pc ON pc.id = e.conta_contabil_id""")
    exc = {r['bank_transaction_id']: {'id': r['id'], 'codigo': r['codigo'], 'nome': r['nome']}
           for r in cursor.fetchall()}
    return regras, exc


def conta_da_linha(regras, exc, bt_id, empresa_id, contraparte_id, sentido):
    """A conta contábil do lado da empresa: exceção > regra > None."""
    if bt_id in exc:
        return exc[bt_id]
    if contraparte_id:
        return regras.get((empresa_id, contraparte_id, sentido))
    return None


def para_exportar(cursor, row, regras, exc):
    """Para o exportar_contabil: devolve ('debito'|'credito', codigo, nome) quando a linha
    é entre empresas e já tem conta escolhida; senão None (segue a lógica antiga)."""
    if 'transferen' not in (row.get('tipo_conciliacao') or '').lower():
        return None
    emp = row.get('banco_cliente_id')
    if row.get('tipo') == 'DEBIT':
        outra, sentido, lado = row.get('destino_cliente_id'), 'envia', 'debito'
    else:
        outra, sentido, lado = row.get('origem_cliente_id'), 'recebe', 'credito'
    if outra and outra == emp:
        return None
    c = conta_da_linha(regras, exc, row['id'], emp, outra, sentido)
    if not c:
        return None
    return lado, c['codigo'], c['nome']
