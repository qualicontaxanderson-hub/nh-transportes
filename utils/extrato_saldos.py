"""Extrato bancário com saldo do dia (pedido 04/11/2026).

O saldo vem do PRÓPRIO BANCO: todo OFX traz <LEDGERBAL> (saldo ao fim do
período) e o Extrato On-Line traz o saldo da conta. Cada um é guardado em
bank_saldos (conta, dia, origem). O extrato parte do saldo do banco mais
próximo antes do período e soma os lançamentos dia a dia; em cada dia que o
banco informou o saldo, compara com a conta do sistema e mostra a diferença
— é ali que falta ou sobra lançamento.

Medido em 04/11/2026 sobre 351 OFX do Dropbox: saldo de um arquivo +
lançamentos = saldo do seguinte em 94 de 105 (Sicredi NH), 60/63 (Cora NH),
60/60 (Cora Prest), 39/40 (Fresh), 44/46 (Sicoob) — DESDE QUE os espelhos de
transferência fiquem de fora. Espelho é a linha CREDIT que o sistema cria
na conta de destino (hash 'TRANSFER...', sem FITID): não existe no banco.

Gravar o saldo nunca atrapalha a importação: conexão própria e qualquer erro
só vai para o log.
"""
import logging
import re
from datetime import date, datetime, timedelta

logger = logging.getLogger(__name__)

