# -*- coding: utf-8 -*-
"""Prova do /relatorios/saidas_migradas.

Roda a tela de verdade, com o banco de verdade, e cobra dela:

  1) que o motor (utils/saida_migrada) feche com o banco por OUTRO caminho --
     soma direta em SQL, sem passar pelo motor;
  2) que o real contado seja o que ENTROU (linha + acrescimo - desconto), e
     nao a linha do item -- e essa a conta de utils/lucro_migrado;
  3) que os SETE recortes sejam recortes do MESMO faturamento: cada um soma o
     mesmo total, e nenhum perde ou repete nota;
  4) que a nota cancelada fique de fora de tudo, mas apareca contada;
  5) que clicar num card filtre o resto da tela sem trocar o periodo;
  6) que os numeros do motor sejam os que a tela imprime.

  SECRET_KEY=... DB_HOST=... DB_PASSWORD=... python prova_saidas_migradas.py
"""
import io
import re
import sys
from datetime import date, timedelta

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from app import create_app
from utils.db import get_db_connection
from utils import saida_migrada

INI, FIM = date(2026, 9, 1), date(2026, 9, 15)

app = create_app()
app.config['WTF_CSRF_ENABLED'] = False
app.config['LOGIN_DISABLED'] = True

# O real que ENTROU, direto no SQL: e a soma que o motor tem de reproduzir.
_ENTROU = ("SUM(i.valor_total + COALESCE(i.vlr_acrescimo,0) "
           "    - COALESCE(i.vlr_desconto,0))")
_VIVA = ("(v.situacao IS NULL OR UPPER(v.situacao) <> 'CANCELADA') "
         " AND DATE(v.dh_emissao) BETWEEN %s AND %s")
# Litro so de quem e vendido em litro -- o oleo em lata e UN.
_SO_LITRO = "CASE WHEN UPPER(i.unidade) IN ('L','LT','LTS','LITRO') THEN i.quantidade ELSE 0 END"

conn = get_db_connection()
cur = conn.cursor(dictionary=True)

cur.execute("SELECT COUNT(DISTINCT v.id) notas, COUNT(*) itens, "
            "       SUM(%s) litros, %s rs, "
            "       SUM(i.valor_total) linha, "
            "       SUM(COALESCE(i.vlr_acrescimo,0)) acresc, "
            "       SUM(COALESCE(i.vlr_desconto,0)) desc_ "
            "  FROM vendas_xml v JOIN vendas_xml_itens i ON i.venda_id = v.id "
            " WHERE %s" % (_SO_LITRO, _ENTROU, _VIVA), (INI, FIM))
sql_tot = cur.fetchone()

cur.execute("SELECT i.produto_id pid, COUNT(DISTINCT v.id) notas, "
            "       SUM(%s) litros, %s rs "
            "  FROM vendas_xml v JOIN vendas_xml_itens i ON i.venda_id = v.id "
            " WHERE %s GROUP BY i.produto_id" % (_SO_LITRO, _ENTROU, _VIVA),
            (INI, FIM))
sql_prod = {(r['pid'] if r['pid'] is not None else saida_migrada.PID_OUTROS): r
            for r in cur.fetchall()}

cur.execute("SELECT COUNT(*) n, COALESCE(SUM(valor_total),0) rs FROM vendas_xml "
            " WHERE UPPER(situacao) = 'CANCELADA' "
            "   AND DATE(dh_emissao) BETWEEN %s AND %s", (INI, FIM))
sql_cancel = cur.fetchone()

# O periodo ANTERIOR, do mesmo tamanho -- a comparacao dos cards.
_DIAS = (FIM - INI).days + 1
INI_ANT, FIM_ANT = INI - timedelta(days=_DIAS), INI - timedelta(days=1)
cur.execute("SELECT %s rs FROM vendas_xml v "
            "  JOIN vendas_xml_itens i ON i.venda_id = v.id "
            " WHERE %s" % (_ENTROU, _VIVA), (INI_ANT, FIM_ANT))
sql_ant = cur.fetchone()

apurado = saida_migrada.apurar(cur, INI, FIM)
cur.close()
conn.close()

