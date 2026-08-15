"""
utils/conciliacao.py
====================

Desfazer a conciliação de um lançamento bancário.

Vive aqui, e não dentro de um blueprint, porque desfazer não é só voltar o
status: é limpar tudo o que a conciliação criou junto — a despesa lançada, o
vínculo do troco em PIX e o crédito sintético da transferência. Esquecer um
desses passos deixa lixo que ninguém encontra depois.

Usado pela reversão em lote do financeiro e pela exclusão de memorizações com
reversão.
"""

import logging

logger = logging.getLogger(__name__)


def reverter_uma(cursor_w, tx_id, log=None):
    """Devolve um lançamento para 'pendente' e limpa o que a conciliação criou.

    Recebe um cursor de escrita já aberto; NÃO faz commit — quem chamou decide
    o tamanho da transação. Devolve True se chegou ao fim.
    """
    log = log or logger

    # tipo_conciliacao pode não existir em bancos antigos: tenta com, depois sem.
    try:
        cursor_w.execute(
            """UPDATE bank_transactions
                  SET status = 'pendente',
                      forma_recebimento_id = NULL,
                      fornecedor_id        = NULL,
                      conciliado_em        = NULL,
                      conciliado_por       = NULL,
                      tipo_conciliacao     = NULL
                WHERE id = %s""",
            (tx_id,),
        )
    except Exception:
        cursor_w.execute(
            """UPDATE bank_transactions
                  SET status = 'pendente',
                      forma_recebimento_id = NULL,
                      fornecedor_id        = NULL,
                      conciliado_em        = NULL,
                      conciliado_por       = NULL
                WHERE id = %s""",
            (tx_id,),
        )

    # A despesa que a conciliação lançou.
    try:
        cursor_w.execute(
            "DELETE FROM lancamentos_despesas WHERE bank_transaction_id = %s",
            (tx_id,),
        )
    except Exception as e:
        log.warning("reverter_uma: lancamentos_despesas tx=%s: %s", tx_id, e)

    # O troco em PIX volta a ficar solto.
    try:
        cursor_w.execute(
            "UPDATE troco_pix SET bank_transaction_id = NULL WHERE bank_transaction_id = %s",
            (tx_id,),
        )
    except Exception as e:
        log.warning("reverter_uma: troco_pix tx=%s: %s", tx_id, e)

    # O crédito sintético da transferência, se ainda estiver pendente.
    cursor_w.execute(
        "DELETE FROM bank_transactions"
        " WHERE hash_dedup = %s AND tipo = 'CREDIT' AND status = 'pendente'",
        ('TRANSFER_%d' % tx_id,),
    )
    return True


def reverter_varias(conn, tx_ids, log=None):
    """Reverte uma lista de lançamentos. Devolve (sucessos, [erros]).

    Erro em um lançamento não derruba os outros: o que der para desfazer é
    desfeito, e o que não der volta descrito para quem chamou mostrar.
    """
    log = log or logger
    sucessos, erros = 0, []
    cur_r = conn.cursor(dictionary=True)
    cur_w = conn.cursor()
    try:
        for tx_id in tx_ids:
            try:
                cur_r.execute(
                    "SELECT id, status FROM bank_transactions WHERE id = %s LIMIT 1",
                    (tx_id,),
                )
                tx = cur_r.fetchone()
                if not tx:
                    erros.append('#%s: não encontrada' % tx_id)
                    continue
                if tx['status'] != 'conciliado':
                    erros.append('#%s: não está conciliada' % tx_id)
                    continue
                reverter_uma(cur_w, tx_id, log)
                sucessos += 1
            except Exception as e:
                log.exception("reverter_varias: erro tx_id=%s", tx_id)
                erros.append('#%s: %s' % (tx_id, e))
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        for c in (cur_r, cur_w):
            try:
                c.close()
            except Exception:
                pass
    return sucessos, erros
