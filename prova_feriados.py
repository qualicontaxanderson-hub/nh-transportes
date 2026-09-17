# -*- coding: utf-8 -*-
"""Prova dos feriados nacionais do /relatorios/conf_cartoes.

Feriado aqui nao e enfeite: ele empurra a data em que o cartao cai na conta.
Um 07/09 tratado como dia util credita o dinheiro um dia antes do que o banco
credita, e a conferencia acusa diferenca onde nao ha.

Cobra:
  1) que as datas calculadas sejam as datas certas (Pascoa e os fixos);
  2) que a Consciencia Negra so exista de 2024 em diante (Lei 14.759/2023);
  3) que a conta de dia util pule o feriado nacional -- o caso real do
     07/09/2026, que caiu numa segunda;
  4) que a tela mostre o nacional sem botao de excluir, e o manual com;
  5) que as DUAS telas que fazem essa conta (conf_cartoes e bank_import)
     enxerguem o mesmo conjunto de feriados.

  SECRET_KEY=... DB_HOST=... DB_PASSWORD=... python prova_feriados.py
"""
import io
import re
import sys
from datetime import date

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from app import create_app
from utils import feriados as fer
from utils.db import get_db_connection
from routes.conf_cartoes import _get_feriados, _next_business_day

app = create_app()
app.config['WTF_CSRF_ENABLED'] = False
app.config['LOGIN_DISABLED'] = True

ok = True


def prova(msg, cond):
    global ok
    ok = ok and bool(cond)
    print(('  OK   ' if cond else '  FALHA') + ' ' + msg)


print('\n1) a Pascoa, de onde sai a Sexta-feira Santa')
# Datas publicas, conferiveis em qualquer calendario.
PASCOAS = {2023: date(2023, 4, 9), 2024: date(2024, 3, 31), 2025: date(2025, 4, 20),
           2026: date(2026, 4, 5), 2027: date(2027, 3, 28), 2028: date(2028, 4, 16)}
for ano, esperada in PASCOAS.items():
    prova('Pascoa de %d = %s' % (ano, esperada), fer.pascoa(ano) == esperada)

print('\n2) a Sexta-feira Santa e a Pascoa menos dois dias, e cai numa sexta')
for ano in PASCOAS:
    sexta = [d for d, n in fer.nacionais(ano).items() if n == 'Sexta-feira Santa'][0]
    prova('%d: %s e sexta-feira' % (ano, sexta), sexta.weekday() == 4)
prova('2026: a Sexta-feira Santa e 03/04 -- a mesma data que o Anderson ja '
      'tinha cadastrado a mao',
      date(2026, 4, 3) in fer.nacionais(2026))

print('\n3) os fixos, e o que NAO entra')
n26 = fer.nacionais(2026)
for dia, nome in [((1, 1), 'Confraternização Universal'), ((4, 21), 'Tiradentes'),
                  ((5, 1), 'Dia do Trabalho'), ((9, 7), 'Independência'),
                  ((10, 12), 'Nossa Senhora Aparecida'), ((11, 2), 'Finados'),
                  ((11, 15), 'Proclamação da República'), ((12, 25), 'Natal')]:
    d = date(2026, dia[0], dia[1])
    prova('%s e %s' % (d.strftime('%d/%m'), nome), n26.get(d) == nome)
prova('o 07/09/2026 e feriado nacional (era o exemplo do pedido)',
      date(2026, 9, 7) in n26)
# Estadual e municipal NAO entram: a praca do posto pode parar, mas quem
# processa o cartao costuma estar em outro estado, onde o dia foi util.
prova('Carnaval NAO entra sozinho (e ponto facultativo, nao feriado nacional)',
      date(2026, 2, 16) not in n26 and date(2026, 2, 17) not in n26)
prova('Corpus Christi NAO entra sozinho (idem)', date(2026, 6, 4) not in n26)
prova('nao ha feriado estadual/municipal na lista (sao 10 datas em 2026)',
      len(n26) == 10)

print('\n4) a Consciencia Negra so e nacional de 2024 em diante')
prova('2023 NAO tem (a lei e de dezembro de 2023)',
      'Consciência Negra' not in fer.nacionais(2023).values())
prova('2024 tem', 'Consciência Negra' in fer.nacionais(2024).values())
prova('2026 tem', 'Consciência Negra' in n26.values())
prova('e 2023 tem uma data a menos que 2024',
      len(fer.nacionais(2023)) == len(fer.nacionais(2024)) - 1)

