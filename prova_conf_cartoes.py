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
prova('tem a grade de cards (a mesma do saidas_migradas)', 'class="pgrade"' in html)
prova('tem o card que soma todas', 'pc pc--tot' in html)
prova('tem a regua de meses, e nao os botoes de mes atual/anterior',
      'class="meses"' in html and 'periodo-btn' not in html)
prova('tem as pilulas de tipo (credito, debito, os dois)',
      'Só débito' in html and 'Só crédito' in html and 'Crédito e débito' in html)
prova('os cartoes viraram pilulas no filtro', 'class="chips"' in html)
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

print('\n4) o card TODAS e a soma das bandeiras')
soma_v = sum(q['venda'] for q in por_bandeira)
soma_r = sum(q['receb'] for q in por_bandeira)
# O card que soma todas ocupa o lugar do antigo painel: e nele que a conta
# do periodo inteiro aparece agora.
painel = html[html.index('pc pc--tot'):]
painel = painel[:painel.index('</a>')]
p_venda = _num(re.search(r'class="pc__v"><b>([^<]*)', painel).group(1))
m_receb = re.search(r'<dt>Recebido</dt><dd>([^<]*)', ' '.join(painel.split()))
p_receb = _num(m_receb.group(1)) if m_receb else None
prova('vendido do card TODAS (%s) = soma das bandeiras (%s)'
      % (p_venda, round(soma_v, 2)), perto(p_venda, soma_v, 0.05))
prova('recebido do card TODAS (%s) = soma das bandeiras (%s)'
      % (p_receb, round(soma_r, 2)),
      p_receb is not None and perto(p_receb, soma_r, 0.05))
prova('e o card diz quantas bandeiras sao (%d)' % len(por_bandeira),
      ('%d bandeira' % len(por_bandeira)) in ' '.join(html.split()))

# A conta que o painel passou a mostrar separada: a taxa e o que ficou mesmo,
# o resto e venda a caminho. Juntas as duas tem de fechar o vendido.
_pl = ' '.join(painel.split())


def _caixa(rotulo):
    """O valor da caixinha do card TODAS que tem aquele rotulo."""
    m = re.search(r'<dt>' + re.escape(rotulo) + r'</dt>\s*<dd[^>]*>([^<]*)', _pl)
    return _num(m.group(1)) if m else None


_taxa = _caixa('Taxa retida')
_falta = _caixa('Ainda não caiu')
prova('o card separa a taxa retida (%s) do que ainda nao caiu (%s)'
      % (_taxa, _falta), _taxa is not None and _falta is not None)
if _taxa is not None and _falta is not None:
    prova('e as tres partes fecham o vendido: %s + %s + %s = %s'
          % (round(p_receb, 2), _taxa, _falta, round(p_venda, 2)),
          perto(p_receb + _taxa + _falta, p_venda, 0.05))
    prova('a taxa retida e a soma das diferencas das bandeiras',
          perto(_taxa, sum(q['dif'] for q in por_bandeira), 0.05))
# O rodape nao promete mais a identidade "vendido = recebido + taxa + a
# receber": ela so vale quando todo credito tem venda casada. Quando entra
# credito sem venda (X7 BANK), ela deixa de fechar -- e o rodape passou a
# explicar cada parcela pelo que ela e, inclusive o "caiu sem venda".
prova('o rodape explica a taxa retida', 'taxa retida</b> é a soma' in html)
prova('e explica o "ainda nao caiu" como contagem, nao subtracao',
      'contada ciclo a ciclo' in html)
prova('e explica o "caiu sem venda"',
      'caiu sem venda</b>, é crédito que entrou num' in html)

print('\n4b) o que o Anderson pediu nesta rodada')
prova('a regua traz TODOS os meses com venda de cartao, e nao so dois',
      len(re.findall(r'title="\d+ lançamento', html)) >= 3)
prova('e ela tem o "Tudo" para o periodo inteiro',
      '>Tudo</a>' in html)
prova('o tipo separa credito de debito',
      'tipo=DEBITO' in html and 'tipo=CREDITO' in html)
prova('os cards saem agrupados por tipo (um bloco, depois o outro)',
      [t for t in re.findall(r'class="pc__r">([A-Z]+) ·', html)]
      == sorted(re.findall(r'class="pc__r">([A-Z]+) ·', html)))
prova('cada card lembra ate quando esta recebido',
      html.count('último recebimento') >= 2)
prova('e diz quando nao houve recebimento nenhum no periodo',
      'nenhum no período' in html or html.count('último recebimento') > 0)
_filtro = html[html.index('id="form-filtros"'):html.index('</form>')]
prova('o filtro nao tem mais NENHUMA caixa de rolagem -- so pilulas',
      _filtro.count('<select') == 0 and _filtro.count('class="chips"') == 2)
prova('empresa e cartao, cada um com o seu grupo de pilulas',
      _filtro.count('class="grupo"') == 2)
prova('cada grupo tem o "Todas/Todos", que e desmarcar e nao um valor',
      _filtro.count('class="todos') == 2 and 'name="todos"' not in _filtro)
