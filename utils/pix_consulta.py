"""
PIX Consulta — o frentista (e o Admin) confirma que um PIX caiu no banco e
recebe um comprovante com PROTOCOLO, em vez de pedir no grupo a toda hora.

A base é o extrato que já entra sozinho (bank_transactions, Sicoob NH), sem
mudar nada nele. O que o extrato não guarda fica numa tabela À PARTE,
anotada a cada leitura da API do Sicoob (integrations/extrato_scheduler):

  * pix_recebido_info — o nome INTEIRO e o CPF/CNPJ parcial de quem pagou
    (o extrato grava o nome cortado em 32, como o OFX, e sem o documento), e
    QUANDO o sistema viu o PIX pela primeira vez. A API de conta corrente não
    dá a hora do PIX: o que se sabe de verdade é que ele não estava na leitura
    anterior e estava nesta -- "entre 10:40 e 10:50".
  * pix_consulta_leitura — o momento da última leitura, por conta.
  * pix_consulta_protocolos — um protocolo por PIX (aleatório, não
    sequencial), com quem consultou. O mesmo PIX nunca ganha dois.

PIX lido antes de 29/10/2026 não tem a anotação: aparece com o nome do
extrato (cortado), sem documento e sem hora.
"""
import logging
import re
import secrets
import unicodedata
from datetime import timedelta

from utils.fuso import agora_brasilia

logger = logging.getLogger(__name__)

ACCOUNT_ID = 10             # SICOOB - NH: a chave PIX do posto
CONTA_ROTULO = 'Sicoob · NH GTBA'
# o CNPJ que o cupom grava quando o PIX é liquidado pelo Sicoob
CREDENCIADORA = '02038232000164'
# Os créditos que são PIX recebido no extrato do Sicoob: PIX de outro banco e
# a transferência de outra cooperativa Sicoob (sai do app como PIX).
_FILTRO_PIX = "(bt.memo LIKE 'PIX RECEBIDO%%' OR bt.memo LIKE 'CRED.TRANSF%%')"
# Sem as letras/números que se confundem (O/0, I/1)
_ALFABETO = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'