client = app.test_client()
with client.session_transaction() as s:
    s['_user_id'] = '1'
    s['_fresh'] = True

url = ('/relatorios/saidas_migradas?data_inicio=%s&data_fim=%s'
       % (INI.isoformat(), FIM.isoformat()))
r = client.get(url)
html = r.get_data(as_text=True)
open('_smg.html', 'w', encoding='utf-8').write(html)

ok = True


def prova(msg, cond):
    global ok
    ok = ok and bool(cond)
    print(('  OK   ' if cond else '  FALHA') + ' ' + msg)


def perto(a, b, tol=0.01):
    return abs(float(a or 0) - float(b or 0)) < tol


def litros(v):
    return '{:,.0f}'.format(v or 0).replace(',', '.')


def reais(v):
    n = '{:,.2f}'.format(abs(v or 0))
    n = n.replace(',', 'X').replace('.', ',').replace('X', '.')
    return ('-R$ ' if (v or 0) < 0 else 'R$ ') + n


def preco(v):
    return 'R$ ' + ('%.4f' % (v or 0)).replace('.', ',')


g, tot = apurado['geral'], apurado['total']

print('\n1) a tela abre')
prova('HTTP 200 (e nao um redirect para o login)', r.status_code == 200)
prova('e nao caiu no "nao deu para apurar"', 'Não deu para apurar' not in html)
prova('o topo diz de onde vem o numero', 'vem do cupom e da NF-e' in html)
prova('a barra dos migrados marca a pilula Saídas',
      re.search(r'class="on" href="/relatorios/saidas_migradas"', html) is not None)

print('\n2) o motor fecha com o banco, por outro caminho')
prova('litros: motor %s = SQL %s' % (litros(tot['litros']), litros(sql_tot['litros'])),
      perto(tot['litros'], sql_tot['litros'], 0.5))
prova('faturado: motor %s = SQL %s' % (reais(tot['rs']), reais(sql_tot['rs'])),
      perto(tot['rs'], sql_tot['rs']))
prova('notas: motor %d = SQL %d' % (tot['notas'], sql_tot['notas']),
      tot['notas'] == sql_tot['notas'])
prova('itens: motor %d = SQL %d' % (tot['itens'], sql_tot['itens']),
      tot['itens'] == sql_tot['itens'])

print('\n3) o real contado e o que ENTROU, e nao a linha do item')
soma_linha = float(sql_tot['linha'] or 0)
soma_acr = float(sql_tot['acresc'] or 0)
soma_desc = float(sql_tot['desc_'] or 0)
prova('linha (%s) + acrescimo (%s) - desconto (%s) = o total do motor'
      % (reais(soma_linha), reais(soma_acr), reais(soma_desc)),
      perto(tot['rs'], soma_linha + soma_acr - soma_desc))
prova('e o motor NAO e so a linha do item (diferenca de %s)' % reais(soma_acr - soma_desc),
      not perto(tot['rs'], soma_linha) if (soma_acr - soma_desc) else True)
prova('o acrescimo do periodo aparece no motor (%s)' % reais(soma_acr),
      perto(tot['acrescimo'], soma_acr))

print('\n4) os cards, um por um')
prova('a soma dos cards e o total do periodo',
      perto(sum(p['rs'] for p in apurado['produtos']), tot['rs']))
prova('os litros dos cards somam os litros do periodo',
      perto(sum(p['litros'] for p in apurado['produtos']), tot['litros'], 0.5))
prova('as fatias somam 100%',
      perto(sum(p['fatia'] for p in apurado['produtos']), 100, 0.05))
for p in apurado['produtos']:
    s = sql_prod.get(p['pid'])
    prova('%s: %s L e %s fecham com o SQL' % (p['nome'], litros(p['litros']), reais(p['rs'])),
          s is not None and perto(p['litros'], s['litros'], 0.5) and perto(p['rs'], s['rs']))
    if not p['eh_outros']:
        prova('%s: o preco medio e o total dividido pelos litros (%s)'
              % (p['nome'], preco(p['unit'])),
              perto(p['unit'], p['rs'] / p['litros'], 0.0001))
        prova('%s: o preco medio esta entre o menor e o maior' % p['nome'],
              p['menor'] - 0.0001 <= p['unit'] <= p['maior'] + 0.0001)
        prova('%s: o dia a dia soma os litros do card' % p['nome'],
              perto(sum(d['litros'] for d in p['dia_a_dia']), p['litros'], 0.5))

