# -*- coding: utf-8 -*-
"""Testa o relatorio Fornecedores x Compras DFe SEM banco e SEM Flask.

Existe por causa de um bug que foi pro ar: uma query com tres %s foi formatada
com um valor so, e o TypeError virou 500 na cara do usuario. A checagem que
pega essa familia inteira de erro e simples — o numero de %s no SQL tem de ser
igual ao numero de parametros — e nao precisa de banco nenhum.

Uso:
    python scripts/testar_conf_fornecedores_dfe.py
"""
import importlib.util
import os
import sys
import types
from datetime import date, datetime

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ── stubs ─────────────────────────────────────────────────────────────────────

class Linha(dict):
    """Serve tanto pra row['coluna'] quanto pro fetchone()[0] das contagens.

    Precisa vir PREENCHIDA: com dict vazio o `if not nota: return 404` cortava
    a rota antes da segunda consulta, e o teste passava sem testar nada.
    """

    _PADRAO = {
        'id': 1, 'numero': '838', 'serie': '2', 'valor': 8700.0, 'outros': 0.0,
        'vinculado': 0.0, 'emit_cnpj': '02284585000144', 'fornecedor_id': 5,
        'cnpj_forn': '02284585000144', 'total': 0.0, 'usado': 0.0, 'notas': 0,
        'dh_emissao': datetime(2026, 8, 1, 9, 0),
        'data_transacao': date(2026, 7, 31),
        'descricao': 'PIX', 'primeira': None, 'ultima': None,
    }

    def __init__(self):
        dict.__init__(self, Linha._PADRAO)

    def __getitem__(self, chave):
        if isinstance(chave, int):
            return 1          # fetchone()[0] das contagens: tabela "existe"
        return dict.get(self, chave, None)


class FakeCursor:
    def __init__(self, log):
        self.log = log
        self.rowcount = 1

    def execute(self, sql, params=None):
        self.log.append((sql, params))

    def fetchall(self):
        return []

    def fetchone(self):
        return Linha()

    def close(self):
        pass


class FakeConn:
    def __init__(self):
        self.log = []

    def cursor(self, dictionary=False):
        return FakeCursor(self.log)

    def commit(self):
        pass

    def close(self):
        pass


CONEXOES = []


def _conn():
    c = FakeConn()
    CONEXOES.append(c)
    return c


class FakeArgs:
    def get(self, k, d=None):
        return d

    def getlist(self, k):
        return []


def montar_stubs():
    flask = types.ModuleType('flask')
    flask.Blueprint = lambda *a, **k: types.SimpleNamespace(
        route=lambda *a, **k: (lambda f: f))
    flask.render_template = lambda *a, **k: ('render', k)
    flask.jsonify = lambda **k: k
    flask.request = types.SimpleNamespace(args=FakeArgs(),
                                          get_json=lambda silent=False: {})
    sys.modules['flask'] = flask

    fl = types.ModuleType('flask_login')
    fl.login_required = lambda f: f
    fl.current_user = types.SimpleNamespace(id=1)
    sys.modules['flask_login'] = fl

    sys.modules.setdefault('routes', types.ModuleType('routes'))
    auth = types.ModuleType('routes.auth')
    auth.admin_required = lambda f: f
    sys.modules['routes.auth'] = auth

    sys.modules.setdefault('utils', types.ModuleType('utils'))
    db = types.ModuleType('utils.db')
    db.get_db_connection = _conn
    sys.modules['utils.db'] = db


# ── testes ────────────────────────────────────────────────────────────────────

def conferir_placeholders(log, onde):
    """%s no SQL tem de bater com a quantidade de parametros."""
    for sql, params in log:
        n = sql.count('%s')
        p = len(params) if params else 0
        assert n == p, (
            "%s: %d placeholder(s) para %d parametro(s)\n%s" % (onde, n, p, sql))


