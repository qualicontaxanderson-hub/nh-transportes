"""
Camada 2: vinculo entre a DESCARGA FISICA (ELS, descargas_pendentes) e a
NF-E DE COMPRA (dfe_documentos + dfe_itens). O CT-e vem de brinde: a ligacao
CT-e -> NF-e ja existe em dfe_cte_nfe, entao basta segui-la ao contrario.

Duas funcoes, ambas puras em relacao a transacao (recebem o cursor, NAO dao
commit — quem chama decide):

    sugerir_notas(cur, descarga_id)   -> candidatas ordenadas pela mais provavel
    calcular_estado(cur, descarga_id) -> quanto ja foi vinculado e se cobriu

O fluxo e SUGERIR -> o usuario ESCOLHE. Nada aqui grava vinculo sozinho.
Depende da tabela descarga_nota (scripts/criar_tabela_descarga_nota.py).
"""
from datetime import date

# Mesmos defaults que o els_email.py ja usa pro frete interno, pra tela nao
# ter dois criterios diferentes de "perto".
JANELA_DIAS = 5
TOLERANCIA_L = 500.0

# ---------------------------------------------------------------------------
# ATENCAO — volume a 20 graus
# ---------------------------------------------------------------------------
# O lado da DESCARGA tem os dois volumes (total_descarga e total_descarga_20c).
# O lado da NOTA hoje so tem `dfe_itens.quantidade` (o qCom do XML): NAO existe
# coluna de volume a 20C em dfe_itens, e o parser (scripts/processa_dfe.py) nao
# le o qTemp do grupo <comb>. Ou seja: a comparacao 20C x 20C esta implementada
# aqui, mas NUNCA dispara hoje — sempre cai em ambiente x ambiente. Isso e
# aceitavel porque os dois lados sofrem dilatacao parecida; o que seria ruim e
# comparar ambiente com 20C, e e exatamente o que _par_volumes() evita.
# Para ligar de verdade seria preciso (deliberadamente FORA do escopo de agora):
#   1. ALTER TABLE dfe_itens ADD COLUMN quantidade_20c DECIMAL(15,4) NULL;
#   2. o parser gravar qTemp/vlrQTemp de <comb>;
#   3. trocar SQL_ITEM_20C abaixo por "i.quantidade_20c".
# Enquanto isso, NULL faz o codigo escolher ambiente x ambiente sozinho.
SQL_ITEM_20C = "NULL"


def _f(v):
    """Decimal/None -> float. O MySQL devolve DECIMAL, que nao mistura com float."""
    return float(v) if v is not None else None


def _par_volumes(desc_amb, desc_20c, nfe_amb, nfe_20c):
    """Escolhe o par de volumes a comparar.

    20C x 20C quando os DOIS lados tiverem (mais preciso: elimina a dilatacao
    termica, que em 12.000 L a 25C ja da ~100 L). Senao, ambiente x ambiente —
    comparar ambiente com 20C seria pior do que nao corrigir nada.
    Retorna (litros_descarga, litros_nota, base) com base em '20c' ou 'ambiente'.
    """
    if desc_20c is not None and nfe_20c is not None:
        return desc_20c, nfe_20c, '20c'
    return (desc_amb or 0.0), (nfe_amb or 0.0), 'ambiente'


def _ctes_por_chave(cur, chaves):
    """CT-e que transportaram cada NF-e, indexado pela chave da NF-e.

    Uma consulta so para todas as candidatas (evita N+1). Uma NF-e pode ter
    mais de um CT-e (redespacho, complementar), entao o valor e uma lista.
    """
    if not chaves:
        return {}
    marc = ", ".join(["%s"] * len(chaves))
    cur.execute(
        f"""
        SELECT n.chave_nfe,
               c.id AS cte_documento_id, c.numero AS cte_numero,
               c.dh_emissao AS cte_emissao, c.emit_nome AS cte_transportadora,
               ct.vprest AS cte_valor_frete, ct.placa AS cte_placa,
               ct.mun_ini, ct.uf_ini, ct.mun_fim, ct.uf_fim
        FROM dfe_cte_nfe n
        JOIN dfe_documentos c ON c.id = n.documento_id AND c.tipo = 'CTe'
        LEFT JOIN dfe_cte ct  ON ct.documento_id = c.id
        WHERE n.chave_nfe IN ({marc})
        ORDER BY c.dh_emissao
        """,
        list(chaves),
    )
    saida = {}
    for r in cur.fetchall():
        saida.setdefault(r["chave_nfe"], []).append(r)
    return saida


