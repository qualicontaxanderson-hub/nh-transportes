"""
Camada 2: vinculo entre a DESCARGA FISICA (ELS, descargas_pendentes) e a
NF-E DE COMPRA (dfe_documentos + dfe_itens). O CT-e vem de brinde: a ligacao
CT-e -> NF-e ja existe em dfe_cte_nfe, entao basta segui-la ao contrario.

MODELO
------
A DESCARGA e o que fisicamente entrou no tanque (o "recebido"). Uma NOTA pode
ser baixada em VARIAS descargas: 10.000 L viram 4.900 num dia e 5.200 noutro.

A cada lancamento o USUARIO decide se aquela nota esta encerrada:

  PARCIAL  -> a nota guarda saldo e volta a aparecer nos proximos dias,
              em destaque (e a proxima a descarregar). Nada e apurado.
  INTEGRAL -> este lancamento FECHA a nota. Ela sai das candidatas e a
              perda/sobra e apurada: soma de tudo que foi recebido contra
              essa nota, menos a quantidade da nota.

PERDA e SOBRA
-------------
    perda_sobra = SUM(descarga_nota.litros do item) - dfe_itens.quantidade
    negativo -> PERDA (recebemos menos do que a nota diz)
    positivo -> SOBRA (recebemos mais)

So faz sentido no fechamento: com a nota aberta ainda falta descarregar, e
qualquer numero antes disso seria um falso alarme. Enquanto aberta o valor e
calculado na hora e tratado como provisorio; no fechamento fica gravado na
propria linha que fechou (descarga_nota.perda_sobra_l).

Funcoes puras em relacao a transacao: recebem o cursor e NAO dao commit.
"""
from datetime import date

# Janela folgada de proposito: o produto carrega sexta e desce segunda, ou
# carrega terca e desce quarta. 5 dias cobre o padrao real de viagem.
JANELA_DIAS = 5
TOLERANCIA_L = 500.0
# Abaixo disso o saldo e ruido de arredondamento, nao litro descarregavel.
EPS_L = 0.001

# ---------------------------------------------------------------------------
# Volume a 20 graus
# ---------------------------------------------------------------------------
# O lado da DESCARGA tem total_descarga e total_descarga_20c; o lado da NOTA so
# tem dfe_itens.quantidade (o qCom do XML). Nao existe coluna de 20C em
# dfe_itens e o parser nao le o qTemp de <comb>, entao toda comparacao aqui e
# ambiente x ambiente — o que e aceitavel, ja que os dois lados dilatam
# parecido; ruim seria comparar ambiente com 20C.
#
# O caminho para corrigir de verdade, no dia em que interessar:
#   1. ALTER TABLE dfe_itens ADD COLUMN quantidade_20c DECIMAL(15,4) NULL;
#   2. o parser gravar qTemp/vlrQTemp de <comb>;
#   3. calcular o SALDO em 20C (nao apenas parear volumes totais) e comparar
#      contra total_descarga_20c.
# A funcao _par_volumes() que existia aqui foi removida: alem de nunca
# disparar, ela pareava volumes TOTAIS, e o score agora trabalha com SALDO.


def _f(v):
    """Decimal/None -> float. O MySQL devolve DECIMAL, que nao mistura com float."""
    return float(v) if v is not None else None


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


