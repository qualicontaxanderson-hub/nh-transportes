# -*- coding: utf-8 -*-
"""Cupom fiscal da venda de cada troco PIX (20/11/2026).

Casa a solicitação com o cupom (vendas_xml, NFC-e 65 ou NF-e 55) do MESMO DIA,
autorizado, pago com cheque (forma contém "Cheque") e com valor até R$ 0,10 da
venda do troco (o caixa às vezes digita 1 centavo diferente: 483,09 x 483,10).

- Um candidato só (e livre): liga sozinho (modo 'auto').
- Mais de um, ou nenhum: a tela Ver mostra os candidatos / pede o número, e a
  pessoa liga na mão (modo 'manual').
- Um cupom só pode estar em um troco (uk_cupom).
Medido em 20/11/2026: de 1.518 trocos de 2026, 1.161 têm um candidato só.
"""
from datetime import datetime

TOLERANCIA = 0.10
_tabela_ok = False


def garantir_tabela(conn):
    global _tabela_ok
    if _tabela_ok:
        return
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS troco_pix_cupom (
            troco_pix_id INT NOT NULL PRIMARY KEY,
            vendas_xml_id INT NOT NULL,
            modo VARCHAR(10) NOT NULL,
            criado_por INT NULL,
            criado_em DATETIME NOT NULL,
            UNIQUE KEY uk_cupom (vendas_xml_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    # "não é este": o cupom recusado não volta a ser ligado sozinho
    cur.execute("""
        CREATE TABLE IF NOT EXISTS troco_pix_cupom_recusa (
            troco_pix_id INT NOT NULL,
            vendas_xml_id INT NOT NULL,
            criado_em DATETIME NOT NULL,
            PRIMARY KEY (troco_pix_id, vendas_xml_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    conn.commit()
    cur.close()
    _tabela_ok = True


_CAMPOS = ("v.id, v.numero, v.serie, v.modelo, v.dh_emissao, v.valor_total, "
           "v.forma_pagamento, v.cliente_nome, v.placa")


def cupom_do_troco(conn, troco_pix_id):
    garantir_tabela(conn)
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT " + _CAMPOS + ", tc.modo FROM troco_pix_cupom tc "
                "JOIN vendas_xml v ON v.id = tc.vendas_xml_id WHERE tc.troco_pix_id = %s",
                (troco_pix_id,))
    r = cur.fetchone()
    cur.close()
    return r


def candidatos(conn, troco_pix_id):
    """Cupons do dia, pagos com cheque, valor perto, ainda livres."""
    garantir_tabela(conn)
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT data, venda_total FROM troco_pix WHERE id = %s", (troco_pix_id,))
    t = cur.fetchone()
    if not t or not t['venda_total']:
        cur.close()
        return []
    cur.execute("SELECT " + _CAMPOS + " FROM vendas_xml v "
                "WHERE v.dh_emissao >= %s AND v.dh_emissao < %s + INTERVAL 1 DAY "
                "AND v.situacao = 'autorizada' AND v.forma_pagamento LIKE '%%Cheque%%' "
                "AND ABS(v.valor_total - %s) <= %s "
                "AND NOT EXISTS (SELECT 1 FROM troco_pix_cupom tc WHERE tc.vendas_xml_id = v.id "
                "                AND tc.troco_pix_id <> %s) "
                "AND NOT EXISTS (SELECT 1 FROM troco_pix_cupom_recusa r WHERE r.vendas_xml_id = v.id "
                "                AND r.troco_pix_id = %s) "
                "ORDER BY v.dh_emissao",
                (t['data'], t['data'], t['venda_total'], TOLERANCIA, troco_pix_id, troco_pix_id))
    rows = cur.fetchall()
    cur.close()
    return rows


def por_numero(conn, troco_pix_id, numero):
    """Cupom do dia do troco com esse número (para ligar na mão o que não casou)."""
    garantir_tabela(conn)
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT data FROM troco_pix WHERE id = %s", (troco_pix_id,))
    t = cur.fetchone()
    if not t:
        cur.close()
        return []
    cur.execute("SELECT " + _CAMPOS + " FROM vendas_xml v "
                "WHERE v.numero = %s AND v.situacao = 'autorizada' "
                "AND v.dh_emissao >= %s - INTERVAL 1 DAY AND v.dh_emissao < %s + INTERVAL 2 DAY "
                "ORDER BY v.dh_emissao", (numero, t['data'], t['data']))
    rows = cur.fetchall()
    cur.close()
    # o mesmo número existe em séries diferentes (NF-e 3, NFC-e 2/4/6/8/9/10):
    # se só um deles foi pago com cheque, é ele
    chq = [r for r in rows if 'Cheque' in (r['forma_pagamento'] or '')]
    return chq if chq else rows


def ligar(conn, troco_pix_id, vendas_xml_id, modo, usuario_id=None):
    """Liga (ou troca) o cupom do troco. Devolve None ou a mensagem de erro."""
    garantir_tabela(conn)
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT tc.troco_pix_id, tp.numero_sequencial FROM troco_pix_cupom tc "
                "LEFT JOIN troco_pix tp ON tp.id = tc.troco_pix_id "
                "WHERE tc.vendas_xml_id = %s AND tc.troco_pix_id <> %s",
                (vendas_xml_id, troco_pix_id))
    outro = cur.fetchone()
    if outro:
        cur.close()
        return 'Este cupom já está ligado ao troco %s.' % (outro['numero_sequencial'] or outro['troco_pix_id'])
    cur.execute("REPLACE INTO troco_pix_cupom (troco_pix_id, vendas_xml_id, modo, criado_por, criado_em) "
                "VALUES (%s, %s, %s, %s, %s)",
                (troco_pix_id, vendas_xml_id, modo, usuario_id, datetime.now()))
    conn.commit()
    cur.close()
    return None


def desligar(conn, troco_pix_id, recusar=False):
    garantir_tabela(conn)
    cur = conn.cursor()
    if recusar:
        cur.execute("INSERT IGNORE INTO troco_pix_cupom_recusa (troco_pix_id, vendas_xml_id, criado_em) "
                    "SELECT troco_pix_id, vendas_xml_id, %s FROM troco_pix_cupom WHERE troco_pix_id = %s",
                    (datetime.now(), troco_pix_id))
    cur.execute("DELETE FROM troco_pix_cupom WHERE troco_pix_id = %s", (troco_pix_id,))
    conn.commit()
    cur.close()


def revisar(conn, troco_pix_id):
    """Depois de salvar: se o cupom foi ligado sozinho e o troco mudou (valor ou
    dia) a ponto de não casar mais, solta; e tenta ligar de novo. O que a
    pessoa ligou na mão fica."""
    atual = cupom_do_troco(conn, troco_pix_id)
    if atual and atual['modo'] == 'auto':
        if not any(c['id'] == atual['id'] for c in candidatos(conn, troco_pix_id)):
            desligar(conn, troco_pix_id)
    return tentar_auto(conn, troco_pix_id)


def tentar_auto(conn, troco_pix_id):
    """Se ainda não tem cupom e há UM candidato livre, liga. Devolve o cupom ou None."""
    atual = cupom_do_troco(conn, troco_pix_id)
    if atual:
        return atual
    c = candidatos(conn, troco_pix_id)
    if len(c) == 1 and ligar(conn, troco_pix_id, c[0]['id'], 'auto') is None:
        return cupom_do_troco(conn, troco_pix_id)
    return None
