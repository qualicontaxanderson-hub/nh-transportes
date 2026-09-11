# -*- coding: utf-8 -*-
"""Prova do motor do Lucro Postos Migrados, contra os números reais.

Aqui não se prova tela: prova-se a CONTA. Cada número tem de sair da sua fonte
— e a fonte é a da tela que o usuário opera, /estoque?tab=descargas.

A prova que manda é a última: em dois meses inteiros, nenhum dia medido pode
acusar milhares de litros de sobra ou de perda. Foi exatamente isso que a
versão anterior fazia, porque lia a descarga da tabela errada (`descargas`, do
frete, que guarda o que o caminhão CARREGOU) em vez de `descargas_pendentes`,
que guarda o que a régua mediu DESCER.

Não escreve nada: só lê.

    python prova_lucro_migrado.py
"""
import io
import os
import re
import secrets
import sys
from datetime import date, timedelta

if not os.environ.get('DB_PASSWORD') and os.path.exists('bakup_railway.bat'):
    _m = re.search(r'set DBPASS=(.+)',
                   io.open('bakup_railway.bat', encoding='latin-1').read(), re.I)
    if _m:
        os.environ['DB_PASSWORD'] = _m.group(1).strip()
os.environ.setdefault('SECRET_KEY', secrets.token_hex(32))

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils.db import get_db_connection                 # noqa: E402
from utils import lucro_migrado                        # noqa: E402

CLIENTE = 1                     # Posto Novo Horizonte Goiatuba
INI = date(2026, 9, 1)
FIM = date(2026, 9, 10)
PRODUTOS = [1, 2, 4, 5]         # etanol, gasolina, S-500, S-10

falhas = []


def _erro(fn):
    """True quando a chamada levanta erro — o que aqui e o comportamento certo."""
    try:
        fn()
        return False
    except Exception:
        return True


# O mesmo formatador que a tela usa: reescrever o formato aqui daria uma
# prova que passa com a tela errada, ou que falha com ela certa.
from utils.formatadores import formatar_moeda as _moeda   # noqa: E402


def prova(titulo, ok, detalhe=''):
    print('%-6s %s' % ('OK' if ok else 'FALHA', titulo))
    if not ok:
        if detalhe:
            print('        %s' % detalhe)
        falhas.append(titulo)


conn = get_db_connection()
cur = conn.cursor(dictionary=True)


def um(sql, args=()):
    cur.execute(sql, args)
    return cur.fetchone()


