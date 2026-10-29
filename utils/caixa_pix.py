"""
PIX no Fechamento de Caixa (29/10/2026).

O campo "Recebimentos PIX" do fechamento era digitado pelo Melke a partir de
uma planilha do Sicoob. Medido em out/2026: o número dele é a SOMA DOS PIX
DO DIA nas contas do posto MENOS alguns que ele tira (transferência da mesma
titularidade, o PIX do Baratão...). Em 27/10 a lista abaixo, com as
sugestões, deu 89.519,57 -- o mesmo valor que ele digitou.

Aqui só se monta a lista e se guarda o que foi tirado, com o MOTIVO, e o
PIX lançado à mão (extrato que não chegou). O valor do campo continua
gravado em lancamentos_caixa_comprovacao como sempre; estas tabelas são o
porquê dele:

  caixa_pix_fechamento  um por fechamento: os totais e quem confirmou
  caixa_pix_fora        o PIX tirado do cálculo e o motivo
  caixa_pix_manual      o PIX lançado à mão; bank_transaction_id é
                        preenchido quando o extrato chega e o usuário junta
"""
import json
import logging
from datetime import datetime

from utils import pix_consulta
from utils.cartao_cupom import BARATAO_CNPJ

logger = logging.getLogger(__name__)

X7_CNPJ = '45179094000146'
# CNPJs do grupo (PIX entre contas/empresas do grupo não é venda)
CNPJS_GRUPO = ('33503987000116',)
_NOMES_GRUPO = ('POSTO NOVO HORIZONTE', 'PREST SERVICE', 'MESMA TIT')

# Crédito que é PIX (ou transferência) recebido, em qualquer banco:
#   Sicoob   'PIX RECEBIDO - OUTRA IF' / 'CRED.TRANSF.CONTAS INTERCREDIS' (memo)
#   Sicredi  'RECEBIMENTO PIX-PIX_CRED ...'
#   Cora     'Transf Pix recebida - ...' / 'Transferência recebida - ...'
#   Santander 'PIX RECEBIDO ...' / 'TRANSFERENCIA RECEBIDA - PAGAMENTO PIX...'
_FILTRO = """(bt.memo LIKE 'PIX RECEBIDO%%' OR bt.memo LIKE 'CRED.TRANSF%%'
              OR UPPER(bt.descricao) LIKE '%%PIX%%'
              OR bt.descricao LIKE 'Transf%%recebida%%')"""