_DDL = (
    """
    CREATE TABLE IF NOT EXISTS pix_recebido_info (
        id                  INT AUTO_INCREMENT PRIMARY KEY,
        account_id          INT          NOT NULL,
        api_id              VARCHAR(80)  NOT NULL,
        bank_transaction_id INT          NULL,
        data_banco          DATE         NOT NULL,
        valor               DECIMAL(15,2) NOT NULL,
        nome                VARCHAR(160) NULL,
        doc                 VARCHAR(30)  NULL,
        texto               VARCHAR(300) NULL COMMENT 'o complemento cru da API',
        hora_banco          CHAR(5)      NULL COMMENT 'se um dia a API mandar a hora',
        visto_em            DATETIME     NULL COMMENT 'Brasilia; NULL = ja estava antes da 1a leitura',
        leitura_anterior    DATETIME     NULL,
        UNIQUE KEY uq_conta_api (account_id, api_id),
        KEY ix_bt (bank_transaction_id),
        KEY ix_visto (account_id, visto_em)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS pix_consulta_leitura (
        account_id INT PRIMARY KEY,
        ultima     DATETIME NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS pix_consulta_protocolos (
        id                  INT AUTO_INCREMENT PRIMARY KEY,
        protocolo           CHAR(12)     NOT NULL,
        bank_transaction_id INT          NOT NULL,
        usuario_id          INT          NULL,
        usuario_nome        VARCHAR(120) NULL,
        frentista           VARCHAR(80)  NULL,
        origem              VARCHAR(10)  NOT NULL COMMENT 'admin | pista',
        criado_em           DATETIME     NOT NULL,
        reenvios            INT          NOT NULL DEFAULT 0,
        ultimo_reenvio      DATETIME     NULL,
        UNIQUE KEY uq_protocolo (protocolo),
        UNIQUE KEY uq_bt (bank_transaction_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
)

_tabelas_ok = False


def garantir_tabelas(cur):
    """Uma vez por processo: DDL no MySQL faz COMMIT implícito -- chamar
    sempre ANTES de abrir uma gravação, nunca no meio dela."""
    global _tabelas_ok
    if _tabelas_ok:
        return
    for ddl in _DDL:
        cur.execute(ddl)
    _tabelas_ok = True


# ── anotação, a cada leitura do Sicoob ───────────────────────────────────────
_ROTULOS = ('TRANSFERENCIA PIX', 'RECEBIMENTO PIX')


def _nome_da_api(t):
    """O nome de quem pagou. Na transferência de outra cooperativa Sicoob o
    complemento vem 'REM.: CLEYTON JOSE DOS SANTOS|@Transferência Pix|@CLEYTON
    JOSE DOS SANTOS|@***.903.681-**|@' e o 'quem' do adapter pega o rótulo
    "Transferência Pix" -- o nome é o do REM. (29/10/2026)."""
    nome = (t.get('quem') or '').strip()
    if not nome or _sem_acento(nome) in _ROTULOS:
        from integrations.sicoob_extrato import _parece_documento, partes_complemento
        partes = partes_complemento(t.get('memo'))
        cands = [re.sub(r'^REM\.?:\s*', '', p, flags=re.I).strip() for p in partes]
        nome = next((c for c in cands if c and _sem_acento(c) not in _ROTULOS
                     and not _parece_documento(c)), nome)
    return re.sub(r'^REM\.?:\s*', '', nome, flags=re.I)[:160] or None


def anotar(conn, account_id, api_txs):
    """Guarda nome inteiro, documento e o momento em que cada PIX recebido
    apareceu. api_txs: a saída de sicoob_extrato.ler() (com 'id_banco').
    Roda DEPOIS de extrato_grava.sincronizar, para achar o lançamento."""
    cur = conn.cursor()
    try:
        garantir_tabelas(cur)
        agora = agora_brasilia()
        cur.execute("SELECT ultima FROM pix_consulta_leitura WHERE account_id=%s", (account_id,))
        row = cur.fetchone()
        anterior = row[0] if row else None
        txs = [t for t in api_txs if t.get('id_banco') and t.get('tipo') == 'CREDIT'
               and re.match(r'(PIX RECEBIDO|CRED\.TRANSF)', (t.get('descricao') or '').upper())]
        novos = 0
        if txs:
            ids = [t['id_banco'] for t in txs]
            ph = ','.join(['%s'] * len(ids))
            cur.execute(f"SELECT api_id FROM pix_recebido_info WHERE account_id=%s AND api_id IN ({ph})",
                        [account_id] + ids)
            ja = {r[0] for r in cur.fetchall()}
            cur.execute(f"""SELECT api_id, bank_transaction_id FROM bank_api_ids
                             WHERE account_id=%s AND api_id IN ({ph})""", [account_id] + ids)
            bt = dict(cur.fetchall())
            for t in txs:
                if t['id_banco'] in ja:
                    continue
                # Na 1a leitura de todas, tudo o que veio ja estava no banco
                # antes: a hora de quando foi visto seria mentira.
                visto = agora if anterior else None
                cur.execute("""
                    INSERT IGNORE INTO pix_recebido_info
                        (account_id, api_id, bank_transaction_id, data_banco, valor, nome, doc,
                         texto, hora_banco, visto_em, leitura_anterior)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (account_id, t['id_banco'], bt.get(t['id_banco']), t['data_transacao'],
                     t['valor'], _nome_da_api(t), (t.get('doc_pessoa') or '')[:30] or None,
                     (t.get('memo') or '')[:300] or None, t.get('hora'), visto,
                     anterior if visto else None))
                novos += cur.rowcount
        cur.execute("""INSERT INTO pix_consulta_leitura (account_id, ultima) VALUES (%s, %s)
                       ON DUPLICATE KEY UPDATE ultima=VALUES(ultima)""", (account_id, agora))
        conn.commit()
        return novos
    finally:
        cur.close()


# ── busca ────────────────────────────────────────────────────────────────────
def _sem_acento(s):
    s = unicodedata.normalize('NFD', str(s or ''))
    return ''.join(c for c in s if unicodedata.category(c) != 'Mn').upper()


def _digitos(s):
    return re.sub(r'\D', '', str(s or ''))


def _nome_do_extrato(descricao):
    n = re.sub(r'^(Recebimento Pix|REM\.?:)\s*', '', (descricao or '').strip(), flags=re.I)
    return n.strip()


def casa(pix, quem):
    """CPF/CNPJ como aparece no comprovante do cliente (***.903.681-**,
    903.681, 903681) ou qualquer nome dele, em qualquer ordem."""
    quem = (quem or '').strip()
    if not quem:
        return True
    dig = _digitos(quem)
    if len(dig) >= 4 and re.fullmatch(r'[\d.\-/\s*]+', quem):
        return dig in _digitos(pix['doc'])
    palavras = re.split(r'[^A-Z0-9]+', _sem_acento(pix['nome']))
    return all(any(p.startswith(w) for p in palavras)
               for w in _sem_acento(quem).split() if w)


