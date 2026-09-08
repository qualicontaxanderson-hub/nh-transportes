# -*- coding: utf-8 -*-
"""Prova da tela "Meus envios" nos cinco estados que ela tem de distinguir.

A lista de arquivos e a parte facil. O que importa e a caixa de situacao: sem
ela, um robo parado mostra um historico completo e antigo, e a pessoa le isso
como prova de que o sistema perdeu o arquivo dela.
"""
import datetime as dt
import io
import os
import sys

import jinja2

SP = os.path.dirname(os.path.abspath(__file__))
env = jinja2.Environment(loader=jinja2.ChoiceLoader([
    jinja2.FileSystemLoader(os.path.join(SP, 'tpl')),
    jinja2.FileSystemLoader('templates'),
]))
env.globals['url_for'] = lambda ep, **kw: '/' + ep.replace('.', '/')
env.globals['get_flashed_messages'] = lambda **kw: []
tpl = env.get_template('nhrobo/meus_envios.html')

agora = dt.datetime.now()


class D(dict):
    __getattr__ = dict.get


envios = [
    D(id=2, nome_original='extrato teste.xlsx', nome_final='extrato teste.xlsx',
      ext='xlsx', tamanho_bytes=9216, recebido_em=agora - dt.timedelta(minutes=3)),
    D(id=1, nome_original='extrato teste.ofx', nome_final='extrato teste (1).ofx',
      ext='ofx', tamanho_bytes=5120, recebido_em=agora - dt.timedelta(minutes=4)),
]


def est(**kw):
    base = dict(token_prefixo='35f29aba', chave_ativa=1,
                data_inicio_captura=dt.date(2026, 9, 7),
                ultimo_contato=agora, min_sem_contato=0, enviados=2)
    base.update(kw)
    return D(base)


CASOS = [
    ('sem chave', None, envios, 'ainda nao tem chave'),
    ('chave revogada', est(chave_ativa=0), envios, 'esta desligado'),
    ('nunca falou', est(ultimo_contato=None, min_sem_contato=None), [], 'ainda nao falou'),
    ('funcionando', est(min_sem_contato=0), envios, 'esta funcionando'),
    ('calado ha 3h', est(min_sem_contato=185,
                         ultimo_contato=agora - dt.timedelta(minutes=185)),
     envios, 'nao fala com o sistema'),
]

falhas = []
paginas = []
for nome, estado, lista, esperado in CASOS:
    try:
        html = tpl.render(envios=lista, estado=estado, destino='/BANCOS/OFX/NOVO',
                          extensoes=['.ofx', '.xlsx', '.xls', '.xlsm', '.csv', '.pdf'],
                          limite_mb=25)
    except Exception as exc:
        print('FALHA  %-16s explodiu ao renderizar: %s' % (nome, exc))
        falhas.append(nome)
        continue
    # a comparacao ignora acento: o que importa e a frase certa ter saido
    plano = (html.replace('ã', 'a').replace('á', 'a').replace('ç', 'c')
                 .replace('é', 'e').replace('ê', 'e').replace('í', 'i')
                 .replace('ó', 'o').replace('õ', 'o').replace('ú', 'u'))
    ok = esperado in plano
    print(('OK   ' if ok else 'FALHA') + '  %-16s -> esperava "%s"' % (nome, esperado))
    if not ok:
        falhas.append(nome)
    paginas.append((nome, html))

# a lista de arquivos, no caso normal
html = paginas[3][1] if len(paginas) > 3 else ''
for termo, msg in [('extrato teste.ofx', 'lista o arquivo'),
                   ('extrato teste (1).ofx', 'diz o nome com que foi guardado'),
                   ('o nome ja estava ocupado'.replace('ja', 'já'), 'explica a troca de nome'),
                   ('_NH-ROBO - o que foi enviado.txt', 'aponta para o recibo da pasta'),
                   ('07/09/2026', 'mostra a data de corte')]:
    ok = termo in html
    print(('OK   ' if ok else 'FALHA') + '  %s' % msg)
    if not ok:
        falhas.append(msg)

# uma pagina por estado, para olhar
saida = ['<style>body{margin:0;background:#eef1f5}h2{font:700 13px system-ui;'
         'background:#151d27;color:#fff;margin:0;padding:6px 12px}</style>']
for nome, html in paginas:
    corpo = html.split('<body', 1)[-1].split('>', 1)[-1].rsplit('</body>', 1)[0]
    saida.append('<h2>%s</h2>' % nome)
    saida.append('<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/'
                 'bootstrap@5.3.3/dist/css/bootstrap.min.css">')
    saida.append(html)
io.open(os.path.join(SP, 'render-meus-envios.html'), 'w',
        encoding='utf-8').write('\n'.join(saida))

print('\n%d falha(s)' % len(falhas))
sys.exit(1 if falhas else 0)
