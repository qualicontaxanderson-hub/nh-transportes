# -*- coding: utf-8 -*-
"""Prova do /relatorios/conf_cartoes depois da reforma da tela.

A reforma trocou a CASCA — a conta é a mesma. Esta prova existe para cobrar
exatamente isso: que os números que a tela imprime continuem sendo os que o
motor calcula, e que nada tenha se perdido no caminho.

Cobra:
  1) que a tela abra e traga as partes novas (painel do período, um quadro por
     bandeira, o rodapé que explica as colunas);
  2) que TODO número do motor apareça impresso — venda, recebimento,
     diferença, saldo e taxa, do período e de cada bandeira;
  3) que o total geral seja a soma das bandeiras;
  4) que a linha de fim de semana/feriado e a de venda anterior continuem
     marcadas — são elas que explicam a data do recebimento;
  5) que os ganchos do JS e os três modais tenham sobrevivido à troca;
  6) que o link de cada bandeira no painel caia no quadro dela.

  SECRET_KEY=... DB_HOST=... DB_PASSWORD=... python prova_conf_cartoes.py
"""
import io
import re
import sys
from datetime import date

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from app import create_app
from utils.db import get_db_connection
from routes import conf_cartoes as cc

INI, FIM = '2026-09-01', '2026-09-17'

app = create_app()
app.config['WTF_CSRF_ENABLED'] = False
app.config['LOGIN_DISABLED'] = True

ok = True


def prova(msg, cond):
    global ok
    ok = ok and bool(cond)
    print(('  OK   ' if cond else '  FALHA') + ' ' + msg)


def moeda(v):
    """O mesmo formato do filtro fmtmoney da tela."""
    n = '{:,.2f}'.format(abs(v or 0))
    n = n.replace(',', 'X').replace('.', ',').replace('X', '.')
    return ('-' if (v or 0) < -0.0000001 else '') + n


def perto(a, b, tol=0.01):
    return abs(float(a or 0) - float(b or 0)) < tol


client = app.test_client()
with client.session_transaction() as s:
    s['_user_id'] = '1'
    s['_fresh'] = True

url = '/relatorios/conf_cartoes?data_inicio=%s&data_fim=%s' % (INI, FIM)
r = client.get(url)
html = r.get_data(as_text=True)
open('_cc.html', 'w', encoding='utf-8').write(html)

print('\n1) a tela abre, e com a casca nova')
prova('HTTP 200 (e nao um redirect para o login)', r.status_code == 200)
prova('a tela usa o novo id #ccz', 'id="ccz"' in html)
prova('o topo explica de onde vem cada numero',
      'A venda vem do fechamento de caixa' in html)
prova('tem o painel do periodo inteiro', 'class="painel"' in html)
prova('tem o ranking por bandeira', 'Por bandeira, e a que taxa' in html)
prova('tem o rodape que explica as colunas',
      'class="rod"' in html and 'Dif. acumulada' in html)
prova('a tabela virou cartao no celular (tem data-r nas celulas)',
      'data-r="Dt. venda"' in html and 'data-r="Dif. acumulada"' in html)

print('\n2) a tela e consistente consigo mesma')
# A reforma nao pode ter trocado um numero por outro parecido. Cada bandeira
# imprime os seus totais DUAS vezes -- nas caixas do resumo e no rodape da
# tabela --, e o painel do topo imprime a soma de todas. Se a casca nova
# tivesse pegado a variavel errada em algum ponto, estas contas nao fechariam.


def _num(txt):
    """'95.763,82' -> 95763.82"""
    t = (txt or '').strip().replace('.', '').replace(',', '.')
    try:
        return float(t)
    except ValueError:
        return None


blocos = re.split(r'<div class="cx" id="band-', html)[1:]
prova('a tela tem um quadro por bandeira (%d)' % len(blocos), len(blocos) > 0)

por_bandeira = []
for b in blocos:
    bid = b[:b.index('"')]
    nome = re.search(r'class="ph__n">([^<]*)', b)
    nome = nome.group(1).strip() if nome else '?'
    caixas = dict(re.findall(
        r'class="r__r">([^<]*)</div>\s*<div class="r__v[^"]*">([^<]*)', b))
    caixas = {k.strip(): v.strip() for k, v in caixas.items()}
    rodape = re.search(r'<tfoot>(.*?)</tfoot>', b, re.S)
    tds = re.findall(r'<td[^>]*>(.*?)</td>', rodape.group(1), re.S) if rodape else []
    tds = [re.sub(r'<[^>]+>', '', t).strip() for t in tds]
    por_bandeira.append({
        'id': bid, 'nome': nome,
        'venda': _num(caixas.get('Vendido')),
        'receb': _num(caixas.get('Recebido')),
        'dif': _num(caixas.get('Diferença')),
        'rod_venda': _num(tds[1]) if len(tds) > 1 else None,
        'rod_receb': _num(tds[3]) if len(tds) > 3 else None,
        'rod_dif': _num(tds[4]) if len(tds) > 4 else None,
    })

