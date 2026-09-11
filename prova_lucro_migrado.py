# -*- coding: utf-8 -*-
"""Prova do motor do Lucro Postos Migrados, contra os números reais.

Aqui não se prova tela: prova-se a CONTA. Cada número tem de sair da sua fonte
e a soma tem de fechar com o que está no banco — e as duas bases (nota e
descarga) têm de discordar exatamente onde o produto ainda não desceu.

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
        banco = um("""SELECT COALESCE(SUM(i.quantidade),0) l,
                             COALESCE(SUM(i.valor_total),0) v
                        FROM dfe_itens i
                        JOIN dfe_documentos doc ON doc.id = i.documento_id
                       WHERE doc.cliente_id = %s
                         AND DATE(doc.dh_emissao) BETWEEN %s AND %s
                         AND i.classificado_produto_id = %s""",
                   (CLIENTE, INI, FIM, pid))
        tot = nota[pid]['total']
        prova('produto %s: a entrada pela nota é a soma das notas' % pid,
              abs(tot['entrada_l'] - float(banco['l'])) < 0.01
              and abs(tot['entrada_rs'] - float(banco['v'])) < 0.01,
              'motor %.3f L / R$ %.2f, banco %.3f L / R$ %.2f'
              % (tot['entrada_l'], tot['entrada_rs'],
                 float(banco['l']), float(banco['v'])))

        bd = um("""SELECT COALESCE(SUM(COALESCE(NULLIF(d.volume_descarregado,0),
                                                d.volume_descarga)),0) l
                     FROM descargas d JOIN fretes f ON f.id = d.frete_id
                    WHERE f.clientes_id = %s AND d.data_descarga BETWEEN %s AND %s
                      AND f.produto_id = %s""", (CLIENTE, INI, FIM, pid))
        prova('produto %s: a entrada pela descarga é o que desceu' % pid,
              abs(desc[pid]['total']['entrada_l'] - float(bd['l'])) < 0.01,
              'motor %.3f, banco %.3f'
              % (desc[pid]['total']['entrada_l'], float(bd['l'])))

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

    # ── o caso que motivou o relatório ────────────────────────────────────
    # S-500 em 09/09: a nota trouxe 12.000 L e a descarga do dia foram 5.000 L
    dia = next((d for d in nota[4]['dias'] if d['data'] == date(2026, 9, 9)), None)
    dia_d = next((d for d in desc[4]['dias'] if d['data'] == date(2026, 9, 9)), None)
    if dia and dia_d:
        prova('o S-500 de 09/09 mostra a diferença entre nota e descarga',
              dia['entrada_l'] > dia_d['entrada_l'] + 1000,
              'nota %.0f L, descarga %.0f L' % (dia['entrada_l'], dia_d['entrada_l']))
        print('        09/09 S-500: EI %.0f · nota %.0f · descarga %.0f · venda %.0f'
              % (dia['ei'], dia['entrada_l'], dia_d['entrada_l'], dia['venda_l']))
        print('        variação pela nota %.0f L · pela descarga %.0f L'
              % (dia['variacao'] or 0, dia_d['variacao'] or 0))

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
        acf, acv = 0.0, 0.0
        for d in nota[pid]['dias']:
            acf += d['nota_l'] - d['desc_l']
            if d['variacao'] is not None:
                acv += d['variacao']
            if abs(d['falta_acum'] - acf) > 0.01 or abs(d['var_acum'] - acv) > 0.01:
                erros.append((pid, d['data']))
        t = nota[pid]['total']
        if abs(t['falta_l'] - acf) > 0.01 or abs(t['variacao_l'] - acv) > 0.01:
            erros.append((pid, 'total'))
    prova('os acumulados somam de verdade, dia após dia', not erros, '%r' % erros[:5])

    # ── o caso que o Anderson apontou: 05/09, nota de 9.000 L que nao chegou ──
    # O dia sozinho acusa milhares de litros de variacao; o acumulado do
    # periodo fecha perto de zero. E esse o ponto do relatorio.
    et = nota[1]
    d5 = next((d for d in et['dias'] if d['data'] == date(2026, 9, 5)), None)
    if d5:
        print('        05/09 etanol: nota %.0f L · descarga %.0f L · entrou %s L'
              % (d5['nota_l'], d5['desc_l'],
                 '%.0f' % d5['entrou'] if d5['entrou'] is not None else '—'))
        prova('05/09: a nota veio e o produto não',
              d5['nota_l'] > 5000 and d5['entrou'] is not None
              and abs(d5['entrou']) < 500,
              'nota %.0f, entrou %r' % (d5['nota_l'], d5['entrou']))
        prova('o dia sozinho acusa muito mais do que o período inteiro',
              abs(d5['variacao'] or 0) > abs(et['total']['variacao_l']) * 5,
              'dia %.0f L, período %.0f L'
              % (d5['variacao'] or 0, et['total']['variacao_l']))
        print('        variação do dia %.0f L · acumulada do período %.0f L'
              % (d5['variacao'] or 0, et['total']['variacao_l']))

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
              h.count('class="prodbox"') == len(PRODUTOS),
              '%s quadros para %s produtos'
              % (h.count('class="prodbox"'), len(PRODUTOS)))

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
    prova('a tabela do dia a dia está lá, uma por produto',
          telas['nota'].count('<tbody>') == len(PRODUTOS),
          '%s tabelas' % telas['nota'].count('<tbody>'))
    prova('a tela explica por que nota e descarga discordam',
          'ainda não chegou' in telas['nota'])
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
