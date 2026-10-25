"""
Extrato On-Line GRAVANDO — a API do banco lança no sistema, ao lado do OFX.

Decisão do usuário em 24/10/2026: as duas frentes valem. O que vier pela API
(na hora) é a PRIORIDADE; o OFX (dia seguinte) continua entrando. Quem chega
primeiro grava, o outro reconhece o mesmo lançamento e não duplica:

  * API depois do OFX: o lançamento da API casa com a linha que o OFX já
    gravou (mesmo dia, sentido e valor; o documento e o texto desempatam) e só
    se anota o par em bank_api_ids. Nada muda na linha.
  * API antes do OFX: a API grava pela MESMA rotina do OFX
    (bank_import._save_transactions: de-para por CNPJ, Troco PIX, regras,
    despesas, cobranças), com hash_dedup 'api:...' e o texto montado igual ao
    do OFX. Quando o OFX chegar, _save_transactions acha essa linha e, em vez
    de inserir outra, passa a ela o hash/FITID do OFX — e, se ainda estiver
    pendente, o texto do OFX, para as regras pegarem.

bank_api_ids guarda (conta, id do lançamento na API) -> bank_transactions.id:
é o que impede a API de gravar duas vezes o mesmo lançamento a cada leitura.
Um par apagado à mão continua anotado de propósito: a API não ressuscita um
lançamento que alguém removeu.

Cada lançamento precisa de um id estável ('id_banco'): o Cora dá o seu
('ent_...'); o Sicoob não dá, e sicoob_extrato.id_sintetico monta um.
"""
import hashlib
import logging
from collections import defaultdict

from integrations.banco_api import prefixo_comum

logger = logging.getLogger(__name__)