def main():
    montar_stubs()
    spec = importlib.util.spec_from_file_location(
        'cfd', os.path.join(RAIZ, 'routes', 'conf_fornecedores_dfe.py'))
    cfd = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cfd)

    # 1) Cada consulta isolada, inclusive com filtros ligados (que injetam
    #    placeholders a mais — outra fonte da mesma classe de bug).
    casos = [
        ('_empresas',                 lambda c: cfd._empresas(c)),
        ('_fornecedores',             lambda c: cfd._fornecedores(c)),
        ('_cnpjs_duplicados',         lambda c: cfd._cnpjs_duplicados(c)),
        ('_janela_captura',           lambda c: cfd._janela_captura(c)),
        ('_tem_tabela_vinculo',       lambda c: cfd._tem_tabela_vinculo(c)),
        ('_garante_tabela_vinculo',   lambda c: cfd._garante_tabela_vinculo(c)),
        ('_notas_anteriores',         lambda c: cfd._notas_anteriores(c, '2026-08-01', [], [])),
        ('_notas_anteriores+filtros', lambda c: cfd._notas_anteriores(c, '2026-08-01', ['1', '2'], ['7'])),
        ('_pagamentos_anteriores',    lambda c: cfd._pagamentos_anteriores(c, '2026-08-01', ['1'], ['7'])),
        ('_notas_periodo',            lambda c: cfd._notas_periodo(c, '2026-08-01', '2026-08-12', [], [])),
        ('_notas_periodo+filtros',    lambda c: cfd._notas_periodo(c, '2026-08-01', '2026-08-12', ['1'], ['7', '9'])),
        ('_pagamentos_periodo',       lambda c: cfd._pagamentos_periodo(c, '2026-08-01', '2026-08-12', ['1'], ['7'])),
        ('_notas_sem_fornecedor',     lambda c: cfd._notas_sem_fornecedor(c, '2026-08-01', '2026-08-12', ['1'])),
        ('_pagamentos_antes_corte',   lambda c: cfd._pagamentos_antes_do_corte(c, ['1'], ['7'])),
        ('_vinculos',                 lambda c: cfd._vinculos(c, [10, 11, 12])),
        ('_pag_vinculados_fora',      lambda c: cfd._pagamentos_vinculados_fora(c, [10, 11, 12],
                                                                               '2026-08-01', '2026-08-12')),
    ]
    for nome, fn in casos:
        conn = FakeConn()
        fn(conn)
        conferir_placeholders(conn.log, nome)
        print('OK  %-28s %d consulta(s)' % (nome, len(conn.log)))

    # 2) A rota inteira, que e onde o 500 apareceu.
    del CONEXOES[:]
    cfd.conf_fornecedores_dfe()
    total = sum(len(c.log) for c in CONEXOES)
    for c in CONEXOES:
        conferir_placeholders(c.log, 'conf_fornecedores_dfe')
    print('OK  %-28s %d consulta(s)' % ('rota completa', total))

    # 3) Endpoints de escrita.
    corpo = {'doc_id': 1, 'transacao_id': 9, 'valor': 8700.0,
             'vinculo_id': 3, 'ok': True}
    sys.modules['flask'].request.get_json = lambda silent=False: corpo

    esperado = {'candidatos': 2, 'vincular': 3, 'conferir': 1, 'desvincular': 1}
    for nome, fn in (('conferir', cfd.conferir),
                     ('vincular', cfd.vincular),
                     ('desvincular', cfd.desvincular),
                     ('candidatos', lambda: cfd.candidatos(1))):
        del CONEXOES[:]
        fn()
        n = sum(len(c.log) for c in CONEXOES)
        for c in CONEXOES:
            conferir_placeholders(c.log, nome)
        # Sem isto o teste "passava" sem chegar na consulta que interessa.
        assert n >= esperado[nome], (
            '%s rodou %d consulta(s), esperava ao menos %d — o teste saiu cedo '
            'demais e nao cobriu o SQL de verdade' % (nome, n, esperado[nome]))
        print('OK  %-28s %d consulta(s)' % (nome, n))

    print('\nTudo certo: nenhum SQL com placeholder sobrando ou faltando.')


if __name__ == '__main__':
    main()