DDL = """
CREATE TABLE IF NOT EXISTS `bank_saldos` (
    `id`            INT AUTO_INCREMENT PRIMARY KEY,
    `account_id`    INT           NOT NULL,
    `data`          DATE          NOT NULL,
    `saldo`         DECIMAL(15,2) NOT NULL,
    `origem`        VARCHAR(10)   NOT NULL COMMENT 'ofx = LEDGERBAL do arquivo; api = Extrato On-Line',
    `arquivo`       VARCHAR(200)  NULL,
    `atualizado_em` DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY `uq_conta_dia_origem` (`account_id`, `data`, `origem`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

# Linha que o sistema cria e o banco não tem (espelho de transferência)
SEM_ESPELHO = "NOT (bt.hash_dedup LIKE 'TRANSFER%%' AND (bt.fitid IS NULL OR bt.fitid = ''))"
E_ESPELHO = "(bt.hash_dedup LIKE 'TRANSFER%%' AND (bt.fitid IS NULL OR bt.fitid = ''))"

_tabela_ok = False


def garantir_tabela(cursor):
    """Uma vez por processo (DDL faz COMMIT implícito no MySQL)."""
    global _tabela_ok
    if not _tabela_ok:
        cursor.execute(DDL)
        _tabela_ok = True


# ── gravar ──────────────────────────────────────────────────────────────────

def saldo_do_ofx(conteudo):
    """(data, saldo) do <LEDGERBAL> do OFX, ou None."""
    m = re.search(r'<LEDGERBAL>.*?<BALAMT>\s*([-+\d.,]+).*?<DTASOF>\s*(\d{8})',
                  conteudo or '', re.S | re.I)
    if not m:
        return None
    v = m.group(1)
    if ',' in v:
        v = v.replace('.', '').replace(',', '.')
    try:
        d = m.group(2)
        return date(int(d[:4]), int(d[4:6]), int(d[6:8])), round(float(v), 2)
    except Exception:
        return None


def guardar(account_id, dia, saldo, origem, arquivo=None):
    """Grava (ou atualiza) o saldo do banco naquele dia. Conexão própria."""
    from utils.db import get_db_connection
    conn = cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        garantir_tabela(cur)
        cur.execute(
            "INSERT INTO bank_saldos (account_id, data, saldo, origem, arquivo) "
            "VALUES (%s, %s, %s, %s, %s) "
            "ON DUPLICATE KEY UPDATE saldo = VALUES(saldo), arquivo = VALUES(arquivo)",
            (int(account_id), dia, saldo, origem, (arquivo or '')[:200] or None))
        conn.commit()
        return True
    except Exception:
        logger.exception('[extrato-saldos] guardar falhou (conta %s, %s)', account_id, dia)
        return False
    finally:
        for x in (cur, conn):
            try:
                x and x.close()
            except Exception:
                pass


def guardar_do_ofx(account_id, conteudo, arquivo=None):
    """Chamado depois de importar um OFX. Nunca levanta erro."""
    try:
        s = saldo_do_ofx(conteudo)
        if s and account_id:
            guardar(account_id, s[0], s[1], 'ofx', arquivo)
    except Exception:
        logger.exception('[extrato-saldos] saldo do OFX falhou')


def guardar_da_api(account_id, extrato):
    """Saldo que o Extrato On-Line trouxe ('agora' ou 'fim de dd/mm')."""
    try:
        saldo = getattr(extrato, 'saldo', None)
        if saldo is None or not account_id:
            return
        quando = str(getattr(extrato, 'saldo_quando', '') or '')
        from utils.fuso import hoje_brasilia
        dia = hoje_brasilia()
        m = re.search(r'(\d{2})/(\d{2})', quando)
        if m:
            d = date(dia.year, int(m.group(2)), int(m.group(1)))
            if d > dia:
                d = date(dia.year - 1, d.month, d.day)
            dia = d
        guardar(account_id, dia, round(float(saldo), 2), 'api', quando or 'agora')
    except Exception:
        logger.exception('[extrato-saldos] saldo da API falhou')


# ── montar o extrato ────────────────────────────────────────────────────────

ROTULO_TIPO = {
    'transferencia': 'Transferência',
    'deposito': 'Depósito',
    'troco_pix': 'Troco PIX',
    'devolucao_fornecedor': 'Devolução de fornecedor',
}


def _pontos(cursor, account_id):
    """{dia: (saldo, origem)} — o OFX manda sobre a API no mesmo dia."""
    cursor.execute("SELECT data, saldo, origem FROM bank_saldos WHERE account_id = %s",
                   (account_id,))
    pts = {}
    for r in cursor.fetchall():
        d = r['data']
        if d not in pts or r['origem'] == 'ofx':
            pts[d] = (float(r['saldo']), r['origem'])
    return pts


def _soma(cursor, account_id, de, ate):
    """Entradas - saídas de de..ate (inclusive), sem espelho."""
    if de > ate:
        return 0.0
    cursor.execute(
        "SELECT COALESCE(SUM(IF(bt.tipo = 'CREDIT', bt.valor, -bt.valor)), 0) s "
        "  FROM bank_transactions bt WHERE bt.account_id = %s "
        "   AND bt.data_transacao BETWEEN %s AND %s AND " + SEM_ESPELHO,
        (account_id, de, ate))
    return float(cursor.fetchone()['s'] or 0)


def montar(cursor, conta, ini, fim, origem='todos'):
    """Um bloco de extrato para a conta (dict de bank_accounts).

    origem: 'todos' | 'online' | 'ofx' — só escolhe QUAIS lançamentos
    aparecem; o saldo é sempre feito com todos.
    """
    garantir_tabela(cursor)
    aid = conta['id']
    pts = _pontos(cursor, aid)

    # saldo de partida: o ponto do banco mais próximo ANTES do período; sem
    # ele, o primeiro ponto dentro/depois (andando para trás)
    antes = [d for d in pts if d < ini]
    depois = [d for d in pts if d >= ini]
    if antes:
        a = max(antes)
        saldo = pts[a][0] + _soma(cursor, aid, a + timedelta(days=1), ini - timedelta(days=1))
        base = 'saldo do banco em %s' % a.strftime('%d/%m/%Y')
    elif depois:
        a = min(depois)
        saldo = pts[a][0] - _soma(cursor, aid, ini, a)
        base = 'calculado de trás para frente a partir de %s' % a.strftime('%d/%m/%Y')
    else:
        saldo = None
        base = 'o banco ainda não informou saldo desta conta'

    cursor.execute(
        """SELECT bt.id, bt.data_transacao, bt.tipo, bt.valor, bt.descricao, bt.status,
                  bt.tipo_conciliacao, bt.hash_dedup,
                  EXISTS (SELECT 1 FROM bank_api_ids x WHERE x.bank_transaction_id = bt.id) AS viu_api,
                  COALESCE(NULLIF(TRIM(fo.nome_fantasia), ''), fo.razao_social) AS fornecedor,
                  fr.nome AS forma,
                  bd.apelido AS conta_destino,
                  (SELECT GROUP_CONCAT(DISTINCT COALESCE(sc.nome, cd.nome) SEPARATOR ', ')
                     FROM lancamentos_despesas ld
                     LEFT JOIN categorias_despesas cd ON cd.id = ld.categoria_id
                     LEFT JOIN subcategorias_despesas sc ON sc.id = ld.subcategoria_id
                    WHERE ld.bank_transaction_id = bt.id) AS despesa
             FROM bank_transactions bt
             LEFT JOIN fornecedores fo ON fo.id = bt.fornecedor_id
             LEFT JOIN formas_recebimento fr ON fr.id = bt.forma_recebimento_id
             LEFT JOIN bank_accounts bd ON bd.id = COALESCE(bt.conta_destino_id, bt.conta_origem_id)
            WHERE bt.account_id = %s AND bt.data_transacao BETWEEN %s AND %s AND """ + SEM_ESPELHO + """
            ORDER BY bt.data_transacao, bt.id""",
        (aid, ini, fim))
    linhas = cursor.fetchall()

    cursor.execute("SELECT COUNT(*) n FROM bank_transactions bt WHERE bt.account_id = %s "
                   "AND bt.data_transacao BETWEEN %s AND %s AND " + E_ESPELHO, (aid, ini, fim))
    espelhos = int(cursor.fetchone()['n'] or 0)

    por_dia = {}
    for l in linhas:
        l['valor'] = float(l['valor'] or 0)
        l['online'] = bool(l['viu_api'])
        l['ofx'] = not str(l['hash_dedup'] or '').startswith('api:')
        l['classe'] = _classe(l)
        por_dia.setdefault(l['data_transacao'], []).append(l)

    dias_ver = sorted(set(por_dia) | {d for d in pts if ini <= d <= fim})
    dias = []
    tot = {'entradas': 0.0, 'saidas': 0.0, 'n': 0, 'pendentes': 0, 'divergencias': 0}
    for d in dias_ver:
        todas = por_dia.get(d, [])
        mov = sum(l['valor'] if l['tipo'] == 'CREDIT' else -l['valor'] for l in todas)
        s_ini = saldo
        s_fim = None if saldo is None else round(saldo + mov, 2)
        banco = pts.get(d)
        dif = None
        if banco is not None and s_fim is not None:
            dif = round(banco[0] - s_fim, 2)
            if abs(dif) < 0.01:
                dif = 0.0
        # dia sem lançamento e saldo batendo não precisa aparecer
        if not todas and not dif:
            saldo = banco[0] if banco else s_fim
            continue
        vis = [l for l in todas if origem == 'todos'
               or (origem == 'online' and l['online']) or (origem == 'ofx' and l['ofx'])]
        validas = [l for l in todas if l['status'] != 'ignorado']
        dia = {
            'data': d, 'saldo_ini': s_ini, 'saldo_fim': s_fim,
            'banco': banco[0] if banco else None, 'banco_origem': banco[1] if banco else None,
            'dif': dif, 'linhas': vis, 'n_total': len(todas),
            'entradas': sum(l['valor'] for l in todas if l['tipo'] == 'CREDIT'),
            'saidas': sum(l['valor'] for l in todas if l['tipo'] == 'DEBIT'),
            'pendentes': sum(1 for l in todas if l['status'] == 'pendente'),
            'conciliado': bool(validas) and all(l['status'] == 'conciliado' for l in validas),
        }
        dias.append(dia)
        tot['entradas'] += dia['entradas']
        tot['saidas'] += dia['saidas']
        tot['n'] += len(todas)
        tot['pendentes'] += dia['pendentes']
        if dif:
            tot['divergencias'] += 1
        # o dia seguinte parte do saldo do BANCO quando ele informou: a
        # diferença fica só no dia em que aconteceu
        saldo = banco[0] if banco else s_fim

    return {
        'conta': conta, 'dias': dias, 'base': base, 'espelhos': espelhos,
        'saldo_inicial': dias[0]['saldo_ini'] if dias else saldo,
        'saldo_final': saldo, 'tot': tot,
        'tem_online': any(l['online'] for l in linhas),
    }


def _classe(l):
    """Como o lançamento foi classificado na conciliação (texto curto)."""
    partes = []
    tc = l.get('tipo_conciliacao')
    if tc:
        t = ROTULO_TIPO.get(tc, tc.replace('_', ' ').capitalize())
        if tc == 'transferencia' and l.get('conta_destino'):
            t += (' para ' if l['tipo'] == 'DEBIT' else ' de ') + l['conta_destino']
        partes.append(t)
    if l.get('despesa'):
        partes.append(l['despesa'])
    if l.get('fornecedor'):
        partes.append(l['fornecedor'])
    if l.get('forma'):
        partes.append(l['forma'])
    return ' · '.join(partes)


def contas(cursor):
    cursor.execute(
        """SELECT ba.id, ba.banco_nome, ba.apelido, ba.agencia, ba.conta, ba.cliente_id,
                  COALESCE(NULLIF(TRIM(c.nome_fantasia), ''), c.razao_social) AS empresa
             FROM bank_accounts ba LEFT JOIN clientes c ON c.id = ba.cliente_id
            WHERE ba.ativo = 1 ORDER BY ba.apelido""")
    return cursor.fetchall()
