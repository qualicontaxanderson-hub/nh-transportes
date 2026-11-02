"""Abastecimento da frota (cupom a prazo com placa) virando despesa.

Pedido do usuario (02/11/2026): o combustivel dos caminhoes e dos carros era
digitado a mao nas Despesas, um lancamento por mes copiando o total da Frota,
e errava (meses faltando, R$ 2.893 a mais em fev/2026 no R500...). Agora cada
placa da aba Frota (Prazo) e VINCULADA a uma subcategoria de despesa e a Conf.
Despesas tira o valor dos proprios cupons.

  - frota_despesa_vinculo: (placa, cliente_doc) -> subcategoria_id. Placa
    digitada pela metade no cupom (RDT, TFP...) vincula na mesma subcategoria.
  - Nada e gravado em lancamentos_despesas: o valor e calculado na hora.
  - Na subcategoria vinculada, o lancamento DIGITADO (sem pagamento no banco)
    deixa de contar a partir de CORTE, senao o mes sairia em dobro. Lancamento
    ligado a um pagamento do extrato continua (abastecimento em OUTRO posto,
    ex.: 998,50 no Campo Limpo em 14/05/2026).
"""
import re
from datetime import date

CORTE = date(2026, 1, 1)      # inicio da venda migrada (cupons no banco)

_ONDE_PRAZO = ("(v.forma_pagamento LIKE '%%Prazo%%'"
               " OR v.forma_pagamento LIKE '%%redito Loja%%'"
               " OR v.forma_pagamento LIKE '%%rédito Loja%%')")
_PLACA_SQL = "UPPER(REPLACE(REPLACE(v.placa,'-',''),' ',''))"

_pronta = False


def placa_limpa(p):
    return re.sub(r'[^A-Z0-9]', '', (p or '').upper())


def so_digitos(s):
    return re.sub(r'\D', '', s or '')


def garante_tabela(conn):
    """CREATE TABLE faz commit implicito: chamar fora de transacao."""
    global _pronta
    if _pronta:
        return
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS frota_despesa_vinculo (
            id              INT AUTO_INCREMENT PRIMARY KEY,
            placa           VARCHAR(12)  NOT NULL,
            cliente_doc     VARCHAR(14)  NOT NULL DEFAULT '',
            subcategoria_id INT          NOT NULL,
            criado_por      VARCHAR(80)  NULL,
            criado_em       DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uq_placa_doc (placa, cliente_doc),
            KEY ix_sub (subcategoria_id)
        )""")
    # Cupom SEM placa (material comprado a prazo pelo proprio posto, ex.:
    # tacografo, fita) vinculado direto a uma despesa, um por um.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS frota_despesa_cupom (
            venda_id        INT          NOT NULL PRIMARY KEY,
            subcategoria_id INT          NOT NULL,
            criado_por      VARCHAR(80)  NULL,
            criado_em       DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
            KEY ix_sub (subcategoria_id)
        )""")
    conn.commit()
    cur.close()
    _pronta = True


_CAMINHO = """
                   s.nome AS subcategoria_nome, COALESCE(s.ordem, 9999) AS subcategoria_ordem,
                   c.id AS categoria_id, c.nome AS categoria_nome, COALESCE(c.ordem, 9999) AS categoria_ordem,
                   t.id AS titulo_id, t.nome AS titulo_nome, COALESCE(t.ordem, 9999) AS titulo_ordem"""


def vinculos_cupom(conn):
    """Cupons sem placa vinculados um a um: {venda_id: caminho da despesa}."""
    garante_tabela(conn)
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("""
            SELECT f.venda_id, f.subcategoria_id,""" + _CAMINHO + """
              FROM frota_despesa_cupom f
              JOIN subcategorias_despesas s ON s.id = f.subcategoria_id
              JOIN categorias_despesas c ON c.id = s.categoria_id
              JOIN titulos_despesas t ON t.id = c.titulo_id""")
        return {r['venda_id']: r for r in cur.fetchall()}
    finally:
        cur.close()