_DDL = (
    """
    CREATE TABLE IF NOT EXISTS caixa_pix_fechamento (
        lancamento_caixa_id INT PRIMARY KEY,
        total_dia           DECIMAL(15,2) NOT NULL DEFAULT 0,
        total_fora          DECIMAL(15,2) NOT NULL DEFAULT 0,
        total_manual        DECIMAL(15,2) NOT NULL DEFAULT 0,
        total_usado         DECIMAL(15,2) NOT NULL DEFAULT 0,
        usuario_nome        VARCHAR(120) NULL,
        atualizado_em       DATETIME     NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS caixa_pix_fora (
        id                  INT AUTO_INCREMENT PRIMARY KEY,
        lancamento_caixa_id INT          NOT NULL,
        bank_transaction_id INT          NOT NULL,
        account_id          INT          NULL,
        valor               DECIMAL(15,2) NOT NULL,
        nome                VARCHAR(160) NULL,
        motivo              VARCHAR(255) NOT NULL,
        usuario_nome        VARCHAR(120) NULL,
        criado_em           DATETIME     NOT NULL,
        UNIQUE KEY uq_lc_bt (lancamento_caixa_id, bank_transaction_id),
        KEY ix_bt (bank_transaction_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS caixa_pix_manual (
        id                  INT AUTO_INCREMENT PRIMARY KEY,
        lancamento_caixa_id INT          NOT NULL,
        account_id          INT          NOT NULL,
        valor               DECIMAL(15,2) NOT NULL,
        nome                VARCHAR(160) NOT NULL,
        bank_transaction_id INT          NULL COMMENT 'o PIX do extrato com que foi juntado',
        usuario_nome        VARCHAR(120) NULL,
        criado_em           DATETIME     NOT NULL,
        KEY ix_lc (lancamento_caixa_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
)
_tabelas_ok = False


def garantir_tabelas(conn):
    """DDL faz COMMIT implícito: chamar ANTES de abrir a gravação do caixa."""
    global _tabelas_ok
    if _tabelas_ok:
        return
    cur = conn.cursor()
    try:
        for ddl in _DDL:
            cur.execute(ddl)
        _tabelas_ok = True
    finally:
        cur.close()


def sugestao(texto, nome=''):
    """O motivo sugerido para tirar o PIX do cálculo, ou None."""
    t = pix_consulta._sem_acento('%s %s' % (texto or '', nome or ''))
    if 'BARATAO' in t or BARATAO_CNPJ in t:
        return 'Pagamento do Baratão (entra na Conferência de Cartões)'
    if X7_CNPJ in t or 'X7 B' in t:
        return 'Pagamento do cartão X7 (entra na Conferência de Cartões)'
    if any(c in t for c in CNPJS_GRUPO) or any(n in t for n in _NOMES_GRUPO):
        return 'Transferência entre contas/empresas do grupo'
    return None


def contas_do_cliente(conn, cliente_id):
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("""SELECT id, apelido FROM bank_accounts
                        WHERE cliente_id = %s AND ativo = 1 ORDER BY id""", (cliente_id,))
        contas = cur.fetchall()
    finally:
        cur.close()
    # O Sicoob (a chave PIX do posto) primeiro: é onde está quase tudo
    return sorted(contas, key=lambda c: (c['id'] != pix_consulta.ACCOUNT_ID, c['id']))


def _nome(descricao):
    import re
    n = re.sub(r'^(Recebimento Pix|REM\.?:|RECEBIMENTO PIX-PIX_CRED\s+\d+|PIX RECEBIDO\s+\d*|'
               r'Transf(er[eê]ncia)?\s+(Pix\s+)?recebida\s*-|TRANSFERENCIA RECEBIDA\s*-)\s*',
               '', (descricao or '').strip(), flags=re.I)
    return n.strip() or (descricao or '').strip()


def pix_do_dia(conn, cliente_id, dia, lancamento_id=None):
    """A lista do dia para o fechamento: {contas, pix, fora, manuais, salvo}.

    fora: o que foi tirado (do fechamento salvo) ou, num fechamento novo, as
    sugestões. Num fechamento salvo ANTES desta tela (sem caixa_pix_fechamento)
    salvo=False: a tela não troca o valor digitado sem o usuário confirmar."""
    contas = contas_do_cliente(conn, cliente_id)
    if not contas:
        return {'contas': [], 'pix': [], 'fora': {}, 'manuais': [], 'salvo': False}
    ids = [c['id'] for c in contas]
    pix = []
    # Sicoob: o dia em que o PIX foi visto (o banco data o fim de semana na
    # segunda), nome inteiro, hora e o vendedor do cupom -- o PIX Consulta.
    if pix_consulta.ACCOUNT_ID in ids:
        for p in pix_consulta.buscar(conn, dia):
            pix.append({'id': p['id'], 'conta': pix_consulta.ACCOUNT_ID, 'valor': p['valor'],
                        'nome': p['nome'], 'doc': p['doc'],
                        'hora': p.get('cupom_hora') or (p['hora'] or '').replace('entre ', '').replace(' e ', '–'),
                        'vendedor': p.get('vendedor'), '_texto': p['nome']})
    outras = [i for i in ids if i != pix_consulta.ACCOUNT_ID]
    cur = conn.cursor(dictionary=True)
    try:
        if outras:
            ph = ','.join(['%s'] * len(outras))
            cur.execute(f"""
                SELECT bt.id, bt.account_id, bt.valor, bt.descricao, bt.memo
                  FROM bank_transactions bt
                 WHERE bt.account_id IN ({ph}) AND bt.tipo = 'CREDIT'
                   AND bt.data_transacao = %s AND {_FILTRO}
                 ORDER BY bt.account_id, bt.id""", outras + [dia])
            for r in cur.fetchall():
                pix.append({'id': r['id'], 'conta': r['account_id'], 'valor': float(r['valor']),
                            'nome': _nome(r['descricao']), 'doc': '', 'hora': '', 'vendedor': None,
                            '_texto': '%s %s' % (r['descricao'] or '', r['memo'] or '')})
        # o texto do extrato do Sicoob também entra na sugestão (MESMA TIT. fica no memo)
        sic = [p['id'] for p in pix if p['conta'] == pix_consulta.ACCOUNT_ID]
        if sic:
            ph = ','.join(['%s'] * len(sic))
            cur.execute(f"SELECT id, descricao, memo FROM bank_transactions WHERE id IN ({ph})", sic)
            txt = {r['id']: '%s %s' % (r['descricao'] or '', r['memo'] or '') for r in cur.fetchall()}
            for p in pix:
                if p['id'] in txt:
                    p['_texto'] += ' ' + txt[p['id']]

        salvo, fora, manuais = False, {}, []
        if lancamento_id:
            cur.execute("SELECT 1 FROM caixa_pix_fechamento WHERE lancamento_caixa_id = %s", (lancamento_id,))
            salvo = cur.fetchone() is not None
            if salvo:
                cur.execute("""SELECT bank_transaction_id, motivo FROM caixa_pix_fora
                                WHERE lancamento_caixa_id = %s""", (lancamento_id,))
                fora = {r['bank_transaction_id']: r['motivo'] for r in cur.fetchall()}
                cur.execute("""SELECT id, account_id, valor, nome, bank_transaction_id, usuario_nome
                                 FROM caixa_pix_manual WHERE lancamento_caixa_id = %s ORDER BY id""",
                            (lancamento_id,))
                manuais = [{'id': 'm%d' % r['id'], 'conta': r['account_id'], 'valor': float(r['valor']),
                            'nome': r['nome'], 'junto': r['bank_transaction_id'],
                            'usuario': r['usuario_nome']} for r in cur.fetchall()]
    finally:
        cur.close()
    if not salvo:
        for p in pix:
            s = sugestao(p['_texto'], p['nome'])
            if s:
                fora[p['id']] = s + ' (sugestão)'
    for p in pix:
        p.pop('_texto', None)
    return {'contas': contas, 'pix': pix, 'fora': fora, 'manuais': manuais, 'salvo': salvo}


def gravar(cursor, lancamento_id, detalhe_json, usuario_nome):
    """Grava o detalhe do PIX do fechamento, dentro da MESMA transação do
    caixa (cursor do caixa; o commit é dele). detalhe_json vazio = a tela não
    mexeu no PIX: nada muda. Devolve o total usado, ou None."""
    if not detalhe_json:
        return None
    d = json.loads(detalhe_json)
    agora = datetime.now()
    try:
        from utils.fuso import agora_brasilia
        agora = agora_brasilia()
    except Exception:
        pass
    cursor.execute("DELETE FROM caixa_pix_fora WHERE lancamento_caixa_id = %s", (lancamento_id,))
    cursor.execute("DELETE FROM caixa_pix_manual WHERE lancamento_caixa_id = %s", (lancamento_id,))
    for f in d.get('fora') or []:
        motivo = (f.get('motivo') or '').strip()
        if not motivo:
            raise ValueError('PIX tirado do cálculo sem o motivo')
        cursor.execute("""
            INSERT INTO caixa_pix_fora (lancamento_caixa_id, bank_transaction_id, account_id, valor,
                                        nome, motivo, usuario_nome, criado_em)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (lancamento_id, int(f['id']), f.get('conta'), float(f['valor']), (f.get('nome') or '')[:160],
             motivo[:255], (f.get('usuario') or usuario_nome or '')[:120], agora))
    for m in d.get('manuais') or []:
        cursor.execute("""
            INSERT INTO caixa_pix_manual (lancamento_caixa_id, account_id, valor, nome,
                                          bank_transaction_id, usuario_nome, criado_em)
            VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (lancamento_id, int(m['conta']), float(m['valor']), (m.get('nome') or '')[:160],
             int(m['junto']) if m.get('junto') else None,
             (m.get('usuario') or usuario_nome or '')[:120], agora))
    t = d.get('totais') or {}
    cursor.execute("""
        INSERT INTO caixa_pix_fechamento (lancamento_caixa_id, total_dia, total_fora, total_manual,
                                          total_usado, usuario_nome, atualizado_em)
        VALUES (%s,%s,%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE total_dia=VALUES(total_dia), total_fora=VALUES(total_fora),
            total_manual=VALUES(total_manual), total_usado=VALUES(total_usado),
            usuario_nome=VALUES(usuario_nome), atualizado_em=VALUES(atualizado_em)""",
        (lancamento_id, float(t.get('dia') or 0), float(t.get('fora') or 0),
         float(t.get('manual') or 0), float(t.get('usado') or 0), (usuario_nome or '')[:120], agora))
    return float(t.get('usado') or 0)


def apagar(cursor, lancamento_id):
    for tab in ('caixa_pix_fora', 'caixa_pix_manual', 'caixa_pix_fechamento'):
        try:
            cursor.execute(f"DELETE FROM {tab} WHERE lancamento_caixa_id = %s", (lancamento_id,))
        except Exception:
            pass                        # tabela ainda não existe