def sugerir_notas(cur, descarga_id, janela_dias=JANELA_DIAS,
                  tolerancia_l=TOLERANCIA_L, limite=20):
    """Candidatas a NF-e de compra para UMA descarga, da mais provavel pra menos.

    Casa por PRODUTO (descargas_pendentes.produto_id x o produto do item da
    nota) e por DATA (janela de +/- janela_dias). O volume NAO filtra — ele
    ordena: a tela mostra todas as notas do produto na janela e deixa o usuario
    escolher, porque numa descarga fracionada o volume da nota e legitimamente
    MUITO maior que o da descarga, e filtrar por tolerancia esconderia
    justamente a nota certa.

    Retorna None se a descarga nao existir, senao:
        {'descarga': {...}, 'candidatas': [ {...}, ... ]}

    Cada candidata traz o item da NF-e, o saldo ainda nao vinculado daquele
    item, os CT-e ligados e um `score` (menor = mais provavel).
    NAO grava nada.
    """
    cur.execute(
        """
        SELECT id, cliente_id, produto_id, produto_nome, tanque, status,
               total_descarga, total_descarga_20c,
               COALESCE(data_final, data_inicial, data_descarga) AS dt
        FROM descargas_pendentes
        WHERE id = %s
        """,
        (descarga_id,),
    )
    d = cur.fetchone()
    if not d:
        return None

    desc_amb = _f(d["total_descarga"])
    desc_20c = _f(d["total_descarga_20c"])
    dt = d["dt"]
    dia = dt.date() if hasattr(dt, "date") else dt

    descarga = {
        "id": d["id"], "produto_id": d["produto_id"], "produto_nome": d["produto_nome"],
        "tanque": d["tanque"], "status": d["status"], "data": dia,
        "total_descarga": desc_amb, "total_descarga_20c": desc_20c,
    }

    # Sem produto resolvido ou sem data nao da pra sugerir nada com honestidade.
    if not d["produto_id"] or not dia:
        return {"descarga": descarga, "candidatas": [],
                "motivo_vazio": ("descarga sem produto_id" if not d["produto_id"]
                                 else "descarga sem data")}

    cur.execute(
        f"""
        SELECT doc.id  AS documento_id, doc.chave, doc.numero, doc.serie,
               doc.dh_emissao, doc.emit_cnpj, doc.emit_nome,
               doc.valor_total AS nota_valor,
               i.id AS item_id, i.n_item, i.produto_xml, i.cod_anp, i.unidade,
               i.quantidade AS item_litros, {SQL_ITEM_20C} AS item_litros_20c,
               i.valor_total AS item_valor, i.categoria,
               COALESCE(v.litros, 0)  AS vinculado_total,
               COALESCE(vd.litros, 0) AS vinculado_nesta
        FROM dfe_itens i
        JOIN dfe_documentos doc ON doc.id = i.documento_id
        LEFT JOIN (SELECT item_id, SUM(litros) AS litros
                     FROM descarga_nota GROUP BY item_id) v
               ON v.item_id = i.id
        LEFT JOIN (SELECT item_id, SUM(litros) AS litros
                     FROM descarga_nota WHERE descarga_id = %s GROUP BY item_id) vd
               ON vd.item_id = i.id
        WHERE doc.tipo = 'NFe'
          AND doc.situacao = 'autorizado'
          AND doc.cliente_id = %s
          AND COALESCE(i.classificado_produto_id, i.produto_id) = %s
          AND ABS(DATEDIFF(DATE(doc.dh_emissao), %s)) <= %s
        """,
        (descarga_id, d["cliente_id"], d["produto_id"], dia, janela_dias),
    )
    brutas = cur.fetchall()
    if not brutas:
        return {"descarga": descarga, "candidatas": [],
                "motivo_vazio": "nenhuma NF-e autorizada deste produto na janela"}

    ctes = _ctes_por_chave(cur, {r["chave"] for r in brutas})

    tol = tolerancia_l if tolerancia_l and tolerancia_l > 0 else 1.0
    jan = janela_dias if janela_dias and janela_dias > 0 else 1

    candidatas = []
    for r in brutas:
        nfe_amb = _f(r["item_litros"]) or 0.0
        nfe_20c = _f(r["item_litros_20c"])
        v_desc, v_nota, base = _par_volumes(desc_amb, desc_20c, nfe_amb, nfe_20c)

        emissao = r["dh_emissao"]
        dia_nfe = emissao.date() if hasattr(emissao, "date") else emissao
        dif_dias = (dia_nfe - dia).days if isinstance(dia_nfe, date) else 0
        dif_litros = round(v_nota - v_desc, 3)

        vinc_total = _f(r["vinculado_total"]) or 0.0
        vinc_nesta = _f(r["vinculado_nesta"]) or 0.0
        saldo = round(nfe_amb - vinc_total, 3)

        # Score: as duas distancias normalizadas pela propria unidade de
        # tolerancia, entao "300 L de diferenca" e "3 dias de diferenca" pesam
        # de forma comparavel. Menor = mais provavel.
        score = round(abs(dif_litros) / tol + abs(dif_dias) / jan, 4)

        candidatas.append({
            "documento_id": r["documento_id"], "chave": r["chave"],
            "numero": r["numero"], "serie": r["serie"],
            # emissao_br ja formatada: o jsonify do Flask serializa `date` em
            # HTTP-date ("Tue, 28 Jul 2026 00:00:00 GMT"), que a tela mostrava
            # cru. Formatar aqui evita o navegador ter que parsear aquilo.
            "emissao": dia_nfe,
            "emissao_br": dia_nfe.strftime("%d/%m/%Y") if dia_nfe else "",
            "fornecedor": r["emit_nome"],
            "emit_cnpj": r["emit_cnpj"], "nota_valor": _f(r["nota_valor"]),
            "item_id": r["item_id"], "n_item": r["n_item"],
            "produto_xml": r["produto_xml"], "cod_anp": r["cod_anp"],
            "unidade": r["unidade"], "categoria": r["categoria"],
            "item_litros": nfe_amb, "item_valor": _f(r["item_valor"]),
            # comparacao
            "base_volume": base,          # '20c' ou 'ambiente'
            "dif_litros": dif_litros,     # >0 = nota maior que a descarga
            "dif_dias": dif_dias,         # >0 = nota emitida DEPOIS da descarga
            "dentro_tolerancia": abs(dif_litros) <= tol,
            "score": score,
            # saldo (base do vinculo parcial)
            "vinculado_total": vinc_total,
            "vinculado_nesta": vinc_nesta,
            "saldo": saldo,
            "esgotada": saldo <= 0,
            "ja_vinculada_nesta": vinc_nesta > 0,
            # CT-e de brinde
            "ctes": ctes.get(r["chave"], []),
        })

    # Nota sem saldo vai pro fim mesmo que o volume bata perfeito — nao adianta
    # sugerir em primeiro lugar uma nota ja toda consumida por outras descargas.
    candidatas.sort(key=lambda c: (c["esgotada"], c["score"]))
    return {"descarga": descarga, "candidatas": candidatas[:limite]}