def conjunto_de(cur, descarga_id=None, item_id=None):
    """Componente conexo no grafo descargas <-> itens de nota.

    Os nos sao as descargas e os itens; as arestas sao as linhas de
    descarga_nota. Uma descarga pode puxar duas notas, uma nota pode puxar
    duas descargas, e isso encadeia — por isso e componente conexo e nao
    "as notas desta descarga".

    Passar os dois argumentos junta um vinculo que ainda nao existe, o que
    permite simular o fechamento antes de gravar.

    Devolve (set de descarga_id, set de item_id). Converge em 1-2 voltas nos
    casos reais; a flag `cresceu` garante a parada.
    """
    descargas = {descarga_id} if descarga_id else set()
    itens = {item_id} if item_id else set()
    while True:
        cresceu = False
        if descargas:
            marc = ", ".join(["%s"] * len(descargas))
            cur.execute(f"SELECT DISTINCT item_id FROM descarga_nota "
                        f"WHERE descarga_id IN ({marc})", list(descargas))
            novos = {r["item_id"] for r in cur.fetchall()} - itens
            if novos:
                itens |= novos
                cresceu = True
        if itens:
            marc = ", ".join(["%s"] * len(itens))
            cur.execute(f"SELECT DISTINCT descarga_id FROM descarga_nota "
                        f"WHERE item_id IN ({marc})", list(itens))
            novos = {r["descarga_id"] for r in cur.fetchall()} - descargas
            if novos:
                descargas |= novos
                cresceu = True
        if not cresceu:
            return descargas, itens


def perda_sobra_conjunto(cur, descarga_id=None, item_id=None, fechando_item=None):
    """Perda/sobra de um CONJUNTO de descargas e notas ligadas entre si.

        perda_sobra = SUM(total_descarga das descargas) - SUM(quantidade das notas)

    Negativo e PERDA (entrou menos do que as notas dizem), positivo e SOBRA.

    A regra e por conjunto, e nao por nota, porque so assim os tres formatos
    cabem numa formula so:
      1 nota -> varias descargas .. gasolina: 4.948+4.820 vs 10.000  = -232
      varias notas -> 1 descarga .. diesel:   4.705 vs 3.000+2.000   = -295
      1 para 1 .................. S10:        3.156 vs 3.000         = +156
    Calculando por nota, o caso do meio contaria o recebido da descarga INTEIRO
    para cada nota (+1.705 e +2.705, somando +4.410 de sobra inventada).

    O numero so vale com o conjunto FECHADO: todo item dele precisa ter algum
    vinculo integral. Enquanto faltar um, ainda pode entrar litro e qualquer
    valor seria um falso alarme. `fechando_item` trata como fechado um item que
    esta sendo fechado agora e ainda nao foi gravado.

    `exibe_em` e a descarga do ULTIMO vinculo integral do conjunto: e nela que
    o numero aparece. As outras nao repetem, senao a auditoria somaria a mesma
    perda duas vezes.

    NAO grava nada — o valor e sempre derivado, entao nao ha como desincronizar
    quando o conjunto cresce.
    """
    descargas, itens = conjunto_de(cur, descarga_id, item_id)
    if not descargas and not itens:
        return None

    soma_d = 0.0
    if descargas:
        marc = ", ".join(["%s"] * len(descargas))
        cur.execute(f"SELECT COALESCE(SUM(total_descarga), 0) AS s "
                    f"FROM descargas_pendentes WHERE id IN ({marc})", list(descargas))
        soma_d = _f((cur.fetchone() or {}).get("s")) or 0.0

    soma_n = 0.0
    fechados = set()
    exibe_em = None
    if itens:
        marc = ", ".join(["%s"] * len(itens))
        cur.execute(f"SELECT COALESCE(SUM(quantidade), 0) AS s "
                    f"FROM dfe_itens WHERE id IN ({marc})", list(itens))
        soma_n = _f((cur.fetchone() or {}).get("s")) or 0.0

        cur.execute(f"SELECT DISTINCT item_id FROM descarga_nota "
                    f"WHERE item_id IN ({marc}) AND modo = 'integral'", list(itens))
        fechados = {r["item_id"] for r in cur.fetchall()}

        cur.execute(f"SELECT descarga_id FROM descarga_nota "
                    f"WHERE item_id IN ({marc}) AND modo = 'integral' "
                    f"ORDER BY id DESC LIMIT 1", list(itens))
        linha = cur.fetchone()
        exibe_em = linha["descarga_id"] if linha else None

    if fechando_item:
        fechados = fechados | {fechando_item}
        if exibe_em is None:
            exibe_em = descarga_id

    return {
        "descargas": descargas, "itens": itens,
        "soma_descargas": round(soma_d, 3), "soma_notas": round(soma_n, 3),
        "perda_sobra": round(soma_d - soma_n, 3),
        "fechado": bool(itens) and itens <= fechados,
        "exibe_em": exibe_em,
    }


