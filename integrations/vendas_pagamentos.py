"""
integrations/vendas_pagamentos.py
=================================

O pagamento de cada cupom, forma por forma, lido do XML da nota.

O robô de vendas do posto (POST /api/vendas) grava em vendas_xml só o total e
o NOME das formas ("Dinheiro+Cartao Debito") e o cartão do 1º <detPag>. O
valor de cada forma se perde — e o cupom misto (R$ 0,01 no dinheiro + R$ 10,00
no PIX) nunca casa com o PIX de 10,00 do banco nem com a venda da maquininha.

Os XMLs (nfeProc, NFC-e 65 e NF-e 55) já chegam ao Dropbox pela captura do
app Qualicontax, ~7 min depois da venda, em
    /Aplicativos/QUALICONTAX/EMPRESAS/162 - POSTO NOVO HORIZONTE GOIATUBA LTDA/Fiscal/SAIDAS/AAAA/MM/<chave>.xml
Aqui SÓ SE LÊ essa pasta: nada é gravado, movido nem apagado lá — ela é do
Qualicontax. O que se grava é a tabela vendas_xml_pagamentos (uma linha por
<detPag>), ligada a vendas_xml pela chave. vendas_xml não muda.

Pasta: env VENDAS_XML_DROPBOX_DIR; sem ela tenta '/Aplicativos/...' e
'/Apps/...' (o nome da pasta de aplicativos depende do idioma da conta).
"""
import logging
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

from utils.db import get_db_connection

_log = logging.getLogger(__name__)

_EMPRESA = 'QUALICONTAX/EMPRESAS/162 - POSTO NOVO HORIZONTE GOIATUBA LTDA/Fiscal/SAIDAS'
PASTAS = ('/Aplicativos/' + _EMPRESA, '/Apps/' + _EMPRESA)

#: Downloads por rodada: a rodada de 10 min traz ~30 cupons; o resto vem na próxima.
LIMITE_RODADA = 600