print('\n5) a conta de dia util pula o feriado -- o caso do 07/09/2026')
# 07/09/2026 caiu numa SEGUNDA. Uma venda na sexta 04/09 com prazo de 1 dia
# util nao cai na segunda: cai na terca 08/09.
prova('07/09/2026 e uma segunda-feira', date(2026, 9, 7).weekday() == 0)
_set = fer.set_iso(2026, 2026)
prova('venda 04/09 (sex) + 1 dia util = 08/09 (ter), e nao 07/09',
      _next_business_day(date(2026, 9, 4), 1, _set) == date(2026, 9, 8))
prova('sem o feriado na conta, daria 07/09 -- a data errada',
      _next_business_day(date(2026, 9, 4), 1, set()) == date(2026, 9, 7))
# E o Natal de 2026, que cai numa sexta: venda na quinta 24/12 + 1 = 28/12 (seg)
prova('venda 24/12/2026 (qui) + 1 dia util = 28/12 (seg), pulando Natal e '
      'fim de semana',
      _next_business_day(date(2026, 12, 24), 1, _set) == date(2026, 12, 28))

print('\n6) o que a tela mostra')
conn = get_db_connection()
linhas, conjunto = _get_feriados(conn, 2026, 2026)
conn.close()
prova('a lista de 2026 traz os 10 nacionais',
      len([f for f in linhas if f['nacional']]) == 10)
prova('e so de 2026 (a tela nao vira uma lista de tres anos para rolar)',
      all(f['data_iso'][:4] == '2026' for f in linhas))
prova('o 07/09/2026 esta na lista, marcado como nacional',
      any(f['data_iso'] == '2026-09-07' and f['nacional'] for f in linhas))
prova('o nacional sem cadastro manual nao tem id -- e o que tira a lixeira '
      'da tela',
      all(f['id'] is None
          for f in linhas if f['nacional'] and f['data_iso'] == '2026-09-07'))
prova('o cadastro manual continua na lista e continua excluivel',
      any((not f['nacional']) and f['id'] for f in linhas))
# O SET vai alem do que a tela lista: o prazo atravessa o virar do ano.
prova('a conta enxerga o 01/01/2027, mesmo a tela listando so 2026',
      '2027-01-01' in conjunto)
prova('e o 25/12/2025, para tras', '2025-12-25' in conjunto)

print('\n7) a tela de verdade')
client = app.test_client()
with client.session_transaction() as s:
    s['_user_id'] = '1'
    s['_fresh'] = True
r = client.get('/relatorios/conf_cartoes?data_inicio=2026-09-01&data_fim=2026-09-17')
html = r.get_data(as_text=True)
open('_cc.html', 'w', encoding='utf-8').write(html)
prova('a tela abre 200', r.status_code == 200)
corpo = re.search(r'<tbody id="tbl-feriados-body">(.*?)</tbody>', html, re.S)
prova('a tabela de feriados existe', corpo is not None)
if corpo:
    trs = re.findall(r'<tr.*?</tr>', corpo.group(1), re.S)
    def _texto(t):
        return ' '.join(re.sub(r'<[^>]+>', ' ', t).split())
    linha_0709 = [t for t in trs if '07/09/2026' in _texto(t)]
    prova('o 07/09/2026 aparece na tela', len(linha_0709) == 1)
    if linha_0709:
        prova('com o nome "Independência" e o selo "nacional"',
              'Independência' in _texto(linha_0709[0])
              and 'nacional' in _texto(linha_0709[0]))
        prova('e SEM botao de excluir (ele nao esta cadastrado, e calculado)',
              'btn-feriado-del' not in linha_0709[0])
    carnaval = [t for t in trs if '16/02/2026' in _texto(t)]
    prova('o Carnaval cadastrado a mao continua na tela',
          len(carnaval) == 1 and 'CARNAVAL' in _texto(carnaval[0]))
    prova('e continua com botao de excluir',
          carnaval and 'btn-feriado-del' in carnaval[0])
prova('a tela explica que o municipal/estadual nao entra',
      'municipal ou estadual não entra' in html)

print('\n8) as duas telas que fazem essa conta enxergam o mesmo')
# bank_import monta o proprio set para calcular a data esperada do credito.
# Se ele nao tivesse os nacionais, o 07/09 seria feriado numa tela e dia util
# na outra -- e a mesma venda teria duas datas de credito.
fonte = io.open('routes/bank_import.py', encoding='utf-8').read()
prova('bank_import usa utils.feriados (e nao so a tabela)',
      'from utils import feriados as _fer_br' in fonte
      and '_feriados_set |= _fer_br.set_iso' in fonte)
prova('e conf_cartoes usa a mesma fonte',
      'from utils import feriados as feriados_br'
      in io.open('routes/conf_cartoes.py', encoding='utf-8').read())

print('\n' + ('TUDO PROVADO' if ok else 'TEM FALHA'))
sys.exit(0 if ok else 1)