def vinculos(conn):
    """Todos os vinculos com o caminho da despesa (titulo > categoria > sub).
    Inclui as subcategorias que so tem cupom vinculado (placa '')."""
    garante_tabela(conn)
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("""
            SELECT f.placa, f.cliente_doc, f.subcategoria_id,
                   s.nome AS subcategoria_nome, COALESCE(s.ordem, 9999) AS subcategoria_ordem,
                   c.id AS categoria_id, c.nome AS categoria_nome, COALESCE(c.ordem, 9999) AS categoria_ordem,
                   t.id AS titulo_id, t.nome AS titulo_nome, COALESCE(t.ordem, 9999) AS titulo_ordem
              FROM frota_despesa_vinculo f
              JOIN subcategorias_despesas s ON s.id = f.subcategoria_id
              JOIN categorias_despesas c ON c.id = s.categoria_id
              JOIN titulos_despesas t ON t.id = c.titulo_id""")
        out = cur.fetchall()
    finally:
        cur.close()
    tem = {v['subcategoria_id'] for v in out}
    for vc in vinculos_cupom(conn).values():
        if vc['subcategoria_id'] not in tem:
            tem.add(vc['subcategoria_id'])
            out.append(dict(vc, placa='', cliente_doc=None))
    return out


def abastecimentos(conn, ini, fim, vincs=None):
    """Um dict por cupom a prazo de placa vinculada, entre ini e fim (>= CORTE),
    com a despesa de destino (titulo/categoria/subcategoria) e a empresa
    (cliente cujo CNPJ e o do cupom)."""
    vincs = vinculos(conn) if vincs is None else vincs
    if not vincs:
        return []
    ini = max(ini, CORTE) if isinstance(ini, date) else max(str(ini), CORTE.isoformat())
    por_chave = {(v['placa'], v['cliente_doc']): v for v in vincs if v['placa']}
    placas = sorted({v['placa'] for v in vincs if v['placa']}) or ['#']
    subs = {v['subcategoria_id'] for v in vincs}
    por_cupom = {k: v for k, v in vinculos_cupom(conn).items() if v['subcategoria_id'] in subs}
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("""SELECT id, REPLACE(REPLACE(REPLACE(cnpj,'.',''),'/',''),'-','') AS doc
                         FROM clientes WHERE cnpj IS NOT NULL AND cnpj <> ''""")
        cli_doc = {}
        for r in cur.fetchall():
            cli_doc.setdefault(r['doc'], r['id'])
        ph = ','.join(['%s'] * len(placas))
        cur.execute(f"""
            SELECT v.id, DATE(v.dh_emissao) AS data, v.dh_emissao, v.numero,
                   {_PLACA_SQL} AS placa, v.cliente_doc, v.km, v.valor_total, v.vendedor_raw,
                   (SELECT SUM(i.quantidade) FROM vendas_xml_itens i
                     WHERE i.venda_id = v.id AND i.eh_combustivel = 1) AS litros
              FROM vendas_xml v
             WHERE {_ONDE_PRAZO}
               AND DATE(v.dh_emissao) BETWEEN %s AND %s
               AND ({_PLACA_SQL} IN ({ph}) OR v.id IN ({','.join(['%s'] * len(por_cupom)) or 'NULL'}))
             ORDER BY v.dh_emissao, v.id""", [ini, fim] + placas + list(por_cupom))
        saida = []
        for r in cur.fetchall():
            v = por_cupom.get(r['id']) or por_chave.get((r['placa'], r['cliente_doc'] or ''))
            if not v:
                continue
            saida.append(dict(v, **{
                'venda_id': r['id'], 'data': r['data'], 'dh_emissao': r['dh_emissao'],
                'numero': r['numero'], 'placa': r['placa'] or 'sem placa',
                'km': float(r['km']) if r['km'] else None,
                'valor': float(r['valor_total'] or 0),
                'litros': float(r['litros'] or 0),
                'frentista': ' '.join((r['vendedor_raw'] or '').split()).title(),
                'cliente_id': cli_doc.get(r['cliente_doc'] or ''),
            }))
        return saida
    finally:
        cur.close()