def resumo_conjuntos(cur):
    """Perda/sobra de TODOS os conjuntos de uma vez, para a LISTA.

    Fazer BFS por linha da lista custaria N x 2 consultas. Aqui a tabela
    descarga_nota inteira e carregada (dezenas de linhas) e os componentes sao
    montados em memoria — 3 consultas no total, independente do tamanho da
    pagina. Se um dia descarga_nota passar de dezenas de milhares de linhas,
    vale voltar a este ponto.

    Devolve {descarga_id: perda_sobra} SO para a descarga que exibe o numero
    (a do ultimo vinculo integral de cada conjunto fechado).
    """
    cur.execute("SELECT id, descarga_id, item_id, modo FROM descarga_nota ORDER BY id")
    arestas = cur.fetchall()
    if not arestas:
        return {}

    viz = {}
    for a in arestas:
        viz.setdefault(('d', a["descarga_id"]), set()).add(('i', a["item_id"]))
        viz.setdefault(('i', a["item_id"]), set()).add(('d', a["descarga_id"]))

    fechados = {a["item_id"] for a in arestas if a["modo"] == 'integral'}
    # ultimo vinculo integral de cada item (a lista ja vem ordenada por id)
    ultimo = {}
    for a in arestas:
        if a["modo"] == 'integral':
            ultimo[a["item_id"]] = a

    cur.execute("SELECT id, total_descarga FROM descargas_pendentes "
                "WHERE id IN (SELECT DISTINCT descarga_id FROM descarga_nota)")
    tot_d = {r["id"]: _f(r["total_descarga"]) or 0.0 for r in cur.fetchall()}
    cur.execute("SELECT id, quantidade FROM dfe_itens "
                "WHERE id IN (SELECT DISTINCT item_id FROM descarga_nota)")
    tot_i = {r["id"]: _f(r["quantidade"]) or 0.0 for r in cur.fetchall()}

    saida, vistos = {}, set()
    for no in viz:
        if no in vistos:
            continue
        comp, fila = set(), [no]
        while fila:
            atual = fila.pop()
            if atual in comp:
                continue
            comp.add(atual)
            fila.extend(viz[atual] - comp)
        vistos |= comp

        itens = {n for t, n in comp if t == 'i'}
        if not itens or not (itens <= fechados):
            continue                      # conjunto aberto: nada a exibir
        soma_d = sum(tot_d.get(n, 0.0) for t, n in comp if t == 'd')
        soma_n = sum(tot_i.get(n, 0.0) for n in itens)
        # quem exibe: a descarga do vinculo integral de maior id do conjunto
        alvo = max((ultimo[i] for i in itens if i in ultimo),
                   key=lambda a: a["id"], default=None)
        if alvo:
            saida[alvo["descarga_id"]] = round(soma_d - soma_n, 3)
    return saida


