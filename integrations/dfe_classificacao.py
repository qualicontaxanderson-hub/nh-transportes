"""
Classificacao automatica de itens de COMPRA (DFe) por regra memorizada.

Uma regra em `dfe_classificacao_regra` mapeia (emit_cnpj + cprod_fornecedor) ->
categoria (+ produto_id quando combustivel). Quando notas novas sao capturadas,
`aplicar_regras()` preenche a classificacao dos itens que ja tem regra, para que
NAO caiam na fila de pendentes da tela.

Design:
- Recebe um CURSOR ja aberto (funciona com mysql.connector E pymysql; ambos usam
  o placeholder %s). NAO faz commit -- quem chama controla a transacao.
- Idempotente: so toca em itens com categoria ainda NULL.
- Chamada tipica (nos scripts de captura, DEPOIS de gravar o lote):
      from integrations.dfe_classificacao import aplicar_regras
      aplicar_regras(cur)            # todos os itens pendentes
      aplicar_regras(cur, doc_id)    # so os itens de um documento
      conn.commit()
"""

# UPDATE multi-tabela: casa item pendente com a regra do fornecedor pelo cProd.
_SQL_APLICAR = (
    "UPDATE dfe_itens i "
    "JOIN dfe_documentos d ON d.id = i.documento_id "
    "JOIN dfe_classificacao_regra r "
    "  ON r.emit_cnpj = d.emit_cnpj "
    " AND r.cprod_fornecedor = i.cprod_fornecedor "
    "SET i.categoria = r.categoria, "
    "    i.classificado_produto_id = r.produto_id, "
    "    i.classificado_em = NOW(), "
    "    i.classificado_modo = 'memorizado' "
    "WHERE i.categoria IS NULL "
    "  AND i.cprod_fornecedor IS NOT NULL "
    "  AND i.cprod_fornecedor <> '' "
)


def aplicar_regras(cur, documento_id=None):
    """
    Aplica as regras memorizadas aos itens ainda NAO classificados.

    Args:
        cur: cursor de banco aberto (mysql.connector ou pymysql).
        documento_id: se informado, restringe a esse documento; senao, varre todos.

    Retorna:
        int -- quantidade de itens classificados nesta chamada.

    Nao faz commit: o chamador decide quando efetivar.
    """
    sql = _SQL_APLICAR
    params = ()
    if documento_id is not None:
        sql = sql + " AND i.documento_id = %s"
        params = (documento_id,)
    cur.execute(sql, params)
    # rowcount reflete quantas linhas foram efetivamente atualizadas.
    return cur.rowcount if cur.rowcount is not None and cur.rowcount > 0 else 0