try:
    nota = lucro_migrado.apurar(cur, CLIENTE, PRODUTOS, INI, FIM, 'nota')
    desc = lucro_migrado.apurar(cur, CLIENTE, PRODUTOS, INI, FIM, 'descarga')
    prova('a apuração responde pelos quatro produtos',
          set(nota) == set(PRODUTOS) and set(desc) == set(PRODUTOS),
          'nota: %r, descarga: %r' % (sorted(nota), sorted(desc)))
    prova('e por todos os dias do período',
          all(len(nota[p]['dias']) == (FIM - INI).days + 1 for p in nota),
          '%s dias' % {p: len(nota[p]['dias']) for p in nota})

    # ── cada número vem da sua fonte ──────────────────────────────────────
    for pid in PRODUTOS:
        # A NOTA entra pelo dia da descarga que a consumiu, e a soma do
        # periodo tem de bater com os vinculos daquele periodo.
        banco = um("""SELECT COALESCE(SUM(dn.litros),0) l
                        FROM descarga_nota dn
                        JOIN descargas_pendentes dp ON dp.id = dn.descarga_id
                       WHERE dp.cliente_id = %s AND dp.produto_id = %s
                         AND DATE(COALESCE(dp.data_descarga, dp.data_final,
                                           dp.data_inicial)) BETWEEN %s AND %s""",
                   (CLIENTE, pid, INI, FIM))
        tot = nota[pid]['total']
        # o vinculo grava o litro MEDIDO; a alocacao devolve o litro da NOTA,
        # entao os dois andam juntos mas nao sao iguais ao litro
        prova('produto %s: a entrada pela nota é a nota daquelas descargas' % pid,
              abs(tot['entrada_l'] - float(banco['l'])) <= max(
                  float(banco['l']) * 0.05, 50),
              'motor %.1f L, vínculos %.1f L' % (tot['entrada_l'], float(banco['l'])))

        # A DESCARGA e a regua de /estoque?tab=descargas — nao a tabela do frete.
        bd = um("""SELECT COALESCE(SUM(d.total_descarga),0) l
                     FROM descargas_pendentes d
                    WHERE d.cliente_id = %s AND d.produto_id = %s
                      AND DATE(COALESCE(d.data_descarga, d.data_final,
                                        d.data_inicial)) BETWEEN %s AND %s""",
                (CLIENTE, pid, INI, FIM))
        prova('produto %s: a entrada pela descarga é o que a régua mediu' % pid,
              abs(desc[pid]['total']['entrada_l'] - float(bd['l'])) < 0.01,
              'motor %.3f, régua %.3f'
              % (desc[pid]['total']['entrada_l'], float(bd['l'])))

        # e NAO pode ser a tabela do frete, que foi o erro da versao anterior
        bf = um("""SELECT COALESCE(SUM(COALESCE(NULLIF(d.volume_descarregado,0),
                                                d.volume_descarga)),0) l
                     FROM descargas d JOIN fretes f ON f.id = d.frete_id
                    WHERE f.clientes_id = %s AND d.data_descarga BETWEEN %s AND %s
                      AND f.produto_id = %s""", (CLIENTE, INI, FIM, pid))
        if abs(float(bf['l']) - float(bd['l'])) > 1:
            prova('produto %s: não é o volume do frete que está sendo usado' % pid,
                  abs(desc[pid]['total']['entrada_l'] - float(bf['l'])) > 1,
                  'o motor voltou a ler a tabela `descargas` do frete')

        # Cupom cancelado NAO e venda: o produto voltou para o tanque. O
        # motor exclui, e por isso a conferencia exclui tambem — comparar com
        # a soma crua acusaria o motor de perder litros que ele esta certo em
        # nao contar.
        bv = um("""SELECT COALESCE(SUM(i.quantidade),0) l,
                          COALESCE(SUM(i.valor_total),0) v
                     FROM vendas_xml vx JOIN vendas_xml_itens i ON i.venda_id = vx.id
                    WHERE DATE(vx.dh_emissao) BETWEEN %s AND %s
                      AND i.produto_id = %s
                      AND UPPER(COALESCE(vx.situacao,'')) NOT LIKE '%%CANCEL%%'""",
                (INI, FIM, pid))
        prova('produto %s: a venda é a soma dos cupons' % pid,
              abs(tot['venda_l'] - float(bv['l'])) < 0.01
              and abs(tot['venda_rs'] - float(bv['v'])) < 0.01,
              'motor %.3f L / R$ %.2f, banco %.3f L / R$ %.2f'
              % (tot['venda_l'], tot['venda_rs'],
                 float(bv['l']), float(bv['v'])))

    # ── cupom cancelado não pode virar venda ──────────────────────────────
    canc = um("""SELECT COALESCE(SUM(i.quantidade),0) l
                   FROM vendas_xml vx JOIN vendas_xml_itens i ON i.venda_id = vx.id
                  WHERE DATE(vx.dh_emissao) BETWEEN %s AND %s
                    AND i.produto_id IS NOT NULL
                    AND UPPER(COALESCE(vx.situacao,'')) LIKE '%%CANCEL%%'""",
              (INI, FIM))
    cru = um("""SELECT COALESCE(SUM(i.quantidade),0) l
                  FROM vendas_xml vx JOIN vendas_xml_itens i ON i.venda_id = vx.id
                 WHERE DATE(vx.dh_emissao) BETWEEN %s AND %s
                   AND i.produto_id IN (1,2,4,5)""", (INI, FIM))
    somado = sum(nota[p]['total']['venda_l'] for p in PRODUTOS)
    prova('o cancelado fica de fora da venda (%.0f L no período)' % float(canc['l']),
          float(canc['l']) > 0 and abs((float(cru['l']) - somado)
                                       - float(canc['l'])) < 1.0,
          'cru %.1f - motor %.1f = %.1f, cancelado %.1f'
          % (float(cru['l']), somado, float(cru['l']) - somado, float(canc['l'])))

    # ── a alocação "a nota manda" ─────────────────────────────────────────
    # Um item de nota que desce em parcelas tem de fechar EXATAMENTE na sua
    # quantidade: a régua mede com perda de temperatura, e essa perda não pode
    # virar litro de estoque nem sumir do custo.
    cur.execute("""SELECT dn.item_id, i.quantidade nota_l,
                          COUNT(*) parcelas, SUM(dn.litros) medido
                     FROM descarga_nota dn
                     JOIN dfe_itens i ON i.id = dn.item_id
                     JOIN descargas_pendentes dp ON dp.id = dn.descarga_id
                    WHERE dp.cliente_id = %s AND dp.produto_id IN (1,2,4,5)
                      AND DATE(COALESCE(dp.data_descarga, dp.data_final,
                                        dp.data_inicial)) BETWEEN %s AND %s
                    GROUP BY dn.item_id, i.quantidade""", (CLIENTE, INI, FIM))
    vincs = cur.fetchall()
    parcelados = [v for v in vincs if v['parcelas'] > 1]
    difs = [v for v in vincs if abs(float(v['nota_l']) - float(v['medido'])) > 1]
    prova('há nota descendo em mais de uma parcela no período (é o caso difícil)',
          bool(parcelados) or bool(difs),
          'nenhuma nota parcelada nem com perda — a prova não testaria nada')
    soma_nota = sum(float(v['nota_l']) for v in vincs)
    soma_motor = sum(nota[p]['total']['entrada_l'] for p in PRODUTOS)
    prova('a alocação devolve o litro da NOTA, não o da régua',
          abs(soma_motor - soma_nota) <= max(soma_nota * 0.02, 100),
          'motor %.0f L, notas vinculadas %.0f L, régua %.0f L'
          % (soma_motor, soma_nota, sum(float(v['medido']) for v in vincs)))

    # ── a conta do dia fecha ──────────────────────────────────────────────
    erros = []
    for pid in PRODUTOS:
        for d in nota[pid]['dias']:
            esperado = d['ei'] + d['entrada_l'] - d['venda_l']
            if abs(d['ef_calc'] - esperado) > 0.01:
                erros.append((pid, d['data']))
    prova('estoque final calculado = inicial + entrada - venda, todo dia',
          not erros, 'falhou em: %r' % erros[:5])

    erros = []
    for pid in PRODUTOS:
        for d in nota[pid]['dias']:
            if d['ef_real'] is None:
                continue
            if abs(d['variacao'] - (d['ef_real'] - d['ef_calc'])) > 0.01:
                erros.append((pid, d['data']))
    prova('a variação é a medição menos o calculado', not erros,
          'falhou em: %r' % erros[:5])

    # o estoque inicial de cada dia tem de ser a medição daquele dia
    erros = []
    for pid in PRODUTOS:
        for d in nota[pid]['dias']:
            m = um("""SELECT SUM(volume_atual) v FROM leitura_tanque_diaria
                       WHERE cliente_id=%s AND DATE(data_leitura)=%s
                         AND produto_id=%s""", (CLIENTE, d['data'], pid))
            medido = float(m['v']) if m and m['v'] is not None else None
            if medido is None:
                if d['ei_medido']:
                    erros.append((pid, d['data'], 'disse medido sem medição'))
            elif abs(d['ei'] - medido) > 0.01:
                erros.append((pid, d['data'], 'ei %.1f != medição %.1f'
                              % (d['ei'], medido)))
    prova('o estoque inicial do dia é a medição do tanque daquele dia',
          not erros, 'falhou: %r' % erros[:4])

    # ── lucro e margem ────────────────────────────────────────────────────
    erros = []
    for pid in PRODUTOS:
        for d in nota[pid]['dias']:
            if abs(d['lucro_rs'] - (d['venda_rs'] - d['custo_rs'])) > 0.01:
                erros.append((pid, d['data']))
    prova('lucro do dia = receita - custo', not erros, '%r' % erros[:5])

    erros = [pid for pid in PRODUTOS
             if abs(nota[pid]['total']['lucro_rs']
                    - sum(d['lucro_rs'] for d in nota[pid]['dias'])) > 0.05]
    prova('o total do período é a soma dos dias', not erros, '%r' % erros)

    # custo corrido: o custo unitario tem de ficar entre o menor e o maior
    # preco de compra do periodo — se sair disso, a media movel furou
    for pid in PRODUTOS:
        precos = [d['entrada_unit'] for d in nota[pid]['dias'] if d['entrada_l']]
        if not precos:
            continue
        custos = [d['custo_unit'] for d in nota[pid]['dias'] if d['venda_l']]
        if not custos:
            continue
        folga = 0.25          # o estoque de abertura entra por preço médio
        prova('produto %s: o custo corrido anda junto do preço de compra' % pid,
              min(custos) >= min(precos) * (1 - folga)
              and max(custos) <= max(precos) * (1 + folga),
              'compra entre %.4f e %.4f, custo entre %.4f e %.4f'
              % (min(precos), max(precos), min(custos), max(custos)))

    # ── as duas bases: onde elas discordam, e por quê ─────────────────────
    comp = lucro_migrado.comparar(cur, CLIENTE, PRODUTOS, INI, FIM)
    prova('a comparação responde pelos quatro produtos',
          set(comp) == set(PRODUTOS))
    achou = [pid for pid in comp if abs(comp[pid]['diferenca_l']) > 1]
    prova('nota e descarga discordam em pelo menos um produto (é o esperado)',
          bool(achou),
          'as duas bases deram igual — ou não há descarga no período')
    for pid in achou[:2]:
        c = comp[pid]
        print('        produto %s: nota %.0f L, descarga %.0f L, diferença %.0f L'
              % (pid, c['nota_l'], c['descarga_l'], c['diferenca_l']))

    # a venda é a mesma nas duas bases: o que muda é só a entrada
    iguais = all(abs(nota[p]['total']['venda_l'] - desc[p]['total']['venda_l']) < 0.01
                 for p in PRODUTOS)
    prova('a venda não muda de uma base para a outra', iguais)

    # ── a nota e a régua têm de andar coladas, dia a dia ──────────────────
    # Antes a nota entrava pelo dia da emissão e a descarga vinha do frete: as
    # duas se descolavam por milhares de litros. Lidas do vínculo, a distância
    # entre elas é só a perda de temperatura.
    # O guarda mais forte contra a fonte errada: as duas bases tem de ter
    # entrada nos MESMOS dias. Lendo a descarga da tabela do frete, os dias
    # nem coincidiam — era assim que 05/09 ganhava 9.000 L que nao desceram.
    dias_so_um = []
    for pid in PRODUTOS:
        for dn_, dd_ in zip(nota[pid]['dias'], desc[pid]['dias']):
            if bool(dn_['entrada_l'] > 1) != bool(dd_['entrada_l'] > 1):
                dias_so_um.append((pid, dn_['data'], dn_['entrada_l'],
                                   dd_['entrada_l']))
    prova('nota e régua entram exatamente nos mesmos dias',
          not dias_so_um, '%r' % dias_so_um[:4])

    # E a distancia entre elas e a perda de temperatura: alguns por cento. Um
    # dia ruim de regua pode passar disso, mas o TIPICO nao pode.
    difs = []
    for pid in PRODUTOS:
        for dn_, dd_ in zip(nota[pid]['dias'], desc[pid]['dias']):
            maior = max(dn_['entrada_l'], dd_['entrada_l'])
            if maior > 1:
                difs.append(abs(dn_['entrada_l'] - dd_['entrada_l']) / maior)
    difs.sort()
    mediana = difs[len(difs) // 2] if difs else 0.0
    prova('a distância típica entre a nota e a régua é de poucos por cento',
          bool(difs) and mediana < 0.03 and max(difs) < 0.20,
          'mediana %.2f%%, pior %.2f%% em %s descargas'
          % (mediana * 100, (max(difs) if difs else 0) * 100, len(difs)))
    print('        nota x régua: mediana %.2f%%, pior dia %.2f%% (%s descargas)'
          % (mediana * 100, (max(difs) if difs else 0) * 100, len(difs)))

    # ── o que ENTROU: a unica entrada fisica ──────────────────────────────
    # Recalculada aqui a partir das leituras cruas, sem passar pelo motor: se
    # o motor errar a conta, os dois numeros se separam.
    cur.execute("""SELECT DATE(data_leitura) d, produto_id pid,
                          SUM(volume_atual) v
                     FROM leitura_tanque_diaria
                    WHERE cliente_id = %s AND produto_id IS NOT NULL
                      AND DATE(data_leitura) BETWEEN %s AND %s
                    GROUP BY d, produto_id""",
                (CLIENTE, INI, FIM + timedelta(days=1)))
    medida = {(r['d'], r['pid']): float(r['v']) for r in cur.fetchall()}

    erros, tinha = [], 0
    for pid in PRODUTOS:
        for d in nota[pid]['dias']:
            hoje_m = medida.get((d['data'], pid))
            amanha_m = medida.get((d['data'] + timedelta(days=1), pid))
            if hoje_m is None or amanha_m is None:
                if d['entrou'] is not None:
                    erros.append((pid, d['data'], 'inventou um entrou sem medição'))
                continue
            tinha += 1
            esperado = amanha_m - hoje_m + d['venda_l']
            if d['entrou'] is None or abs(d['entrou'] - esperado) > 0.01:
                erros.append((pid, d['data'], d['entrou'], esperado))
    prova('entrou = medição de amanhã - a de hoje + o que se vendeu',
          not erros and tinha > 0, '%r (dias medidos: %s)' % (erros[:4], tinha))

    erros = []
    for pid in PRODUTOS:
        acv = 0.0
        for d in nota[pid]['dias']:
            if d['variacao'] is not None:
                acv += d['variacao']
            if abs(d['var_acum'] - acv) > 0.01:
                erros.append((pid, d['data']))
        if abs(nota[pid]['total']['variacao_l'] - acv) > 0.01:
            erros.append((pid, 'total'))
    prova('a variação acumulada soma de verdade, dia após dia',
          not erros, '%r' % erros[:5])

    # "A descer" e um SALDO, nao um acumulado de coluna: sobe quando a nota e
    # emitida e baixa no dia em que o caminhao chega. Ele PODE ficar negativo,
    # mas so por um motivo: o produto desceu antes de a nota ser registrada.
    # Se ficar negativo sem isso, a baixa esta comendo nota que nao existe.
    adiantadas = um("""SELECT COUNT(*) n FROM descarga_nota dn
                         JOIN descargas_pendentes dp ON dp.id = dn.descarga_id
                         JOIN dfe_itens i ON i.id = dn.item_id
                         JOIN dfe_documentos doc ON doc.id = i.documento_id
                        WHERE dp.cliente_id = %s
                          AND DATE(COALESCE(dp.data_descarga, dp.data_final,
                                            dp.data_inicial))
                              < DATE(doc.dh_emissao)""", (CLIENTE,))
    negativos = [(pid, d['data'], round(d['falta_acum']))
                 for pid in PRODUTOS for d in nota[pid]['dias']
                 if d['falta_acum'] < -1]
    prova('o saldo a descer só fica negativo quando a descarga chega antes '
          'da nota',
          (not negativos) or int(adiantadas['n']) > 0,
          'ficou negativo em %r e não há descarga anterior à nota' % (negativos[:3],))
    if negativos:
        print('        %s dia(s) com saldo negativo — há %s descarga(s) '
              'lançada(s) antes da nota' % (len(negativos), adiantadas['n']))
    baixou = []
    for pid in PRODUTOS:
        ds = nota[pid]['dias']
        for k in range(1, len(ds)):
            if ds[k]['desc_l'] > 100 and ds[k]['falta_acum'] < ds[k - 1]['falta_acum']:
                baixou.append(pid)
                break
    prova('e baixa no dia em que a descarga chega', len(baixou) >= 2,
          'baixou em %r de %r produtos' % (len(baixou), len(PRODUTOS)))

    # ── o caso que o Anderson apontou: a nota de 9.000 L de 05/09 ─────────
    # Ela foi EMITIDA em 05/09 e desceu depois. Antes, o relatorio a jogava em
    # 05/09 e o dia acusava -9.034 L. Agora ela entra no dia da descarga, e
    # 05/09 — um dia em que nao desceu nada — tem de ficar limpo.
    et = nota[1]
    d5 = next((d for d in et['dias'] if d['data'] == date(2026, 9, 5)), None)
    if d5:
        print('        05/09 etanol: nota %.0f L · régua %.0f L · entrou %s L'
              % (d5['nota_l'], d5['medido_l'],
                 '%.0f' % d5['entrou'] if d5['entrou'] is not None else '—'))
        prova('05/09 não recebeu nada, e o relatório concorda',
              d5['nota_l'] == 0 and d5['medido_l'] == 0
              and d5['entrou'] is not None and abs(d5['entrou']) < 300,
              'nota %.0f, régua %.0f, entrou %r'
              % (d5['nota_l'], d5['medido_l'], d5['entrou']))
        prova('o dia de 05/09 parou de acusar milhares de litros',
              abs(d5['variacao'] or 0) < 300,
              'variação do dia %.0f L' % (d5['variacao'] or 0))
        print('        variação do dia %.0f L · do período %.0f L'
              % (d5['variacao'] or 0, et['total']['variacao_l']))
        # a nota de 9.000 L existe, e desceu — nos dias 08 e 09
        emitida = um("""SELECT COALESCE(SUM(i.quantidade),0) l
                          FROM dfe_itens i
                          JOIN dfe_documentos doc ON doc.id = i.documento_id
                         WHERE doc.cliente_id = %s AND i.classificado_produto_id = 1
                           AND DATE(doc.dh_emissao) = '2026-09-05'""", (CLIENTE,))
        prova('a nota de 05/09 existe mesmo — ela só não entrou naquele dia',
              float(emitida['l']) > 5000,
              'a nota emitida em 05/09 soma %.0f L' % float(emitida['l']))

    # o tanque e o juiz: a soma do que entrou tem de ficar entre a nota e a
    # descarga, ou colada em uma delas — nunca fora das duas por muito
    for pid in PRODUTOS:
        t = nota[pid]['total']
        if t['entrou_l'] or t['nota_l'] or t['desc_l']:
            folga = max(t['nota_l'], t['desc_l']) * 0.10 + 500
            prova('produto %s: o que entrou no tanque não foge da nota nem da '
                  'descarga' % pid,
                  min(abs(t['entrou_l'] - t['nota_l']),
                      abs(t['entrou_l'] - t['desc_l'])) <= folga,
                  'entrou %.0f, nota %.0f, descarga %.0f'
                  % (t['entrou_l'], t['nota_l'], t['desc_l']))

    # ── a prova que manda: dois meses, e nenhum dia absurdo ───────────────
    # "nunca tem + 4000 de sobra ou perca" — Anderson. Um dia de posto perde
    # ou sobra dezenas de litros, nao milhares. Se voltar a aparecer um dia de
    # milhares, a fonte esta errada de novo, e esta prova cai.
    LARGO_INI, LARGO_FIM, TETO = date(2026, 8, 1), date(2026, 9, 30), 800
    for base in ('nota', 'descarga'):
        largo = lucro_migrado.apurar(cur, CLIENTE, PRODUTOS,
                                     LARGO_INI, LARGO_FIM, base)
        absurdos, medidos, pior = [], 0, (0.0, None, None)
        for pid in PRODUTOS:
            for d in largo[pid]['dias']:
                if d['variacao'] is None:
                    continue
                medidos += 1
                if abs(d['variacao']) > abs(pior[0]):
                    pior = (d['variacao'], pid, d['data'])
                if abs(d['variacao']) > TETO:
                    absurdos.append((pid, d['data'], round(d['variacao'])))
        prova('base %s: em %s dias medidos, nenhum acusa mais de %s L'
              % (base, medidos, TETO),
              not absurdos and medidos > 100,
              '%s dia(s) fora: %r' % (len(absurdos), absurdos[:5]))
        print('        pior dia da base %s: %.0f L (produto %s em %s)'
              % (base, pior[0], pior[1], pior[2]))

    # ── período sem dado não pode estourar ────────────────────────────────
    vazio = lucro_migrado.apurar(cur, CLIENTE, PRODUTOS,
                                 date(2019, 1, 1), date(2019, 1, 3), 'nota')
    prova('período sem movimento nenhum responde zerado, sem quebrar',
          all(v['total']['venda_l'] == 0 and v['total']['entrada_l'] == 0
              for v in vazio.values()))
    prova('base inválida é recusada',
          _erro(lambda: lucro_migrado.apurar(cur, CLIENTE, PRODUTOS, INI, FIM, 'xpto')))
finally:
    cur.close()
    conn.close()

# ── a tela ────────────────────────────────────────────────────────────────
# O motor acima está provado contra o banco. Aqui prova-se que a tela mostra
# o que ele apurou, nas duas bases.
os.environ.setdefault('WTF_CSRF_ENABLED', 'False')
from app import app                                    # noqa: E402

conn2 = get_db_connection()
cur2 = conn2.cursor(dictionary=True)
cur2.execute("""SELECT id FROM usuarios WHERE ativo = 1
                 AND UPPER(nivel) = 'ADMIN' LIMIT 1""")
adm = cur2.fetchone()

if adm:
    app.config['WTF_CSRF_ENABLED'] = False
    cli = app.test_client()
    with cli.session_transaction() as sess:
        sess['_user_id'] = str(adm['id'])
        sess['_fresh'] = True

    url = ('/relatorios/lucro_postos_migrados?data_inicio=%s&data_fim=%s'
           '&cliente_id=%s' % (INI, FIM, CLIENTE))
    for _p in PRODUTOS:
        url += '&produto_ids[]=%s' % _p

    telas = {}
    for base in ('nota', 'descarga'):
        r = cli.get(url + '&base=' + base, follow_redirects=True)
        h = r.get_data(as_text=True)
        telas[base] = h
        prova('a tela abre na base %s (200)' % base, r.status_code == 200,
              'codigo %s' % r.status_code)
        prova('e não caiu no aviso de erro (%s)' % base,
              'Não deu para apurar' not in h and 'id="lpm"' in h)
        prova('há um quadro por produto na base %s' % base,
              h.count('onclick="lpmAbre(this)"') == len(PRODUTOS),
              '%s quadros para %s produtos'
              % (h.count('onclick="lpmAbre(this)"'), len(PRODUTOS)))

    # os números da tela são os do motor — nas duas bases
    for base in ('nota', 'descarga'):
        ap = lucro_migrado.apurar(cur2, CLIENTE, PRODUTOS, INI, FIM, base)
        faltou = []
        for pid, dados in ap.items():
            for campo in ('venda_l', 'entrada_l'):
                v = '{:,.0f}'.format(dados['total'][campo]).replace(',', '.')
                if v not in telas[base]:
                    faltou.append((base, pid, campo, v))
        prova('os litros da base %s aparecem na tela, produto a produto' % base,
              not faltou, 'não achei: %r' % faltou[:4])

    # a entrada MUDA de uma base para a outra — é para isso que elas existem
    dif = [pid for pid, c in lucro_migrado.comparar(cur2, CLIENTE, PRODUTOS,
                                                    INI, FIM).items()
           if abs(c['diferenca_l']) > 1]
    prova('a tela das duas bases não mostra o mesmo número',
          bool(dif) and telas['nota'] != telas['descarga'],
          'as duas telas saíram iguais')
    # uma por produto, mais a do posto inteiro e a da conferencia das fontes
    prova('a tabela do dia a dia está lá, uma por produto',
          telas['nota'].count('<tbody>') == len(PRODUTOS) + 2,
          '%s tabelas' % telas['nota'].count('<tbody>'))
    prova('a tela explica de onde vem cada entrada',
          'ainda não desceu' in telas['nota']
          and '/estoque → descargas' in telas['nota'])
    prova('a tela traz as três entradas: nota, descarga e tanque',
          '>Nota (L)<' in telas['nota'].replace('\n', ' ')
          and '>Descarga (L)<' in telas['nota'].replace('\n', ' ')
          and '>Entrou (L)<' in telas['nota'].replace('\n', ' '),
          'faltou alguma coluna do bloco de entrada')
    prova('e a coluna do acumulado, que é a que vale',
          '>A descer<' in telas['nota'].replace('\n', ' ')
          and '>Acumulada<' in telas['nota'].replace('\n', ' '))
    prova('a tela diz que o dia sozinho não fecha',
          'a nota vem num dia e o caminhão no outro' in
          ' '.join(telas['nota'].split()))
    # ── o resumo geral, que junta todos os produtos ───────────────────
    liso = ' '.join(telas['nota'].split())
    prova('a tela abre pelo posto inteiro, antes de qualquer produto',
          'Lucro do período' in liso and 'De onde vem o lucro' in liso
          and 'Dia a dia do posto' in liso,
          'faltou algum bloco do resumo geral')
    ger = lucro_migrado.apurar(cur2, CLIENTE, PRODUTOS, INI, FIM, 'nota')
    lucro_total = sum(ger[p]['total']['lucro_rs'] for p in ger)
    venda_total = sum(ger[p]['total']['venda_l'] for p in ger)
    prova('o lucro do posto é a soma dos combustíveis, e está na tela',
          _moeda(lucro_total) in liso,
          'não achei %s (lucro somado dos %s produtos)'
          % (_moeda(lucro_total), len(PRODUTOS)))
    prova('e os litros vendidos do posto também',
          '{:,.0f}'.format(venda_total).replace(',', '.') in liso,
          'não achei %s L' % venda_total)
    print('        posto inteiro: %s de lucro em %s L vendidos'
          % (_moeda(lucro_total), '{:,.0f}'.format(venda_total).replace(',', '.')))

    # cada produto tem de aparecer no "de onde vem o lucro", com sua fatia
    faltou = [pid for pid in PRODUTOS
              if _moeda(ger[pid]['total']['lucro_rs']) not in liso]
    prova('cada combustível aparece com o lucro dele no resumo geral',
          not faltou, 'faltaram: %r' % faltou)
    prova('o resumo geral tem a coluna do lucro acumulado',
          liso.count('>Lucro acumulado<') >= 1)

    # o acumulado do ultimo dia TEM de ser o lucro do periodo — se ele somar
    # errado, o numero que o usuario olha para saber se o mes esta indo mente
    ultimo = None
    for k in range(len((ger[PRODUTOS[0]]['dias']))):
        soma = sum(ger[pid]['dias'][k]['lucro_rs'] for pid in PRODUTOS)
        ultimo = (ultimo or 0.0) + soma
    prova('o acumulado do último dia é o lucro do período',
          abs((ultimo or 0.0) - lucro_total) < 0.01,
          'acumulado %.2f, período %.2f' % (ultimo or 0.0, lucro_total))

    # e o acumulado de cada produto tambem
    erros = []
    for pid in PRODUTOS:
        acu = 0.0
        for d in ger[pid]['dias']:
            acu += d['lucro_rs']
            if abs(d['lucro_acum'] - acu) > 0.01:
                erros.append((pid, d['data']))
    prova('o lucro acumulado de cada produto soma dia a dia',
          not erros, '%r' % erros[:4])

    # ── o celular ─────────────────────────────────────────────────────
    # No telefone a tabela vira cartao. Duas coisas tem de valer, ou o
    # cartao fica pior que a tabela: TODA celula que sobrevive precisa do
    # rotulo (senao e um numero solto), e o dia a dia do posto precisa
    # existir em cartao, nao so em tabela.
    corpo = telas['nota']
    tabs = re.findall(r'<div class="tab tab--prod"[^>]*>(.*?)</table>',
                      corpo, re.S)
    prova('cada produto tem a tabela que vira cartão no celular',
          len(tabs) == len(PRODUTOS), '%s de %s' % (len(tabs), len(PRODUTOS)))
    sem_rotulo = []
    for bloco in tabs:
        linha = re.search(r'<tbody>(.*?)</tr>', bloco, re.S)
        if not linha:
            continue
        celulas = re.findall(r'<td([^>]*)>', linha.group(1))
        for k, atrs in enumerate(celulas[1:], 1):   # a 1a e a data, e o topo
            if 'data-r=' not in atrs:
                sem_rotulo.append(atrs.strip()[:60])
    prova('no cartão do celular nenhum número fica sem o nome dele',
          not sem_rotulo, 'sem rótulo: %r' % sem_rotulo[:4])
    escondidas = sum(1 for b in tabs[:1]
                     for a_ in re.findall(r'<td([^>]*)>',
                                          re.search(r'<tbody>(.*?)</tr>', b,
                                                    re.S).group(1))
                     if 'sec' in a_)
    prova('as colunas que não cabem no bolso ficam de fora por padrão',
          escondidas >= 5, 'só %s coluna(s) escondida(s)' % escondidas)
    prova('e a tabela cheia continua a um toque',
          corpo.count('lpmTudo(this)') == len(PRODUTOS)
          and 'Ver a tabela completa' in corpo)

    cartoes = re.findall(r'<div class="dc">', corpo)
    com_venda = sum(1 for d in ger[PRODUTOS[0]]['dias']
                    if sum(ger[p_]['dias'][ger[PRODUTOS[0]]['dias'].index(d)]
                           ['venda_l'] for p_ in PRODUTOS) > 0)
    prova('o dia a dia do posto existe em cartão, um por dia com venda',
          len(cartoes) == com_venda,
          '%s cartões para %s dias com venda' % (len(cartoes), com_venda))
    prova('e o cartão do período fecha a lista com o lucro total',
          _moeda(lucro_total) in ' '.join(
              corpo[corpo.index('class="dias so-fone"'):].split()))

    # ── os dois modelos aprovados ─────────────────────────────────────
    # O escuro so pode existir atras da classe: se uma regra dele escapar
    # para fora, quem escolheu o claro ganha um pedaco escuro sem pedir.
    css = corpo[corpo.index('#lpm .topo{'):corpo.index('</style>',
                                                        corpo.index('#lpm .nada{'))]
    regras_escuras = [l for l in css.splitlines()
                      if ('#0d1926' in l or '#0f1b29' in l or '#5fd79a' in l
                          or '#9fb3c8' in l or '#132033' in l)]
    prova('o painel escuro existe no CSS', len(regras_escuras) >= 6,
          'só %s regra(s) do escuro' % len(regras_escuras))
    vazadas = [l.strip()[:70] for l in regras_escuras
               if '#lpm.escuro' not in l and not l.strip().startswith(('border',
               'background', 'color', '}', '/*', '*'))]
    prova('e toda regra dele está presa à classe .escuro',
          not vazadas, 'escaparam: %r' % vazadas)
    prova('a chave dos dois modelos está na tela',
          'data-tema="claro"' in corpo and 'data-tema="escuro"' in corpo
          and 'lpmTema(' in corpo)
    prova('e a escolha é aplicada antes do painel, para não piscar',
          corpo.index("localStorage.getItem('lpm_tema')")
          < corpo.index('class="painel"'),
          'o script do tema roda depois do painel — a tela nasceria clara')

    prova('e dá o caminho de volta para o relatório antigo',
          '/relatorios/lucro_postos"' in telas['nota']
          or "/relatorios/lucro_postos'" in telas['nota']
          or '/relatorios/lucro_postos<' in telas['nota']
          or 'lucro_postos?' in telas['nota']
          or '/relatorios/lucro_postos' in telas['nota'])
    # Dia sem leitura de tanque tem de ficar marcado — mas só quando existe
    # um. No período provado o ELS mandou os 11 dias completos, e exigir o
    # marcador aqui reprovaria uma tela certa; então a prova procura um
    # período que realmente tenha buraco.
    cur2.execute("""SELECT MIN(DATE(data_leitura)) ini, MAX(DATE(data_leitura)) fim,
                           COUNT(DISTINCT DATE(data_leitura)) dias
                      FROM leitura_tanque_diaria WHERE cliente_id = %s""",
                 (CLIENTE,))
    faixa = cur2.fetchone()
    total_dias = (faixa['fim'] - faixa['ini']).days + 1 if faixa['ini'] else 0
    if total_dias and faixa['dias'] < total_dias:
        u = ('/relatorios/lucro_postos_migrados?data_inicio=%s&data_fim=%s'
             '&cliente_id=%s&base=nota' % (faixa['ini'], faixa['fim'], CLIENTE))
        for _p in PRODUTOS:
            u += '&produto_ids[]=%s' % _p
        hb = cli.get(u, follow_redirects=True).get_data(as_text=True)
        prova('o dia sem medição de tanque vem marcado na tabela',
              'sem leitura de tanque neste dia' in hb,
              'há %s dias sem leitura entre %s e %s, e nenhum foi marcado'
              % (total_dias - faixa['dias'], faixa['ini'], faixa['fim']))
    else:
        print('OK     (no período medido não falta nenhum dia de leitura —'
              ' nada a marcar)')

    # A prova de clique (prova_lucro_tema.js) roda sobre o HTML de verdade;
    # guardar aqui evita que ela teste uma copia que envelhece.
    if '--html' in sys.argv:
        alvo = sys.argv[sys.argv.index('--html') + 1]
        io.open(alvo, 'w', encoding='utf-8').write(telas['nota'])
        print('       (tela guardada em %s)' % alvo)

cur2.close()
conn2.close()

# ── o menu Relatorios tem de levar ate ele ────────────────────────────────
# O botao dentro do relatorio antigo nao basta: quem abre o menu do topo
# procura o relatorio pelo nome, e ate agora ele nao estava la.
hm = cli.get('/relatorios/lucro_postos', follow_redirects=True).get_data(as_text=True)
itens = re.findall(r'<a class="dropdown-item" href="([^"]+)"[^>]*>(.*?)</a>', hm, re.S)
menu = [(u, re.sub(r'<[^>]+>|\s+', ' ', t).strip()) for u, t in itens]
prova('o menu Relatorios leva ao Lucro Postos Migrados',
      any(u == '/relatorios/lucro_postos_migrados' for u, _ in menu),
      'nao achei no menu; tem %s itens' % len(menu))
prova('e com o nome que o usuario procura',
      any(u == '/relatorios/lucro_postos_migrados'
          and 'Lucro Postos Migrados' in t for u, t in menu),
      'achei o link mas com outro texto')
prova('o antigo continua no menu, no lugar dele',
      any(u == '/relatorios/lucro_postos' for u, _ in menu))

print('\n%s' % ('TUDO OK' if not falhas else '%d FALHA(S): %s'
                % (len(falhas), '; '.join(falhas))))
sys.exit(1 if falhas else 0)