def sugerir_notas(cur, descarga_id, janela_dias=JANELA_DIAS,
                  tolerancia_l=TOLERANCIA_L, limite=20):
    """Notas candidatas para UMA descarga, agrupadas por nota, da mais provavel
    para a menos.

    Casa por PRODUTO e por DATA (janela folgada). O volume NAO filtra: numa
    descarga fracionada a nota e legitimamente muito maior, e filtrar
    esconderia justamente a nota certa.

    Fora da lista: nota FECHADA (algum lancamento integral) e nota sem saldo.

    Ordem, em tres niveis:
      1. parcial que ainda cobre  -> ja comecou a descarregar, e a proxima
      2. as que cobrem o que falta
      3. as que nao cobrem, da que mais cobre para a que menos cobre

    Uma NOTA aparece UMA vez. Se ela tiver mais de uma linha do mesmo
    combustivel, as linhas vem dentro dela em `itens` — o vinculo continua
    sendo por item, que e a unica unidade sem ambiguidade (a mesma NF-e pode
    trazer S10 e S500, que vao para tanques diferentes).

    NAO grava nada.
    """
    cur.execute(
        """
        SELECT id, cliente_id, produto_id, produto_nome, tanque, status,
               total_descarga, total_descarga_20c,
               COALESCE(data_final, data_inicial, data_descarga) AS dt,
               COALESCE((SELECT SUM(dn.litros) FROM descarga_nota dn
                          WHERE dn.descarga_id = descargas_pendentes.id), 0) AS vinculado
        FROM descargas_pendentes
        WHERE id = %s
        """,
        (descarga_id,),
    )
    d = cur.fetchone()
    if not d:
        return None

    recebido = _f(d["total_descarga"]) or 0.0
    vinculado = _f(d["vinculado"]) or 0.0
    # O que ainda falta juntar — NAO o total da descarga. Numa descarga que ja
    # tem 3.000 de 6.000, quem manda na comparacao sao os 3.000 que faltam.
    precisa = round(recebido - vinculado, 3)
    dt = d["dt"]
    dia = dt.date() if hasattr(dt, "date") else dt

    descarga = {
        "id": d["id"], "produto_id": d["produto_id"], "produto_nome": d["produto_nome"],
        "tanque": d["tanque"], "status": d["status"], "data": dia,
        "recebido": recebido, "vinculado": vinculado, "precisa": precisa,
        "total_descarga": recebido, "total_descarga_20c": _f(d["total_descarga_20c"]),
    }

    if not d["produto_id"] or not dia:
        return {"descarga": descarga, "candidatas": [],
                "motivo_vazio": ("descarga sem produto_id" if not d["produto_id"]
                                 else "descarga sem data")}

    cur.execute(
        """
        SELECT doc.id  AS documento_id, doc.chave, doc.numero, doc.serie,
               doc.dh_emissao, doc.emit_cnpj, doc.emit_nome,
               doc.valor_total AS nota_valor,
               i.id AS item_id, i.n_item, i.produto_xml, i.cod_anp, i.unidade,
               i.quantidade AS item_litros, i.valor_total AS item_valor, i.categoria,
               COALESCE(v.litros, 0)  AS vinculado_total,
               COALESCE(vd.litros, 0) AS vinculado_nesta,
               -- volume FISICO que ja desceu no tanque por conta desta nota,
               -- em OUTRAS descargas (a atual entra depois, na tela)
               COALESCE((SELECT SUM(dp2.total_descarga)
                           FROM descarga_nota a
                           JOIN descargas_pendentes dp2 ON dp2.id = a.descarga_id
                          WHERE a.item_id = i.id AND a.descarga_id <> %s), 0) AS recebido_fisico,
               EXISTS (SELECT 1 FROM descarga_nota f
                        WHERE f.item_id = i.id AND f.modo = 'integral') AS fechada
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
        ORDER BY doc.dh_emissao DESC, doc.id, i.n_item
        """,
        (descarga_id, descarga_id, d["cliente_id"], d["produto_id"], dia, janela_dias),
    )
    brutas = cur.fetchall()
    if not brutas:
        return {"descarga": descarga, "candidatas": [],
                "motivo_vazio": "nenhuma NF-e autorizada deste produto na janela"}

    tol = tolerancia_l if tolerancia_l and tolerancia_l > 0 else 1.0
    jan = janela_dias if janela_dias and janela_dias > 0 else 1

    # ---- 1) por item: descarta fechada e sem saldo ----
    vivos = []
    n_fechadas = n_sem_saldo = 0
    for r in brutas:
        total_item = _f(r["item_litros"]) or 0.0
        vinc = _f(r["vinculado_total"]) or 0.0
        saldo = round(total_item - vinc, 3)
        if r["fechada"]:
            n_fechadas += 1
            continue
        if saldo <= EPS_L:
            n_sem_saldo += 1
            continue
        r = dict(r)
        r["_total_item"] = total_item
        r["_vinc"] = vinc
        r["_saldo"] = saldo
        vivos.append(r)

    if not vivos:
        motivo = "todas as notas do periodo ja foram fechadas" if n_fechadas \
            else "as notas do periodo nao tem saldo"
        return {"descarga": descarga, "candidatas": [], "motivo_vazio": motivo}

    ctes = _ctes_por_chave(cur, {r["chave"] for r in vivos})

    # ---- 2) agrupa por NOTA (cada nota aparece uma vez) ----
    notas = {}
    for r in vivos:
        doc_id = r["documento_id"]
        emissao = r["dh_emissao"]
        dia_nfe = emissao.date() if hasattr(emissao, "date") else emissao
        if doc_id not in notas:
            notas[doc_id] = {
                "documento_id": doc_id, "chave": r["chave"], "numero": r["numero"],
                "serie": r["serie"], "emissao": dia_nfe,
                "emissao_br": dia_nfe.strftime("%d/%m/%Y") if dia_nfe else "",
                "fornecedor": r["emit_nome"], "emit_cnpj": r["emit_cnpj"],
                "nota_valor": _f(r["nota_valor"]),
                "ctes": ctes.get(r["chave"], []),
                "itens": [],
            }
        notas[doc_id]["itens"].append({
            "item_id": r["item_id"], "n_item": r["n_item"],
            "produto_xml": r["produto_xml"], "cod_anp": r["cod_anp"],
            "unidade": r["unidade"], "categoria": r["categoria"],
            "item_litros": r["_total_item"], "item_valor": _f(r["item_valor"]),
            "vinculado_total": r["_vinc"], "saldo": r["_saldo"],
            "vinculado_nesta": _f(r["vinculado_nesta"]) or 0.0,
            "recebido_fisico": _f(r["recebido_fisico"]) or 0.0,
        })

    # ---- 3) score da nota, pelo SALDO (nao pelo volume total) ----
    candidatas = []
    for c in notas.values():
        # A linha com mais saldo representa a nota na comparacao; e tambem a
        # que vem pre-selecionada quando a nota tem mais de uma linha.
        melhor = max(c["itens"], key=lambda it: it["saldo"])
        saldo = melhor["saldo"]
        dif_dias = (c["emissao"] - dia).days if isinstance(c["emissao"], date) else 0
        dif_litros = round(saldo - precisa, 3)
        cobre = saldo >= precisa - tol
        # Ja comecou a descarregar e ainda tem saldo: e a proxima da fila.
        parcial = any(it["vinculado_total"] > 0 for it in c["itens"])

        c.update({
            "item_id": melhor["item_id"], "n_item": melhor["n_item"],
            "produto_xml": melhor["produto_xml"], "cod_anp": melhor["cod_anp"],
            "unidade": melhor["unidade"], "item_litros": melhor["item_litros"],
            "item_valor": melhor["item_valor"],
            "recebido_fisico": melhor["recebido_fisico"],
            "saldo": saldo, "saldo_nota": round(sum(it["saldo"] for it in c["itens"]), 3),
            "vinculado_total": melhor["vinculado_total"],
            "vinculado_nesta": melhor["vinculado_nesta"],
            "varias_linhas": len(c["itens"]) > 1,
            "base_volume": "ambiente",
            "dif_litros": dif_litros, "dif_dias": dif_dias,
            "dentro_tolerancia": abs(dif_litros) <= tol,
            "cobre": cobre, "parcial": parcial,
            "score": round(abs(dif_litros) / tol + abs(dif_dias) / jan, 4),
            # sugestao para o campo de litros: nunca mais que o saldo
            "sugestao_litros": round(min(saldo, precisa), 3) if precisa > 0 else saldo,
        })
        candidatas.append(c)

    candidatas.sort(key=lambda c: (not (c["parcial"] and c["cobre"]),
                                   not c["cobre"], c["score"]))
    return {"descarga": descarga, "candidatas": candidatas[:limite],
            "ocultas_fechadas": n_fechadas, "ocultas_sem_saldo": n_sem_saldo}