def _hora(dt):
    return dt.strftime('%H:%M') if dt else None


def _com_vendedor(pixs, dia):
    """O vendedor do cupom fiscal que cada PIX pagou -- o mesmo casamento do
    Extrato On-Line (integrations/extrato_cupom: Extrato Pix, nome na
    autorização, valor no dia, ordem do banco). Só leitura, em memória. Tem
    de ser o DIA INTEIRO: um PIX que tem dois cupons de mesmo valor só se
    resolve quando os vizinhos já casaram."""
    for p in pixs:
        p.update(vendedor=None, cupom=None, cupom_hora=None, possiveis=[])
    if not pixs:
        return
    try:
        from integrations.extrato_cupom import casar
        txs = [{'valor': p['valor'], 'data_transacao': dia, 'dias': [dia],
                'quem': p['nome'], 'hora': p.get('_hora_banco')} for p in pixs]
        casa, _ = casar(txs, dia, dia, CREDENCIADORA)
        for p, tx in zip(pixs, txs):
            r = casa.get(id(tx)) or {}
            c = r.get('cupom')
            if c:
                p.update(vendedor=c.get('vendedor') or None, cupom=c.get('numero'),
                         cupom_hora=c['dh_emissao'].strftime('%H:%M'))
            elif r.get('status') == 'possiveis':
                p['possiveis'] = sorted({c.get('vendedor') or '?' for c in r.get('candidatos') or []})
    except Exception:
        # o vendedor é complemento: sem ele, a consulta segue
        logger.exception('[pix_consulta] casamento PIX x cupom falhou')


def buscar(conn, dia, valor=None, quem=None):
    """Os PIX recebidos no DIA (o dia em que o sistema viu; sem anotação, o do
    extrato), com o vendedor do cupom, filtrados por valor exato e por
    nome/documento."""
    pixs = _do_dia(conn, dia)
    _com_vendedor(pixs, dia)
    return [p for p in pixs
            if (valor is None or abs(p['valor'] - valor) < 0.005) and casa(p, quem)]


def _do_dia(conn, dia):
    cur = conn.cursor(dictionary=True)
    try:
        garantir_tabelas(cur)
        # O Sicoob lança o PIX do fim de semana com a data de segunda: a
        # janela do extrato vai alguns dias para a frente.
        params = [ACCOUNT_ID, dia - timedelta(days=1), dia + timedelta(days=4)]
        cur.execute(f"""
            SELECT bt.id, bt.data_transacao, bt.valor, bt.descricao,
                   i.nome, i.doc, i.hora_banco, i.visto_em, i.leitura_anterior,
                   p.protocolo, p.usuario_nome, p.frentista, p.criado_em AS consultado_em,
                   p.origem, p.reenvios
              FROM bank_transactions bt
              LEFT JOIN pix_recebido_info i
                     ON i.id = (SELECT MIN(i2.id) FROM pix_recebido_info i2
                                 WHERE i2.bank_transaction_id = bt.id)
              LEFT JOIN pix_consulta_protocolos p ON p.bank_transaction_id = bt.id
             WHERE bt.account_id = %s AND bt.tipo = 'CREDIT' AND {_FILTRO_PIX}
               AND bt.data_transacao BETWEEN %s AND %s
             ORDER BY COALESCE(i.visto_em, bt.data_transacao), bt.id""", params)
        return [_formatar(r) for r in cur.fetchall()
                if (r['visto_em'].date() if r['visto_em'] else r['data_transacao']) == dia]
    finally:
        cur.close()