outros = [p for p in apurado['produtos'] if p['eh_outros']]
prova('o card Outros existe e junta o que nao tem produto classificado',
      len(outros) == 1 and outros[0]['pid'] == saida_migrada.PID_OUTROS)
if outros:
    o = outros[0]
    prova('Outros NAO inventa preco medio (sao produtos diferentes, em unidade)',
          o['unit'] is None and o['menor'] is None and o['maior'] is None)
    prova('Outros diz o que tem dentro (%d itens diferentes)' % len(o['lista']),
          len(o['lista']) > 0 and perto(sum(v['rs'] for v in o['lista']), o['rs']))
    prova('e o maior deles aparece na tela', o['lista'][0]['nome'] in html)
    # O que sobra em Outros e produto de loja, vendido em UNIDADE. Dizer "0 L"
    # dele seria mentir de um jeito silencioso -- cada item sai na sua unidade.
    prova('cada item de Outros traz a sua unidade, e nao um litro inventado',
          all((v['unidade'] or '').strip() and v['qtd'] > 0 for v in o['lista']))
    prova('o card de Outros mostra QUANTIDADE, e nao litros (%s)' % o['qtd_rotulo'],
          o['qtd_rotulo'] != '—' and o['qtd_rotulo'] in html)
    prova('e a quantidade de cada item sai impressa na tela',
          all(('%s %s' % ('{:,.0f}'.format(v['qtd']).replace(',', '.'),
                          v['unidade'])) in html for v in o['lista']))

print('\n4b) o ARLA tem card proprio')
arla = [p for p in apurado['produtos'] if p['nome'] == 'ARLA']
prova('o ARLA saiu de dentro de Outros e virou card', len(arla) == 1)
if arla:
    a0 = arla[0]
    prova('o card do ARLA nao e o card Outros', not a0['eh_outros'])
    prova('ele e granel: sai em litro (%s L) e tem preco por litro (%s)'
          % (litros(a0['litros']), preco(a0['unit'])),
          a0['litros'] > 0 and a0['unit'] > 0)
    prova('e nenhum item de Outros ainda e ARLA',
          not any('ARLA' in (v['nome'] or '').upper()
                  for v in (outros[0]['lista'] if outros else [])))

print('\n5) o card TODOS')
prova('os litros do card somam os dos produtos',
      perto(g['litros'], sum(p['litros'] for p in apurado['produtos']), 0.5))
prova('os reais do card somam os dos produtos',
      perto(g['rs'], sum(p['rs'] for p in apurado['produtos'])))
prova('as notas do card sao as notas do periodo (%d)' % g['notas'],
      g['notas'] == sql_tot['notas'])
prova('conta os produtos (%d), sem o Outros' % g['produtos'],
      g['produtos'] == len([p for p in apurado['produtos'] if not p['eh_outros']]))
prova('o dia a dia soma o total em reais',
      perto(sum(d['rs'] for d in g['dia_a_dia']), g['rs']))
prova('o card NAO inventa preco medio de cesta',
      'unit' not in g)
prova('o periodo anterior bate com o SQL (%s)' % reais(sql_ant['rs']),
      perto(g['antes_rs'], sql_ant['rs']))
prova('a variacao e vendido agora menos vendido antes',
      g['delta_rs'] is None or perto(g['delta_rs'], g['rs'] - g['antes_rs']))
prova('o "mais vendido" e mesmo o de maior fatia (%s)' % g['maior'],
      g['maior'] == max((p for p in apurado['produtos'] if not p['eh_outros']),
                        key=lambda p: p['rs'])['nome'])

print('\n6) a nota cancelada fica de fora -- mas contada')
prova('canceladas: motor %d = SQL %d' % (g['canceladas']['notas'], sql_cancel['n']),
      g['canceladas']['notas'] == sql_cancel['n'])