def listar_vinculos(cur, descarga_id):
    """Vinculos ja gravados de UMA descarga, com os dados da nota, pro modal."""
    cur.execute(
        """
        SELECT dn.id, dn.litros, dn.observacao, dn.criado_em, dn.criado_por,
               dn.documento_id, dn.item_id,
               doc.numero, doc.serie, doc.emit_nome AS fornecedor, doc.chave,
               doc.dh_emissao, i.n_item, i.produto_xml,
               u.username AS criado_por_nome
        FROM descarga_nota dn
        JOIN dfe_documentos doc ON doc.id = dn.documento_id
        JOIN dfe_itens i        ON i.id  = dn.item_id
        LEFT JOIN usuarios u    ON u.id  = dn.criado_por
        WHERE dn.descarga_id = %s
        ORDER BY dn.id
        """,
        (descarga_id,),
    )
    saida = []
    for r in cur.fetchall():
        r = dict(r)
        r["litros"] = _f(r["litros"])
        saida.append(r)
    return saida


def vinculos_resumo(cur, descarga_ids):
    """Resumo por descarga para a LISTA (uma consulta so, sem N+1).

    {descarga_id: {'n': qtd de notas, 'litros': total, 'numero': n da 1a nota}}
    """
    ids = [i for i in (descarga_ids or []) if i]
    if not ids:
        return {}
    marc = ", ".join(["%s"] * len(ids))
    cur.execute(
        f"""
        SELECT dn.descarga_id, COUNT(*) AS n, SUM(dn.litros) AS litros,
               MIN(doc.numero) AS numero
        FROM descarga_nota dn
        JOIN dfe_documentos doc ON doc.id = dn.documento_id
        WHERE dn.descarga_id IN ({marc})
        GROUP BY dn.descarga_id
        """,
        ids,
    )
    return {r["descarga_id"]: {"n": r["n"], "litros": _f(r["litros"]) or 0.0,
                               "numero": r["numero"]}
            for r in cur.fetchall()}