def _formatar(r):
    if r.get('hora_banco'):
        hora = 'às ' + r['hora_banco']
    elif r.get('visto_em') and r.get('leitura_anterior'):
        hora = 'entre %s e %s' % (_hora(r['leitura_anterior']), _hora(r['visto_em']))
    elif r.get('visto_em'):
        hora = 'até ' + _hora(r['visto_em'])
    else:
        hora = ''
    dia = r['visto_em'].date() if r.get('visto_em') else r['data_transacao']
    return {
        'id': r['id'],
        'valor': float(r['valor']),
        'nome': r.get('nome') or _nome_do_extrato(r.get('descricao')),
        'doc': r.get('doc') or '',
        'dia': dia.strftime('%d/%m/%Y'),
        'hora': hora,
        'conta': CONTA_ROTULO,
        'protocolo': r.get('protocolo'),
        'consultado_por': r.get('frentista') or r.get('usuario_nome'),
        'consultado_em': r['consultado_em'].strftime('%d/%m/%Y %H:%M') if r.get('consultado_em') else None,
        'origem': r.get('origem'),
        'reenvios': r.get('reenvios') or 0,
        '_hora_banco': r.get('hora_banco'),
        '_dia': dia,
    }


def um(conn, bt_id=None, protocolo=None):
    """Um PIX pelo id do extrato ou pelo protocolo (para reenviar)."""
    cur = conn.cursor(dictionary=True)
    try:
        garantir_tabelas(cur)
        cond, arg = ('bt.id = %s', bt_id) if bt_id else ('p.protocolo = %s', protocolo)
        cur.execute(f"""
            SELECT bt.id, bt.data_transacao, bt.valor, bt.descricao,
                   i.nome, i.doc, i.hora_banco, i.visto_em, i.leitura_anterior,
                   p.protocolo, p.usuario_nome, p.frentista, p.criado_em AS consultado_em,
                   p.origem, p.reenvios
              FROM bank_transactions bt
              LEFT JOIN pix_recebido_info i
                     ON i.id = (SELECT MIN(i2.id) FROM pix_recebido_info i2
                                 WHERE i2.bank_transaction_id = bt.id)
              LEFT JOIN pix_consulta_protocolos p ON p.bank_transaction_id = bt.id
             WHERE {cond} AND bt.account_id = %s AND bt.tipo = 'CREDIT' AND {_FILTRO_PIX}""",
            (arg, ACCOUNT_ID))
        r = cur.fetchone()
    finally:
        cur.close()
    if not r:
        return None
    pix = _formatar(r)
    # o vendedor sai do casamento do dia inteiro (ver _com_vendedor)
    dia = next((p for p in buscar(conn, pix['_dia']) if p['id'] == pix['id']), None)
    return dia or pix


# ── protocolo ────────────────────────────────────────────────────────────────
def _novo_protocolo():
    s = ''.join(secrets.choice(_ALFABETO) for _ in range(8))
    return 'NH-%s-%s' % (s[:4], s[4:])


def emitir(conn, bt_id, usuario_id, usuario_nome, origem='admin', frentista=None):
    """O protocolo do PIX: cria na 1a vez; depois devolve o MESMO e conta o
    reenvio. Devolve (pix, novo: bool) ou (None, False) se não é PIX recebido."""
    if not um(conn, bt_id=bt_id):
        return None, False
    cur = conn.cursor()
    try:
        agora = agora_brasilia()
        novo = False
        for _ in range(5):
            try:
                cur.execute("""
                    INSERT INTO pix_consulta_protocolos
                        (protocolo, bank_transaction_id, usuario_id, usuario_nome, frentista,
                         origem, criado_em)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                    (_novo_protocolo(), bt_id, usuario_id, (usuario_nome or '')[:120],
                     (frentista or '')[:80] or None, origem, agora))
                novo = True
                break
            except Exception as exc:
                msg = str(exc)
                if 'uq_bt' in msg:          # o PIX já tem protocolo: é reenvio
                    cur.execute("""UPDATE pix_consulta_protocolos
                                      SET reenvios = reenvios + 1, ultimo_reenvio = %s
                                    WHERE bank_transaction_id = %s""", (agora, bt_id))
                    break
                if 'uq_protocolo' not in msg:
                    raise
                # protocolo repetido (raríssimo): sorteia outro
        conn.commit()
    finally:
        cur.close()
    return um(conn, bt_id=bt_id), novo


def de_hoje(conn, dia):
    """As consultas (protocolos) emitidas no dia, mais nova primeiro."""
    cur = conn.cursor(dictionary=True)
    try:
        garantir_tabelas(cur)
        cur.execute("""SELECT bank_transaction_id FROM pix_consulta_protocolos
                        WHERE criado_em >= %s AND criado_em < %s
                        ORDER BY criado_em DESC""", (dia, dia + timedelta(days=1)))
        ids = [r['bank_transaction_id'] for r in cur.fetchall()]
    finally:
        cur.close()
    return [p for p in (um(conn, bt_id=i) for i in ids) if p]