prova('e o valor delas nao entra no faturado',
      perto(tot['rs'], sql_tot['rs']) and float(sql_cancel['rs'] or 0) > 0)

print('\n7) os SETE recortes sao recortes do MESMO faturamento')
for chave, rotulo, icone, pergunta in saida_migrada.RECORTES:
    linhas = apurado['recortes'][chave]
    prova('%s: %d linhas, e a soma delas e o total do periodo'
          % (rotulo, len(linhas)),
          len(linhas) > 0 and perto(sum(l['rs'] for l in linhas), tot['rs']))
    prova('%s: os litros tambem fecham' % rotulo,
          perto(sum(l['litros'] for l in linhas), tot['litros'], 0.5))
    prova('%s: as fatias somam 100%%' % rotulo,
          perto(sum(l['fatia'] for l in linhas), 100, 0.05))
    prova('%s: nenhuma linha vazia (toda linha tem rotulo)' % rotulo,
          all((l['rotulo'] or '').strip() for l in linhas))

print('\n8) o que cada recorte tem de particular')
formas = apurado['recortes']['forma']
prova('as duas grafias do cartao viraram UMA linha ("Cartão Débito")',
      len([l for l in formas if l['rotulo'] == 'Cartão Débito']) == 1)
prova('A+B e B+A sao a mesma combinacao (nenhum rotulo repetido)',
      len(set(l['rotulo'] for l in formas)) == len(formas))
prova('o prazo tem nome de prazo, e nao "Credito Loja/Prazo"',
      any('Prazo' in l['rotulo'] for l in formas))

cli = apurado['recortes']['cliente']
prova('o cupom sem cliente vira UMA linha, e a tela diz o que ela e',
      len([l for l in cli if l['rotulo'] == 'Consumidor não identificado']) == 1)
prova('o cliente identificado leva o documento embaixo do nome',
      any(l['sub'] for l in cli if l['rotulo'] != 'Consumidor não identificado'))

bico = apurado['recortes']['bico']
prova('cada bico diz de qual tanque e produto ele veio',
      all(l['sub'] for l in bico))
prova('o item sem bico (ARLA, oleo, venda faturada) nao some: vira linha',
      any(l['rotulo'] == 'Sem bico no XML' for l in bico))
prova('e os bicos saem em ordem de bomba',
      [l['chave'] for l in bico] == sorted(l['chave'] for l in bico))

caixa = apurado['recortes']['caixa']
prova('a NF-e nao se disfarca de caixa de pista',
      any('NF-e' in l['rotulo'] for l in caixa))

hora = apurado['recortes']['hora']
prova('a hora sai em ordem de relogio, e nao de faturamento',
      [l['chave'] for l in hora] == sorted(l['chave'] for l in hora))

band = apurado['recortes']['bandeira']
prova('"Outros" do XML nao e vendido como se fosse uma bandeira',
      not any(l['rotulo'] == 'Outros' for l in band))

print('\n9) o dia a dia')
dias = apurado['dias']
prova('tem uma linha por dia com venda (%d dias)' % len(dias), len(dias) > 0)
prova('o dia a dia soma o faturado do periodo',
      perto(sum(d['rs'] for d in dias), tot['rs']))
prova('e soma as notas do periodo (sem repetir)',
      sum(d['notas'] for d in dias) == tot['notas'])
prova('o mais novo vem primeiro',
      [d['dia'] for d in dias] == sorted((d['dia'] for d in dias), reverse=True))
prova('cada dia leva para as notas daquele dia em /vendas',
      all(('/vendas?data_ini=%s&amp;data_fim=%s' % (d['dia'], d['dia'])) in html
          for d in dias))
prova('e abre em outra aba', 'class="dia" target="_blank"' in html)