DDL = """
CREATE TABLE IF NOT EXISTS `bank_api_ids` (
    `id`                  INT AUTO_INCREMENT PRIMARY KEY,
    `account_id`          INT          NOT NULL,
    `api_id`              VARCHAR(80)  NOT NULL,
    `bank_transaction_id` INT          NOT NULL,
    `origem`              VARCHAR(10)  NOT NULL COMMENT 'api = a API gravou; ofx = casou com a linha do OFX',
    `criado_em`           DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY `uq_conta_api` (`account_id`, `api_id`),
    KEY `ix_bt` (`bank_transaction_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

PREFIXO_HASH = 'api:'


_tabela_ok = False


def garantir_tabela(cursor):
    """Uma vez por processo: DDL no MySQL faz COMMIT implícito."""
    global _tabela_ok
    if not _tabela_ok:
        cursor.execute(DDL)
        _tabela_ok = True


def hash_api(account_id, api_id):
    """64 caracteres, como o hash do OFX (coluna VARCHAR(64) UNIQUE)."""
    h = hashlib.sha256(f'{account_id}|{api_id}'.encode('utf-8')).hexdigest()
    return PREFIXO_HASH + h[:64 - len(PREFIXO_HASH)]


def _digitos(txt):
    return ''.join(c for c in str(txt or '') if c.isdigit())


def _chave(data_tx, tipo, valor):
    return (data_tx, tipo, f'{float(valor):.2f}')


def emparelhar(lado_a, lado_b, texto_a, texto_b, doc_a, doc_b):
    """Pares (a, b) com a mesma (data, tipo, valor). Dentro do grupo, o mesmo
    documento vem primeiro, depois o texto mais parecido. Devolve
    (pares, sobra_a)."""
    fila = defaultdict(list)
    for b in lado_b:
        fila[_chave(b['data_transacao'], b['tipo'], b['valor'])].append(b)
    grupos = defaultdict(list)
    for a in lado_a:
        grupos[_chave(a['data_transacao'], a['tipo'], a['valor'])].append(a)
    pares, sobra = [], []
    for k, as_ in grupos.items():
        bs = fila.get(k, [])
        notas = sorted((((doc_a(a) and doc_a(a) == doc_b(b)) or False,
                         prefixo_comum(texto_a(a), texto_b(b)), -i, -j)
                        for i, a in enumerate(as_) for j, b in enumerate(bs)), reverse=True)
        usa, usb = set(), set()
        for _d, _t, mi, mj in notas:
            i, j = -mi, -mj
            if i in usa or j in usb:
                continue
            usa.add(i)
            usb.add(j)
            pares.append((as_[i], bs[j]))
        sobra += [a for i, a in enumerate(as_) if i not in usa]
        fila[k] = [b for j, b in enumerate(bs) if j not in usb]
    return pares, sobra


def sincronizar(mod, api_txs, cursor, conn):
    """Grava no sistema o que a API trouxe e o sistema ainda não tem.

    mod: o adapter da conta (account_id, texto_como_ofx). api_txs: a saída de
    mod.ler() — com 'id_banco'. cursor: dictionary=True. Devolve
    {'novos', 'casados_ofx', 'ja_tinha'}.
    """
    conta = mod.account_id
    garantir_tabela(cursor)
    txs = [t for t in api_txs if t.get('id_banco')]
    r = {'novos': 0, 'casados_ofx': 0, 'ja_tinha': 0}
    if not txs:
        return r

    ids = [t['id_banco'] for t in txs]
    ph = ','.join(['%s'] * len(ids))
    cursor.execute(f"SELECT api_id FROM bank_api_ids WHERE account_id=%s AND api_id IN ({ph})",
                   [conta] + ids)
    anotados = {row['api_id'] for row in cursor.fetchall()}
    novos = [t for t in txs if t['id_banco'] not in anotados]
    r['ja_tinha'] = len(txs) - len(novos)
    if not novos:
        return r

    # 1. O que o OFX já gravou (e nenhum lançamento da API reivindicou)
    ini = min(t['data_transacao'] for t in novos)
    fim = max(t['data_transacao'] for t in novos)
    cursor.execute(
        """SELECT bt.id, bt.data_transacao, bt.tipo, bt.valor, bt.descricao, bt.cnpj_cpf
             FROM bank_transactions bt
            WHERE bt.account_id=%s AND bt.data_transacao BETWEEN %s AND %s
              AND NOT EXISTS (SELECT 1 FROM bank_api_ids x
                               WHERE x.account_id=bt.account_id AND x.bank_transaction_id=bt.id)""",
        (conta, ini, fim))
    livres = cursor.fetchall()
    pares, sobra = emparelhar(
        novos, livres, mod.texto_como_ofx, lambda b: b['descricao'],
        lambda a: _digitos(a.get('cnpj_cpf')), lambda b: _digitos(b.get('cnpj_cpf')))
    for a, b in pares:
        cursor.execute(
            "INSERT IGNORE INTO bank_api_ids (account_id, api_id, bank_transaction_id, origem) "
            "VALUES (%s, %s, %s, 'ofx')", (conta, a['id_banco'], b['id']))
    r['casados_ofx'] = len(pares)
    conn.commit()
    if not sobra:
        return r

    # 2. O resto entra pela rotina do OFX, com o texto do OFX
    from routes.bank_import import _save_transactions
    linhas = []
    como_ofx = getattr(mod, 'linha_como_ofx', None)
    for a in sobra:
        if como_ofx:                # Sicoob: NAME cortado, MEMO e CNPJ do texto
            linha = como_ofx(a)
        else:                       # Cora: o OFX repete o texto no MEMO
            texto = mod.texto_como_ofx(a)
            linha = {'descricao': texto, 'memo': texto,
                     'cnpj_cpf': _digitos(a.get('cnpj_cpf')) or None}
        linhas.append(dict(linha, fitid=a['id_banco'], tipo=a['tipo'],
                           data_transacao=a['data_transacao'], valor=a['valor'],
                           hash_dedup=hash_api(conta, a['id_banco'])))
    _save_transactions(cursor, conn, conta, linhas)
    hs = [l['hash_dedup'] for l in linhas]
    ph = ','.join(['%s'] * len(hs))
    cursor.execute(f"SELECT id, fitid FROM bank_transactions WHERE account_id=%s AND hash_dedup IN ({ph})",
                   [conta] + hs)
    for row in cursor.fetchall():
        cursor.execute(
            "INSERT IGNORE INTO bank_api_ids (account_id, api_id, bank_transaction_id, origem) "
            "VALUES (%s, %s, %s, 'api')", (conta, row['fitid'], row['id']))
        r['novos'] += 1
    conn.commit()
    logger.info('[extrato_grava] conta %s: %s', conta, r)
    return r


def ofx_reconhece_api(cursor, account_id, transactions, existing_hashes):
    """Chamado por bank_import._save_transactions ANTES de inserir: o OFX que
    chega depois da API não insere de novo — a linha da API recebe o hash e o
    FITID do OFX (e o texto, se ainda estiver pendente). Devolve
    {hash_do_ofx: id_da_linha} dos reconhecidos; o chamador os trata como
    duplicados. Conta sem linha da API: não faz nada."""
    # As linhas que a própria API está gravando (hash 'api:') não se reconhecem
    # entre si: dois PIX de mesmo valor no dia são dois lançamentos.
    candidatos = [t for t in transactions if t['hash_dedup'] not in existing_hashes
                  and not str(t['hash_dedup']).startswith(PREFIXO_HASH)]
    if not candidatos:
        return {}
    datas = sorted({t['data_transacao'] for t in candidatos})
    ph = ','.join(['%s'] * len(datas))
    cursor.execute(
        f"""SELECT id, data_transacao, tipo, valor, descricao, cnpj_cpf, status
              FROM bank_transactions
             WHERE account_id=%s AND hash_dedup LIKE 'api:%%' AND data_transacao IN ({ph})""",
        [account_id] + datas)
    da_api = cursor.fetchall()
    if not da_api:
        return {}
    pares, _ = emparelhar(
        candidatos, da_api, lambda t: t.get('descricao'), lambda b: b['descricao'],
        lambda t: _digitos(t.get('cnpj_cpf')), lambda b: _digitos(b.get('cnpj_cpf')))
    feitos = {}
    for t, b in pares:
        if b['status'] == 'pendente':
            cursor.execute(
                """UPDATE bank_transactions SET hash_dedup=%s, fitid=%s,
                          descricao=%s, memo=%s, cnpj_cpf=COALESCE(%s, cnpj_cpf)
                    WHERE id=%s""",
                (t['hash_dedup'], t.get('fitid'), t.get('descricao'), t.get('memo'),
                 t.get('cnpj_cpf'), b['id']))
        else:
            cursor.execute("UPDATE bank_transactions SET hash_dedup=%s, fitid=%s WHERE id=%s",
                           (t['hash_dedup'], t.get('fitid'), b['id']))
        feitos[t['hash_dedup']] = b['id']
    if feitos:
        logger.info('[extrato_grava] OFX conta %s: %d lançamento(s) já vieram pela API',
                    account_id, len(feitos))
    return feitos