DDL = """
CREATE TABLE IF NOT EXISTS `vendas_xml_pagamentos` (
    `id`            INT AUTO_INCREMENT PRIMARY KEY,
    `chave`         CHAR(44)      NOT NULL COMMENT 'vendas_xml.chave',
    `n`             TINYINT       NOT NULL COMMENT 'ordem do detPag no XML (1, 2, ...)',
    `tpag`          VARCHAR(2)    NULL,
    `forma`         VARCHAR(30)   NULL,
    `valor`         DECIMAL(14,2) NOT NULL DEFAULT 0,
    `tband`         VARCHAR(2)    NULL,
    `bandeira`      VARCHAR(30)   NULL,
    `credenciadora` VARCHAR(14)   NULL,
    `autorizacao`   VARCHAR(60)   NULL COMMENT 'cAut inteiro (o TxID do PIX tem 35)',
    `integrado`     TINYINT       NULL,
    `troco`         DECIMAL(14,2) NOT NULL DEFAULT 0 COMMENT 'vTroco da nota, só na linha 1',
    `lido_em`       DATETIME      NOT NULL,
    UNIQUE KEY `uk_chave_n` (`chave`, `n`),
    KEY `ix_tpag` (`tpag`, `credenciadora`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

# Mesmos rótulos do robô de vendas (tabela da NT, leiaute NF-e 4.00).
_TPAG = {
    '01': 'Dinheiro', '02': 'Cheque', '03': 'Cartao Credito', '04': 'Cartao Debito',
    '05': 'Credito Loja/Prazo', '10': 'Vale Alimentacao', '11': 'Vale Refeicao',
    '12': 'Vale Presente', '13': 'Vale Combustivel', '14': 'Duplicata Mercantil',
    '15': 'Boleto', '16': 'Deposito Bancario', '17': 'PIX Dinamico',
    '18': 'Transferencia/Carteira', '19': 'Fidelidade/Cashback', '20': 'PIX Estatico',
    '21': 'Credito em Loja', '22': 'Pagto Eletronico', '90': 'Sem Pagamento', '99': 'Outros',
}
_TBAND = {
    '01': 'Visa', '02': 'Mastercard', '03': 'American Express', '04': 'Sorocred',
    '05': 'Diners', '06': 'Elo', '07': 'Hipercard', '08': 'Aura', '09': 'Cabal',
    '99': 'Outros',
}


def ensure_tables():
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(DDL)
        conn.commit()
    finally:
        cur.close()
        conn.close()


def _agora():
    """Hora de Brasília: o servidor roda em UTC."""
    try:
        import pytz
        return datetime.now(pytz.timezone('America/Sao_Paulo')).replace(tzinfo=None)
    except Exception:
        return datetime.now()


def _txt(el, nome):
    if el is None:
        return None
    f = el.find(nome)
    return (f.text or '').strip() or None if f is not None else None


def _num(v):
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return 0.0


def ler_xml(conteudo):
    """(chave, [linhas]) do XML da nota; (None, []) se não for nota.
    Toda nota devolve ao menos uma linha — sem <detPag> vira uma linha vazia,
    para não ser baixada de novo a cada rodada."""
    raiz = ET.fromstring(conteudo)
    for el in raiz.iter():
        if isinstance(el.tag, str) and '}' in el.tag:
            el.tag = el.tag.split('}', 1)[1]
    inf = raiz.find('.//infNFe')
    if inf is None:
        return None, []
    chave = re.sub(r'\D', '', inf.get('Id') or '')[-44:]
    if len(chave) != 44:
        return None, []
    pag = inf.find('pag')
    linhas = []
    for i, dp in enumerate(pag.findall('detPag') if pag is not None else [], 1):
        tpag = _txt(dp, 'tPag')
        card = dp.find('card')
        tband = _txt(card, 'tBand')
        integ = _txt(card, 'tpIntegra')
        linhas.append({
            'n': i, 'tpag': tpag,
            'forma': _TPAG.get(tpag or '', 'Outros(%s)' % tpag if tpag else None),
            'valor': _num(_txt(dp, 'vPag')),
            'tband': tband, 'bandeira': _TBAND.get(tband, 'Outros') if tband else None,
            'credenciadora': re.sub(r'\D', '', _txt(card, 'CNPJ') or '') or None,
            'autorizacao': (_txt(card, 'cAut') or '')[:60] or None,
            'integrado': int(integ) if integ and integ.isdigit() else None,
            'troco': 0.0,
        })
    if not linhas:
        linhas.append({'n': 1, 'tpag': None, 'forma': None, 'valor': 0.0, 'tband': None,
                       'bandeira': None, 'credenciadora': None, 'autorizacao': None,
                       'integrado': None, 'troco': 0.0})
    linhas[0]['troco'] = _num(_txt(pag, 'vTroco'))
    return chave, linhas


def gravar(cur, chave, linhas, quando=None):
    """Grava por cima (a mesma nota lida de novo dá o mesmo resultado)."""
    quando = quando or _agora()
    cur.execute("DELETE FROM vendas_xml_pagamentos WHERE chave = %s AND n > %s",
                (chave, len(linhas)))
    for l in linhas:
        cur.execute(
            """INSERT INTO vendas_xml_pagamentos
                 (chave, n, tpag, forma, valor, tband, bandeira, credenciadora,
                  autorizacao, integrado, troco, lido_em)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON DUPLICATE KEY UPDATE tpag=VALUES(tpag), forma=VALUES(forma),
                 valor=VALUES(valor), tband=VALUES(tband), bandeira=VALUES(bandeira),
                 credenciadora=VALUES(credenciadora), autorizacao=VALUES(autorizacao),
                 integrado=VALUES(integrado), troco=VALUES(troco), lido_em=VALUES(lido_em)""",
            (chave, l['n'], l['tpag'], l['forma'], l['valor'], l['tband'], l['bandeira'],
             l['credenciadora'], l['autorizacao'], l['integrado'], l['troco'], quando))


def ja_lidas(cur, aamm):
    """Chaves do mês (AAMM, posições 3-6 da chave) que já têm pagamento."""
    cur.execute("SELECT DISTINCT chave FROM vendas_xml_pagamentos WHERE SUBSTRING(chave, 3, 4) = %s",
                (aamm,))
    return {r[0] if not isinstance(r, dict) else r['chave'] for r in cur.fetchall()}


def _meses(hoje):
    """O mês corrente e, nos primeiros dias, o anterior (o XML do dia 31 às
    23h chega no dia 1º)."""
    meses = [(hoje.year, hoje.month)]
    if hoje.day <= 3:
        ant = hoje.replace(day=1) - timedelta(days=1)
        meses.append((ant.year, ant.month))
    return meses


def _listar(dbx, pasta):
    res = dbx.files_list_folder(pasta)
    entradas = list(res.entries)
    while res.has_more:
        res = dbx.files_list_folder_continue(res.cursor)
        entradas.extend(res.entries)
    return [e for e in entradas if hasattr(e, 'size') and e.name.lower().endswith('.xml')]


def _base(dbx):
    """A pasta SAIDAS como o Dropbox a chama (env ou o primeiro que existir)."""
    env = (os.environ.get('VENDAS_XML_DROPBOX_DIR') or '').strip().rstrip('/')
    for p in ([env] if env else PASTAS):
        try:
            dbx.files_get_metadata(p)
            return p
        except Exception:
            continue
    return None


def processar():
    """Lê os XMLs novos do mês e grava o pagamento. Devolve um dict de resumo."""
    from integrations.dropbox_ofx import _criar_dbx, is_configured
    if not is_configured():
        return {'erro': 'Dropbox não configurado'}
    ensure_tables()
    dbx = _criar_dbx()
    base = _base(dbx)
    if not base:
        return {'erro': 'pasta SAIDAS do Posto não encontrada no Dropbox'}
    conn = get_db_connection()
    cur = conn.cursor()
    lidos = falhas = 0
    try:
        for ano, mes in _meses(_agora().date()):
            pasta = '%s/%04d/%02d' % (base, ano, mes)
            try:
                arquivos = _listar(dbx, pasta)
            except Exception:
                continue                    # mês ainda sem pasta
            feitas = ja_lidas(cur, '%02d%02d' % (ano % 100, mes))
            for e in sorted(arquivos, key=lambda e: e.name):
                chave_nome = re.sub(r'\D', '', e.name)[:44]
                if chave_nome in feitas:
                    continue
                if lidos + falhas >= LIMITE_RODADA:
                    break
                try:
                    _, resp = dbx.files_download('%s/%s' % (pasta, e.name))
                    chave, linhas = ler_xml(resp.content)
                    if chave:
                        gravar(cur, chave, linhas)
                        conn.commit()
                    lidos += 1
                except Exception:
                    falhas += 1
                    _log.exception('[vendas_pag] %s: falhou', e.name)
    finally:
        cur.close()
        conn.close()
    return {'pasta': base, 'lidos': lidos, 'falhas': falhas}


def situacao(cursor):
    """Para a tela: até quando os pagamentos do XML estão lidos."""
    try:
        cursor.execute("""SELECT MAX(lido_em) lido_em, COUNT(DISTINCT chave) notas
                            FROM vendas_xml_pagamentos""")
        r = cursor.fetchone()
        r = dict(r) if isinstance(r, dict) else {'lido_em': r[0], 'notas': r[1]}
        # O posto vende de madrugada, mas pouco: 6 h sem XML novo é parada.
        r['parado'] = bool(r['lido_em'] and _agora() - r['lido_em'] > timedelta(hours=6))
        return r
    except Exception:
        return None