print('\n10) os numeros do motor sao os que a tela imprime')
prova('o faturado do periodo: %s' % reais(g['rs']), reais(g['rs']) in html)
prova('os litros do periodo: %s' % litros(g['litros']), litros(g['litros']) in html)
prova('as notas do periodo: %d' % g['notas'], '>%d<' % g['notas'] in html)
for p in apurado['produtos']:
    prova('%s: %s na tela' % (p['nome'], reais(p['rs'])), reais(p['rs']) in html)
    if not p['eh_outros']:
        prova('%s: preco medio %s na tela' % (p['nome'], preco(p['unit'])),
              preco(p['unit']) in html)
for chave, rotulo, icone, pergunta in saida_migrada.RECORTES:
    prova('a pilula "%s" esta na tela' % rotulo, rotulo in html)

print('\n11) clicar num card filtra o resto da tela')
p0 = [p for p in apurado['produtos'] if not p['eh_outros']][0]
rp = client.get(url + '&pid=%d' % p0['pid'])
hp = rp.get_data(as_text=True)
prova('a tela do %s abre 200' % p0['nome'], rp.status_code == 200)
prova('o card do %s fica aceso' % p0['nome'], 'pc pc--on' in hp or 'pc--on' in hp)
prova('e os outros cards continuam na tela (o seletor nao some)',
      all(p['nome'] in hp for p in apurado['produtos']))
prova('a barra diz o que esta filtrado',
      'os recortes abaixo mostram só o' in hp and p0['nome'] in hp)
prova('e tem o caminho de volta', 'ver todos os produtos' in hp)
prova('o preco medio aparece no recorte quando e de um produto so',
      '—</td>' not in hp.split('Preço médio/L')[1][:400])

conn = get_db_connection()
cur = conn.cursor(dictionary=True)
filtrado = saida_migrada.apurar(cur, INI, FIM, p0['pid'])
cur.close()
conn.close()
prova('com o card escolhido, o recorte passa a somar so aquele produto (%s)'
      % reais(p0['rs']),
      perto(sum(l['rs'] for l in filtrado['recortes']['forma']), p0['rs']))
prova('e os cards continuam mostrando o periodo inteiro',
      perto(sum(p['rs'] for p in filtrado['produtos']), tot['rs']))

print('\n12) a tela nao quebra com o que o usuario faz de errado')
prova('um pid que nao existe nao quebra',
      client.get(url + '&pid=999999').status_code == 200)
prova('um pid podre nao quebra',
      client.get(url + '&pid=xis').status_code == 200)
prova('um recorte que nao existe cai no primeiro',
      client.get(url + '&corte=inventado').status_code == 200)
prova('data fim antes da data inicio nao quebra',
      client.get('/relatorios/saidas_migradas?data_inicio=2026-09-15'
                 '&data_fim=2026-09-01').status_code == 200)
prova('um periodo sem venda nenhuma nao quebra',
      client.get('/relatorios/saidas_migradas?data_inicio=2020-01-01'
                 '&data_fim=2020-01-31').status_code == 200)
prova('o periodo inteiro (5 meses) abre',
      client.get('/relatorios/saidas_migradas?data_inicio=2026-05-01'
                 '&data_fim=%s' % FIM.isoformat()).status_code == 200)

print('\n13) a regua de meses')
conn = get_db_connection()
cur = conn.cursor(dictionary=True)
mm = saida_migrada.meses(cur, FIM)
cur.execute("SELECT DATE_FORMAT(dh_emissao,'%Y-%m') mes, COUNT(*) n FROM vendas_xml "
            " WHERE (situacao IS NULL OR UPPER(situacao) <> 'CANCELADA') "
            " GROUP BY mes ORDER BY mes")
sql_m = {r['mes']: r['n'] for r in cur.fetchall()}
cur.close()
conn.close()
prova('a regua traz os meses que TEM venda, e so eles',
      [m['mes'] for m in mm] == sorted(sql_m))
prova('cada mes leva a sua contagem de notas',
      all(m['notas'] == sql_m[m['mes']] for m in mm))
prova('o mes corrente para hoje, e nao no dia 30',
      all(m['fim'] <= FIM for m in mm))
prova('e as pilulas saem na tela', all(m['rotulo'] in html for m in mm))

print('\n' + ('TUDO PROVADO' if ok else 'TEM FALHA'))
sys.exit(0 if ok else 1)
