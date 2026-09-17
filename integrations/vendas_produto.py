"""
Resolucao do nosso produto_id para itens de VENDA capturados de XML.

Espelha o papel de integrations/dfe_classificacao para a COMPRA, mas para a
venda. Diferencas: a venda nao tem 'categoria' (venda e sempre produto) e a
chave do de-para e o `cnpj_emitente` (a venda nao carrega cliente_id).

REGRA DE RESOLUCAO (a mesma documentada na tela Classificar de vendas):
  1. De-para `vendas_xml_depara_produto` (cnpj_emitente + cprod) -> produto_id.
     E o UNICO caminho. O cprod e o codigo que o proprio posto da ao produto;
     e ele que separa a gasolina comum da aditivada, e o ARLA da lata de oleo.
  2. Valida contra `cliente_produtos` (allow-list da empresa). Se a empresa
     nao for cliente conhecido, ou nao tiver produtos cadastrados, a validacao
     e PULADA (nao bloqueia) -- ela so serve para pegar erro grosseiro.
  3. Sem resolucao -> None (o item fica NULL e aparece na aba Classificar).

O COD_ANP NAO DECIDE PRODUTO (16/09/2026). Havia um atalho por ANP para os
tres combustiveis sem ambiguidade. Ele saiu: o ANP identifica familia, nao
produto -- o 620505001 sozinho cobre 37 itens do posto, de ARLA a tacografo --
e um sistema que adivinha por ele acaba jurando que uma caixa de Lubrax e
ARLA. Quem decide e a regra que o usuario memorizou.

Design (igual ao aplicar_regras da compra):
- Recebe um CURSOR ja aberto (funciona com mysql.connector E pymysql; ambos
  usam %s). Funciona tanto com cursor tuple quanto dictionary=True.
- NAO faz commit -- quem chama controla a transacao.
"""

def _scalar(row):
    """Primeiro valor de uma linha, seja ela tuple (cursor comum) ou dict
    (cursor dictionary=True)."""
    if row is None:
        return None
    if isinstance(row, dict):
        return next(iter(row.values()), None)
    return row[0]


def _empresa_vende(cur, cnpj_emitente, produto_id):
    """True se a empresa (achada por cnpj_emitente) tem o produto no allow-list
    `cliente_produtos`. Se a empresa nao for cliente conhecido OU nao tiver
    NENHUM produto cadastrado, retorna True (validacao pulada, nao bloqueia)."""
    if not cnpj_emitente or not produto_id:
        return True
    cur.execute(
        "SELECT id FROM clientes "
        "WHERE REPLACE(REPLACE(REPLACE(cnpj,'.',''),'/',''),'-','') = %s LIMIT 1",
        (cnpj_emitente,),
    )
    cid = _scalar(cur.fetchone())
    if not cid:
        return True  # emitente nao mapeado para cliente -> nao bloqueia
    cur.execute(
        "SELECT COUNT(*) FROM cliente_produtos WHERE cliente_id = %s AND ativo = 1",
        (cid,),
    )
    if not _scalar(cur.fetchone()):
        return True  # empresa sem cadastro de produtos -> nao bloqueia
    cur.execute(
        "SELECT 1 FROM cliente_produtos "
        "WHERE cliente_id = %s AND produto_id = %s AND ativo = 1 LIMIT 1",
        (cid, produto_id),
    )
    return cur.fetchone() is not None


def resolver_produto_id_venda(cur, cnpj_emitente, cprod, cod_anp=None):
    """Resolve o nosso produto_id de UM item de venda. Ver regra no topo.
    Retorna produto_id (int) ou None.

    `cod_anp` continua na assinatura porque quem chama ja o passa, mas ele NAO
    decide nada -- ver a nota sobre o ANP no topo do modulo."""
    # 1) de-para (cnpj_emitente + cprod) -- o unico caminho
    if cnpj_emitente and cprod:
        cur.execute(
            "SELECT produto_id FROM vendas_xml_depara_produto "
            "WHERE cnpj_emitente = %s AND cprod = %s AND ativo = 1",
            (cnpj_emitente, cprod),
        )
        pid = _scalar(cur.fetchone())
        if pid:
            return pid if _empresa_vende(cur, cnpj_emitente, pid) else None

    # 2) sem regra memorizada -> fica NULL e aparece na aba Classificar
    return None


def aplicar_depara_venda(cur, venda_id):
    """Preenche vendas_xml_itens.produto_id (ainda NULL) de UMA venda, usando a
    regra de resolucao. Chamado na ingestao (routes/vendas_api.py) para que a
    captura futura nasca resolvida. NAO faz commit.

    Retorna o numero de itens preenchidos.
    """
    if not venda_id:
        return 0
    cur.execute("SELECT cnpj_emitente FROM vendas_xml WHERE id = %s", (venda_id,))
    cnpj = _scalar(cur.fetchone())

    cur.execute(
        "SELECT id, cprod, cod_anp FROM vendas_xml_itens "
        "WHERE venda_id = %s AND produto_id IS NULL",
        (venda_id,),
    )
    itens = cur.fetchall()

    n = 0
    for it in itens:
        if isinstance(it, dict):
            item_id, cprod, cod_anp = it['id'], it['cprod'], it['cod_anp']
        else:
            item_id, cprod, cod_anp = it[0], it[1], it[2]
        pid = resolver_produto_id_venda(cur, cnpj, cprod, cod_anp)
        if pid:
            cur.execute(
                "UPDATE vendas_xml_itens SET produto_id = %s WHERE id = %s",
                (pid, item_id),
            )
            n += 1
    return n