def registrar_vinculo(cur, descarga_id, item_id, litros, usuario_id=None,
                      observacao=None, tolerancia_l=TOLERANCIA_L):
    """Grava UM vinculo depois de revalidar TUDO no servidor.

    Nao confia em nada que venha da tela: o `documento_id` e resolvido a partir
    do `item_id` (nunca recebido de fora, senao as duas colunas poderiam
    divergir), e a legitimidade do item e conferida de novo — mesma empresa,
    mesmo produto, NF-e autorizada.

    Vincular o MESMO item na MESMA descarga duas vezes SOMA no vinculo que ja
    existe (ON DUPLICATE KEY), respeitando a UNIQUE(descarga_id, item_id): e o
    que o usuario quer dizer, e evita estourar a constraint na cara dele.

    Levanta ValueError com mensagem pronta pra exibir quando algo nao passa.
    NAO da commit — quem chama controla a transacao.
    Retorna o estado da descarga depois do vinculo.
    """
    try:
        litros = float(str(litros).replace(",", "."))
    except (TypeError, ValueError):
        raise ValueError("Informe os litros em número.")
    if litros <= 0:
        raise ValueError("Os litros precisam ser maiores que zero.")

    cur.execute(
        """
        SELECT id, cliente_id, produto_id, status, total_descarga,
               COALESCE((SELECT SUM(dn.litros) FROM descarga_nota dn
                          WHERE dn.descarga_id = descargas_pendentes.id), 0) AS vinculado
        FROM descargas_pendentes WHERE id = %s
        """,
        (descarga_id,),
    )
    d = cur.fetchone()
    if not d:
        raise ValueError("Descarga não encontrada.")
    if d["status"] == 'ignorada':
        raise ValueError("Esta descarga está marcada como ignorada. "
                         "Tire a marcação antes de vincular uma nota.")

    # O item precisa ser um candidato legitimo AGORA — nao basta ter sido
    # quando a tela montou a lista.
    cur.execute(
        """
        SELECT i.id, i.documento_id, i.quantidade,
               COALESCE(i.classificado_produto_id, i.produto_id) AS produto_id,
               doc.cliente_id, doc.tipo, doc.situacao, doc.numero,
               COALESCE((SELECT SUM(dn.litros) FROM descarga_nota dn
                          WHERE dn.item_id = i.id), 0) AS vinculado_item
        FROM dfe_itens i
        JOIN dfe_documentos doc ON doc.id = i.documento_id
        WHERE i.id = %s
        """,
        (item_id,),
    )
    it = cur.fetchone()
    if not it:
        raise ValueError("Item da nota não encontrado.")
    if it["tipo"] != 'NFe' or it["situacao"] != 'autorizado':
        raise ValueError("A nota precisa ser uma NF-e autorizada.")
    if it["cliente_id"] != d["cliente_id"]:
        raise ValueError("Esta nota é de outra empresa.")
    if not d["produto_id"] or it["produto_id"] != d["produto_id"]:
        raise ValueError("O produto da nota não é o mesmo da descarga.")

    saldo_item = round((_f(it["quantidade"]) or 0.0) - (_f(it["vinculado_item"]) or 0.0), 3)
    if litros > saldo_item + 1e-6:
        raise ValueError("A nota %s só tem %.3f L de saldo (você pediu %.3f L)."
                         % (it["numero"] or "?", saldo_item, litros))

    falta = round((_f(d["total_descarga"]) or 0.0) - (_f(d["vinculado"]) or 0.0), 3)
    if litros > falta + 1e-6:
        raise ValueError("Faltam só %.3f L nesta descarga (você pediu %.3f L)."
                         % (falta, litros))

    cur.execute(
        """
        INSERT INTO descarga_nota
            (descarga_id, documento_id, item_id, litros, observacao, criado_por)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            litros     = litros + VALUES(litros),
            observacao = COALESCE(NULLIF(VALUES(observacao), ''), observacao)
        """,
        (descarga_id, it["documento_id"], item_id, litros,
         (observacao or '').strip()[:255] or None, usuario_id),
    )
    return calcular_estado(cur, descarga_id, tolerancia_l=tolerancia_l)