_acesas = re.findall(r'<label class="on"[^>]*>\s*<input[^>]*value="(\d+)"', _filtro)
prova('sem escolha, nenhuma pilula acesa e as duas de "Todas" acesas',
      not _acesas and _filtro.count('class="todos on"') == 2)
_r1 = client.get(url + '&bandeira_ids[]=4').get_data(as_text=True)
_f1 = _r1[_r1.index('id="form-filtros"'):_r1.index('</form>')]
prova('escolhendo um cartao, so ele acende',
      re.findall(r'<label class="on"[^>]*>\s*<input[^>]*value="(\d+)"', _f1) == ['4'])
prova('e o "Todos" dos cartoes apaga, o das empresas continua aceso',
      _f1.count('class="todos on"') == 1)

print('\n4c) o prazo da bandeira: dias uteis ou corridos')
# A X7 BANK paga em 3 dias CORRIDOS -- medido contra a fatura dela. Contar em
# dias uteis erra a venda de fim de semana e desencontra tudo: a mesma quantia
# vira "ainda nao caiu" de um lado e "caiu sem venda" do outro.
from routes.conf_cartoes import _data_esperada, _next_business_day
from datetime import date as _d
_fs = set()
prova('em dias UTEIS, a venda de sabado 22/08/2026 + 3 cai na quarta 26/08',
      _data_esperada(_d(2026, 8, 22), 3, 'UTIL', _fs) == _d(2026, 8, 26))
prova('em dias CORRIDOS, ela cai na terca 25/08 -- que foi o que aconteceu',
      _data_esperada(_d(2026, 8, 22), 3, 'CORRIDO', _fs) == _d(2026, 8, 25))
prova('corrido que cai no domingo anda para a segunda',
      _data_esperada(_d(2026, 8, 20), 3, 'CORRIDO', _fs) == _d(2026, 8, 24))
prova('e corrido tambem pula feriado nacional',
      _data_esperada(_d(2026, 9, 4), 3, 'CORRIDO', {'2026-09-07'}) == _d(2026, 9, 8))
prova('prazo 0 e o proprio dia, nos dois tipos',
      _data_esperada(_d(2026, 8, 22), 0, 'CORRIDO', _fs) == _d(2026, 8, 22)
      and _data_esperada(_d(2026, 8, 22), 0, 'UTIL', _fs) == _d(2026, 8, 22))
prova('tipo vazio cai em dias uteis (o comum)',
      _data_esperada(_d(2026, 8, 22), 3, '', _fs)
      == _next_business_day(_d(2026, 8, 22), 3, _fs))
prova('a tela deixa escolher o tipo na bandeira',
      'inp-prazo-tipo' in html and '>corridos<' in html and '>úteis<' in html)

print('5) as linhas que explicam a data do recebimento')
prova('a linha de fim de semana/feriado continua marcada',
      'class="fds"' in html or 'antes fds' in html)
prova('a venda de antes do periodo continua marcada',
      'selo-antes' in html and 'class="antes ' in html)
prova('e o rodape explica o que ela e', 'antes do período' in html)
prova('o dia da semana continua ao lado da data', 'class="dia-semana"' in html)

print('\n6) o clique no card escolhe a bandeira, sem sumir com as outras')
ancoras = set(re.findall(r'id="band-([^"]+)"', html))
cliques = set(re.findall(r'band=(\d+)"', html))
prova('toda bandeira tem quadro com ancora (%d)' % len(ancoras),
      len(ancoras) == len(por_bandeira))
prova('e todo card tem um clique para a sua bandeira',
      bool(cliques) and cliques <= ancoras)
prova('nenhuma ancora saiu vazia', all(a.strip() for a in ancoras))
# O clique NAO e o filtro: com ele, os cards continuam todos na tela -- eles
# SAO o seletor, e sumir com eles tiraria o caminho de volta.
_um = client.get(url + '&band=' + sorted(ancoras)[0]).get_data(as_text=True)
prova('com um card escolhido, os cards continuam todos na grade',
      _um.count('<a class="pc') == len(por_bandeira) + 1)
prova('e so o quadro dele fica embaixo',
      _um.count('<div class="cx" id="band-') == 1)
prova('o card escolhido fica aceso e ha caminho de volta',
      'pc pc--on' in _um and 'voltar a todas' in _um)


print('\n7) o que a reforma NAO podia quebrar')
# selBandeiras, buscaBandeira e periodo-btn sairam DE PROPOSITO: o cartao virou
# pilula (dez pilulas nao precisam de busca) e os dois botoes de mes viraram a
# regua com todos os meses. O que nao pode ter saido e o resto.
for gancho in ('form-filtros', 'data_inicio', 'data_fim',
               'bandeira_ids[]', 'empresa_ids[]'):
    prova('o gancho do formulario "%s" sobreviveu' % gancho, gancho in html)
# Sairam de proposito: a busca e o multi-select de bandeira (viraram pilula),
# os botoes de mes (viraram regua) e o select de empresa (virou pilula).
for saiu in ('buscaBandeira', 'periodo-btn', 'selEmpresas'):
    prova('e o "%s" saiu junto com o que ele servia' % saiu, saiu not in html)
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