def listar_vinculos(cur, descarga_id):
    """Vinculos ja gravados de UMA descarga, com os dados da nota, pro modal."""
    cur.execute(
        """
        SELECT dn.id, dn.litros, dn.modo, dn.perda_sobra_l, dn.observacao,
               dn.criado_em, dn.criado_por, dn.documento_id, dn.item_id,
               doc.numero, doc.serie, doc.emit_nome AS fornecedor, doc.chave,
               i.n_item, i.produto_xml, i.quantidade AS item_litros,
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
    # Consome o cursor ANTES de calcular o conjunto: perda_sobra_conjunto faz
    # as proprias consultas e sobrescreveria este resultado.
    linhas = cur.fetchall()
    conj = perda_sobra_conjunto(cur, descarga_id=descarga_id)
    saida = []
    for r in linhas:
        r = dict(r)
        r["litros"] = _f(r["litros"])
        r["item_litros"] = _f(r["item_litros"])
        # O numero e do CONJUNTO, nao desta linha: aparece uma vez so, na
        # descarga do ultimo vinculo integral, e so com o conjunto fechado.
        r["perda_sobra_l"] = (conj["perda_sobra"]
                              if (conj and conj["fechado"]
                                  and conj["exibe_em"] == descarga_id) else None)
        r["perda_sobra_prov"] = None
        saida.append(r)
    return saida


def vinculos_resumo(cur, descarga_ids):
    """Resumo por descarga para a LISTA (uma consulta so, sem N+1)."""
    ids = [i for i in (descarga_ids or []) if i]
    if not ids:
        return {}
    marc = ", ".join(["%s"] * len(ids))
    cur.execute(
        f"""
        SELECT dn.descarga_id, COUNT(*) AS n, SUM(dn.litros) AS litros,
               MIN(doc.numero) AS numero,
               SUM(dn.modo = 'integral') AS fechadas,
               SUM(NOT EXISTS (SELECT 1 FROM descarga_nota f
                                WHERE f.item_id = dn.item_id
                                  AND f.modo = 'integral')) AS abertas
        FROM descarga_nota dn
        JOIN dfe_documentos doc ON doc.id = dn.documento_id
        WHERE dn.descarga_id IN ({marc})
        GROUP BY dn.descarga_id
        """,
        ids,
    )
    base = {r["descarga_id"]: {"n": r["n"], "litros": _f(r["litros"]) or 0.0,
                               "numero": r["numero"], "fechadas": r["fechadas"] or 0,
                               "abertas": r["abertas"] or 0, "dif": None}
            for r in cur.fetchall()}
    # A perda/sobra vem dos CONJUNTOS, calculada de uma vez para toda a tabela
    # (3 consultas), e so entra na descarga que exibe o numero.
    for descarga_id, ps in resumo_conjuntos(cur).items():
        if descarga_id in base:
            base[descarga_id]["dif"] = ps
    return base


def registrar_vinculo(cur, descarga_id, item_id, litros, usuario_id=None,
                      observacao=None, modo='parcial', tolerancia_l=TOLERANCIA_L):
    """Grava UM lancamento depois de revalidar TUDO no servidor.

    Nao confia em nada da tela: o `documento_id` sai do `item_id` (nunca vem de
    fora, senao as duas colunas poderiam divergir) e a legitimidade do item e
    conferida de novo — mesma empresa, mesmo produto, NF-e autorizada.

    NAO ha mais trava de "litros <= o que falta na descarga": era ela que
    impedia registrar perda e sobra. Uma nota de 5.000 pode ser lancada inteira
    numa descarga que recebeu 4.950 — a diferenca e justamente a perda. Sobra
    apenas o limite fisico: litros <= saldo da nota. Os avisos de "passou do
    recebido" e de perda/sobra sao dados pela TELA antes de confirmar; aqui
    nao se bloqueia.

    modo='integral' FECHA a nota: grava perda_sobra_l nesta linha e tira a nota
    das candidatas dali pra frente.

    Levanta ValueError com mensagem pronta pra exibir. NAO da commit.
    """
    try:
        litros = float(str(litros).replace(",", "."))
    except (TypeError, ValueError):
        raise ValueError("Informe os litros em número.")
    if litros <= 0:
        raise ValueError("Os litros precisam ser maiores que zero.")
    if modo not in ('parcial', 'integral'):
        raise ValueError("Modo inválido: use parcial ou integral.")

    cur.execute(
        "SELECT id, cliente_id, produto_id, status, total_descarga "
        "FROM descargas_pendentes WHERE id = %s",
        (descarga_id,),
    )
    d = cur.fetchone()
    if not d:
        raise ValueError("Descarga não encontrada.")
    if d["status"] == 'ignorada':
        raise ValueError("Esta descarga está marcada como ignorada. "
                         "Tire a marcação antes de vincular uma nota.")

    cur.execute(
        """
        SELECT i.id, i.documento_id, i.quantidade,
               COALESCE(i.classificado_produto_id, i.produto_id) AS produto_id,
               doc.cliente_id, doc.tipo, doc.situacao, doc.numero,
               COALESCE((SELECT SUM(dn.litros) FROM descarga_nota dn
                          WHERE dn.item_id = i.id), 0) AS vinculado_item,
               EXISTS (SELECT 1 FROM descarga_nota f
                        WHERE f.item_id = i.id AND f.modo = 'integral') AS fechada
        FROM dfe_itens i
        JOIN dfe_documentos doc ON doc.id = i.documento_id
        WHERE i.id = %s
        """,
        (item_id,),
    )
    it = cur.fetchone()
    if not it:
        raise ValueError("Item da nota não encontrado.")
    if it["fechada"]:
        raise ValueError("A nota %s já foi fechada. Desfaça o fechamento antes "
                         "de lançar de novo." % (it["numero"] or "?"))
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

    # perda_sobra_l NAO e mais gravada. O numero passou a ser do CONJUNTO, que
    # pode crescer depois deste lancamento (basta vincular outra nota a alguma
    # descarga dele); gravar aqui congelaria um valor que amanha estaria
    # errado. Agora e sempre derivado. A coluna fica no banco, sem uso.
    cur.execute(
        """
        INSERT INTO descarga_nota
            (descarga_id, documento_id, item_id, litros, modo, perda_sobra_l,
             observacao, criado_por)
        VALUES (%s, %s, %s, %s, %s, NULL, %s, %s)
        ON DUPLICATE KEY UPDATE
            litros     = litros + VALUES(litros),
            modo       = VALUES(modo),
            observacao = COALESCE(NULLIF(VALUES(observacao), ''), observacao)
        """,
        (descarga_id, it["documento_id"], item_id, litros, modo,
         (observacao or '').strip()[:255] or None, usuario_id),
    )
    estado = calcular_estado(cur, descarga_id, tolerancia_l=tolerancia_l)
    if estado is not None:
        estado["fechou_nota"] = (modo == 'integral')
        estado["nota_numero"] = it["numero"]
    return estado


def remover_vinculo(cur, vinculo_id, tolerancia_l=TOLERANCIA_L):
    """Desfaz UM lancamento e recalcula o estado da descarga.

    Se a linha removida era o fechamento da nota, a nota REABRE sozinha: a
    marca de integral morre junto com o lancamento, e a perda/sobra gravada
    nela vai junto — nao fica resultado orfao.

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
    """Progresso da descarga: quanto do RECEBIDO ja foi coberto por notas.

    A descarga fecha quando o vinculado alcanca o recebido OU quando todas as
    notas dela foram fechadas (integral). O segundo caso importa: com perda,
    o vinculado nunca chega ao recebido, e sem essa regra a descarga ficaria
    eternamente pendente.

    Nao mexe em descarga 'ignorada'. NAO da commit.
    """
    cur.execute(
        """
        SELECT dp.id, dp.status, dp.total_descarga,
               COALESCE((SELECT SUM(dn.litros) FROM descarga_nota dn
                          WHERE dn.descarga_id = dp.id), 0) AS vinculado,
               COALESCE((SELECT COUNT(*) FROM descarga_nota dn
                          WHERE dn.descarga_id = dp.id), 0) AS n_vinculos,
               COALESCE((SELECT COUNT(*) FROM descarga_nota dn
                          WHERE dn.descarga_id = dp.id
                            AND NOT EXISTS (SELECT 1 FROM descarga_nota f
                                             WHERE f.item_id = dn.item_id
                                               AND f.modo = 'integral')), 0) AS notas_abertas
        FROM descargas_pendentes dp
        WHERE dp.id = %s
        """,
        (descarga_id,),
    )
    r = cur.fetchone()
    if not r:
        return None

    recebido = _f(r["total_descarga"]) or 0.0
    vinculado = _f(r["vinculado"]) or 0.0
    n_vinculos = r["n_vinculos"]
    notas_abertas = r["notas_abertas"]

    # Estrito de proposito: a tolerancia serve para SUGERIR nota plausivel, nao
    # para declarar descarga fechada. Faltando 150 L com nota ainda aberta, a
    # descarga NAO esta resolvida — dar como fechada esconderia a diferenca,
    # que e justamente o que perda/sobra existe para mostrar.
    alcancou = vinculado > 0 and recebido > 0 and vinculado >= (recebido - EPS_L)
    todas_fechadas = n_vinculos > 0 and notas_abertas == 0
    coberta = bool(alcancou or todas_fechadas)
    falta = round(recebido - vinculado, 3)

    status_atual = r["status"]
    novo_status = status_atual
    if atualizar_status and status_atual != 'ignorada':
        novo_status = 'vinculada' if coberta else 'pendente'
        if novo_status != status_atual:
            cur.execute(
                "UPDATE descargas_pendentes SET status = %s WHERE id = %s",
                (novo_status, descarga_id),
            )

    # PERDA/SOBRA, por NOTA: tudo que aquela nota recebeu — somando TODAS as
    # descargas ligadas a ela — contra a quantidade da nota. Negativo e perda,
    # positivo e sobra.
    #
    # Tem que somar todas: uma nota de 10.000 baixada em 4.948 + 4.820 recebeu
    # 9.768, logo perda de 232. Olhar so a descarga do fechamento daria
    # 4.820 - 10.000 = -5.180, que foi exatamente o bug.
    #
    # So aparece com as notas FECHADAS: com alguma aberta ainda pode entrar
    # litro e o numero mudaria.
    # Perda/sobra do CONJUNTO (descargas e notas ligadas entre si), derivada na
    # hora — nunca gravada, entao nao ha como ficar velha quando o conjunto
    # cresce. So aparece se o conjunto estiver fechado E se esta for a descarga
    # do ultimo vinculo integral; nas outras do conjunto fica None, senao a
    # mesma perda apareceria varias vezes.
    perda_sobra = None
    conj = perda_sobra_conjunto(cur, descarga_id=descarga_id) if n_vinculos else None
    if conj and conj["fechado"] and conj["exibe_em"] == descarga_id:
        perda_sobra = conj["perda_sobra"]

    return {
        "descarga_id": r["id"],
        "recebido": recebido,
        "vinculado": vinculado,
        "perda_sobra": perda_sobra,     # None enquanto houver nota aberta
        "falta": falta,                 # negativo = vinculou mais que o recebido
        "total_descarga": recebido,     # nome antigo, mantido para a tela
        "saldo": falta,
        "coberta": coberta,
        "parcial": bool(vinculado > 0 and not coberta),
        "n_vinculos": n_vinculos,
        "notas_abertas": notas_abertas,
        "todas_fechadas": todas_fechadas,
        "status_anterior": status_atual,
        "status": novo_status,
        "status_alterado": novo_status != status_atual,
    }