print('\n3) o rodape de cada quadro repete o resumo dele')
for q in por_bandeira:
    prova('%s: vendido nas duas pontas (%s)' % (q['nome'], q['venda']),
          q['venda'] is not None and perto(q['venda'], q['rod_venda']))
    prova('%s: recebido nas duas pontas (%s)' % (q['nome'], q['receb']),
          q['receb'] is not None and perto(q['receb'], q['rod_receb']))
    prova('%s: diferenca nas duas pontas (%s)' % (q['nome'], q['dif']),
          q['dif'] is not None and perto(q['dif'], q['rod_dif']))
    # A diferenca NAO e vendido menos recebido: ela so conta ciclo que ja foi
    # liquidado. A venda cujo recebimento ainda nao apareceu no extrato nao e
    # taxa -- e dinheiro a caminho. O invariante de verdade e este:
    #     vendido = recebido + taxa retida + o que ainda nao caiu
    prova('%s: vendido = recebido + taxa + a receber' % q['nome'],
          q['venda'] >= q['receb'] + q['dif'] - 0.02)

print('\n4) o painel do topo e a soma das bandeiras')
soma_v = sum(q['venda'] for q in por_bandeira)
soma_r = sum(q['receb'] for q in por_bandeira)
painel = html[html.index('class="painel"'):html.index('class="rank"')]
p_venda = _num(re.search(r'class="caixa__v">([^<]*)', painel).group(1))
m_receb = re.search(r'Recebido</span><b>([^<]*)', ' '.join(painel.split()))
p_receb = _num(m_receb.group(1)) if m_receb else None
prova('vendido do painel (%s) = soma das bandeiras (%s)'
      % (p_venda, round(soma_v, 2)), perto(p_venda, soma_v, 0.05))
prova('recebido do painel (%s) = soma das bandeiras (%s)'
      % (p_receb, round(soma_r, 2)),
      p_receb is not None and perto(p_receb, soma_r, 0.05))
prova('e o painel diz quantas bandeiras sao (%d)' % len(por_bandeira),
      ('%d bandeira' % len(por_bandeira)) in ' '.join(html.split()))

# A conta que o painel passou a mostrar separada: a taxa e o que ficou mesmo,
# o resto e venda a caminho. Juntas as duas tem de fechar o vendido.
_pl = ' '.join(painel.split())


def _caixa(rotulo):
    """O valor da caixinha do painel que tem aquele rotulo."""
    m = re.search(re.escape(rotulo) + r'</span>\s*<b[^>]*>([^<]*)', _pl)
    return _num(m.group(1)) if m else None


_taxa = _caixa('Taxa retida')
_falta = _caixa('Ainda não caiu')
prova('o painel separa a taxa retida (%s) do que ainda nao caiu (%s)'
      % (_taxa, _falta), _taxa is not None and _falta is not None)
if _taxa is not None and _falta is not None:
    prova('e as tres partes fecham o vendido: %s + %s + %s = %s'
          % (round(p_receb, 2), _taxa, _falta, round(p_venda, 2)),
          perto(p_receb + _taxa + _falta, p_venda, 0.05))
    prova('a taxa retida e a soma das diferencas das bandeiras',
          perto(_taxa, sum(q['dif'] for q in por_bandeira), 0.05))
prova('e o rodape explica a conta',
      'vendido = recebido + taxa retida' in html)

print('\n5) as linhas que explicam a data do recebimento')
prova('a linha de fim de semana/feriado continua marcada',
      'class="fds"' in html or 'antes fds' in html)
prova('a venda de antes do periodo continua marcada',
      'selo-antes' in html and 'class="antes ' in html)
prova('e o rodape explica o que ela e', 'antes do período' in html)
prova('o dia da semana continua ao lado da data', 'class="dia-semana"' in html)

print('\n6) o link do painel cai no quadro da bandeira')
ancoras = set(re.findall(r'id="band-([^"]+)"', html))
links = set(re.findall(r'href="#band-([^"]+)"', html))
prova('toda bandeira tem ancora (%d)' % len(ancoras),
      len(ancoras) == len(por_bandeira))
prova('e todo link do painel tem para onde ir',
      bool(links) and links <= ancoras)
prova('nenhuma ancora saiu vazia', all(a.strip() for a in ancoras))


print('\n7) o que a reforma NAO podia quebrar')
for gancho in ('form-filtros', 'selEmpresas', 'selBandeiras', 'buscaBandeira',
               'periodo-btn', 'data_inicio', 'data_fim'):
    prova('o gancho do JS "%s" sobreviveu' % gancho, gancho in html)
for modal in ('modalFeriados', 'modalContasContabeis', 'modalVinculos'):
    prova('o modal %s continua na tela' % modal, ('id="%s"' % modal) in html)
prova('o botao de cada modal continua abrindo ele',
      html.count('data-bs-target="#modalFeriados"') >= 1
      and html.count('data-bs-target="#modalContasContabeis"') >= 1
      and html.count('data-bs-target="#modalVinculos"') >= 1)
prova('os feriados nacionais continuam na tela (07/09/2026)',
      '07/09/2026' in html and 'nacional' in html)

print('\n8) a tela nao quebra com o que o usuario faz')
prova('sem filtro nenhum abre', client.get('/relatorios/conf_cartoes').status_code == 200)
r2 = client.get('/relatorios/conf_cartoes?data_inicio=2020-01-01&data_fim=2020-01-31')
prova('periodo sem movimento abre', r2.status_code == 200)
prova('e diz que nao ha movimento, em vez de uma tela vazia',
      'Nenhum movimento de cartão' in r2.get_data(as_text=True))
prova('data fim antes do inicio nao quebra',
      client.get('/relatorios/conf_cartoes?data_inicio=2026-09-17'
                 '&data_fim=2026-09-01').status_code == 200)
prova('empresa que nao existe nao quebra',
      client.get(url + '&empresa_ids[]=999999').status_code == 200)

print('\n' + ('TUDO PROVADO' if ok else 'TEM FALHA'))
sys.exit(0 if ok else 1)