def remover_vinculo(cur, vinculo_id, tolerancia_l=TOLERANCIA_L):
    """Desfaz UM vinculo e recalcula o estado da descarga.

    NAO da commit. Retorna o estado novo, ou None se o vinculo nao existir.
    """
    cur.execute("SELECT descarga_id FROM descarga_nota WHERE id = %s", (vinculo_id,))
    v = cur.fetchone()
    if not v:
        return None
    descarga_id = v["descarga_id"]
    cur.execute("DELETE FROM descarga_nota WHERE id = %s", (vinculo_id,))
    return calcular_estado(cur, descarga_id, tolerancia_l=tolerancia_l)


def calcular_estado(cur, descarga_id, tolerancia_l=TOLERANCIA_L,
                    atualizar_status=True):
    """Quanto da descarga ja foi coberto por notas, e sincroniza o status.

    'Coberta' = a soma dos litros vinculados alcancou o total da descarga,
    dentro da tolerancia. Total x parcial nao e um campo gravado: e o resultado
    desta soma, entao nunca fica dessincronizado do que foi de fato vinculado.

    Nao mexe em descarga marcada como 'ignorada' — foi uma decisao do usuario,
    e nao cabe ao calculo desfazer. NAO da commit: quem chama controla a
    transacao (a tela vai gravar o vinculo e recalcular no mesmo commit).

    Retorna None se a descarga nao existir, senao um dict com o estado.
    """
    cur.execute(
        """
        SELECT dp.id, dp.status, dp.total_descarga,
               COALESCE((SELECT SUM(dn.litros) FROM descarga_nota dn
                          WHERE dn.descarga_id = dp.id), 0) AS vinculado,
               COALESCE((SELECT COUNT(*) FROM descarga_nota dn
                          WHERE dn.descarga_id = dp.id), 0) AS n_vinculos
        FROM descargas_pendentes dp
        WHERE dp.id = %s
        """,
        (descarga_id,),
    )
    r = cur.fetchone()
    if not r:
        return None

    total = _f(r["total_descarga"]) or 0.0
    vinculado = _f(r["vinculado"]) or 0.0
    tol = tolerancia_l if tolerancia_l and tolerancia_l > 0 else 0.0

    # Exige vinculo de verdade: sem nenhum litro vinculado a descarga nao esta
    # "coberta", nem quando o total dela e 0 ou nulo (dado ruim do ELS).
    coberta = bool(vinculado > 0 and total > 0 and vinculado >= (total - tol))
    saldo = round(total - vinculado, 3)

    status_atual = r["status"]
    novo_status = status_atual
    if atualizar_status and status_atual != 'ignorada':
        novo_status = 'vinculada' if coberta else 'pendente'
        if novo_status != status_atual:
            cur.execute(
                "UPDATE descargas_pendentes SET status = %s WHERE id = %s",
                (novo_status, descarga_id),
            )

    return {
        "descarga_id": r["id"],
        "total_descarga": total,
        "vinculado": vinculado,
        "saldo": saldo,
        "coberta": coberta,
        "parcial": bool(vinculado > 0 and not coberta),
        "n_vinculos": r["n_vinculos"],
        "status_anterior": status_atual,
        "status": novo_status,
        "status_alterado": novo_status != status_atual,
    }
