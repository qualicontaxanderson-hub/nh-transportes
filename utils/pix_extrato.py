# -*- coding: utf-8 -*-
"""Extrato PIX do banco (hoje: Sicoob), PIX a PIX.

O OFX traz o PIX como uma linha de credito; o "Extrato Pix" do Sicoob
(Movimentacao - Recebimentos, .xlsx) traz cada PIX com a hora ao segundo, o
pagador, o banco dele, o ID da transacao (E2E) e -- no "copia e cola" -- o
TxID. Com ele o PIX casa com o cupom (NFC-e) em utils/cartao_cupom:

  - copia e cola: o cupom do PIX APP guarda os 30 primeiros caracteres do
    TxID na autorizacao ("NVYSFRI1J0OVC00228270917919690" ->
    "NVYSFRI1J0OVC0022827091791969030685"). Casa exato.
  - via chave: o frentista digita o nome do pagador na autorizacao do cupom
    ("ROSA MARIA 1410" -> pagador "ROSA MARIA NAVES DA SILVA").

Chega como os outros arquivos: nome comecando com "PIX" (PIX_14_OUTUBRO.xlsx)
na pasta do NH-Robo -> /BANCOS/OFX/NOVO -> agendador de utils/cartao_arquivo.
Reimportar nao duplica: a chave e o ID da transacao (E2E), unico no Pix.

Sicredi ainda nao: quando houver um arquivo de exemplo, entra aqui.
"""
import io
import re
from datetime import datetime

#: CNPJ do banco que liquida o PIX do cupom (card_credenciadora da NFC-e)
CREDENCIADORA = {'02038232000164': 'SICOOB', '01181521000155': 'SICREDI'}


def ensure_table(conn):
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS pix_extrato (
            id            INT AUTO_INCREMENT PRIMARY KEY,
            banco         VARCHAR(20)  NOT NULL,
            cooperativa   VARCHAR(10)  NULL,
            conta         VARCHAR(30)  NULL,
            e2e_id        VARCHAR(40)  NOT NULL,
            dt            DATETIME     NOT NULL,
            historico     VARCHAR(80)  NULL,
            pagador       VARCHAR(160) NULL,
            instituicao   VARCHAR(120) NULL,
            descricao     VARCHAR(200) NULL,
            txid          VARCHAR(40)  NULL,
            valor         DECIMAL(12,2) NOT NULL,
            arquivo       VARCHAR(200) NULL,
            atualizado_em DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uk_e2e (e2e_id),
            KEY ix_dt (banco, dt)
        )""")
    conn.commit()
    cur.close()


def _valor(s):
    s = str(s or '').replace('R$', '').replace('\xa0', '').strip()
    neg = s.startswith('-')
    s = s.lstrip('-').strip()
    if not s:
        return 0.0
    v = float(s.replace('.', '').replace(',', '.'))
    return -v if neg else v


def _txt(v):
    s = str(v).replace('\n', ' ').strip() if v is not None else ''
    return '' if s == '-' else s


def ler_sicoob(conteudo):
    """Os PIX do "Extrato Pix" do Sicoob (.xlsx). Devolve (cabecalho, pix)."""
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(conteudo), read_only=True, data_only=True)
    linhas = list(wb.worksheets[0].iter_rows(values_only=True))
    cab = {'banco': 'SICOOB', 'cooperativa': None, 'conta': None}
    ini = None
    for k, r in enumerate(linhas):
        primeira = _txt(r[0]) if r else ''
        texto = ' '.join(_txt(x) for x in r if x is not None)
        if primeira.startswith('Cooperativa:'):
            m = re.search(r'Cooperativa:\s*(\d+)', texto)
            cab['cooperativa'] = m.group(1) if m else None
            m = re.search(r'Conta Corrente:\s*([\d.\-]+)', texto)
            cab['conta'] = m.group(1) if m else None
        if primeira == 'Data/Hora Movimento':
            ini = k + 1
            break
    if ini is None:
        raise ValueError('nao parece o "Extrato Pix" do Sicoob: sem a coluna '
                         '"Data/Hora Movimento"')
    pix = []
    for r in linhas[ini:]:
        if not r or not r[0] or not re.match(r'\d{2}/\d{2}/\d{4}', _txt(r[0])):
            continue
        e2e = _txt(r[1])
        if not e2e:
            continue
        pix.append({
            'dt': datetime.strptime(_txt(r[0])[:19], '%d/%m/%Y %H:%M:%S'),
            'e2e_id': e2e, 'historico': _txt(r[2])[:80], 'pagador': _txt(r[3])[:160],
            'instituicao': _txt(r[4])[:120], 'descricao': _txt(r[5])[:200],
            'txid': _txt(r[6])[:40] or None, 'valor': _valor(r[7]),
        })
    if not pix:
        raise ValueError('extrato PIX sem nenhum recebimento')
    return cab, pix


def gravar(conn, arquivo, cab, pix):
    ensure_table(conn)
    cols = ('banco', 'cooperativa', 'conta', 'e2e_id', 'dt', 'historico', 'pagador',
            'instituicao', 'descricao', 'txid', 'valor', 'arquivo')
    sql = ('INSERT INTO pix_extrato (%s) VALUES (%s) ON DUPLICATE KEY UPDATE %s' % (
        ', '.join(cols), ', '.join(['%s'] * len(cols)),
        ', '.join('%s=VALUES(%s)' % (c, c) for c in cols if c != 'e2e_id')))
    cur = conn.cursor()
    cur.executemany(sql, [(cab['banco'], cab['cooperativa'], cab['conta'], p['e2e_id'],
                           p['dt'], p['historico'], p['pagador'], p['instituicao'],
                           p['descricao'], p['txid'], p['valor'], arquivo[:200])
                          for p in pix])
    conn.commit()
    cur.close()
