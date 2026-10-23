"""
O que os adapters de extrato por API têm em comum — UMA implementação só.

Cada banco (sicoob_extrato, cora_extrato, ...) só sabe o que é dele: URLs,
de onde vem o certificado, o formato da resposta e como o OFX daquele banco
escreve o texto. O resto mora aqui e não se repete:

  * mTLS: SessaoMTLS, sobre o montar_sessao_mtls de scripts/consulta_sefaz
    (o mesmo da captura de DFe) — nenhum adapter monta contexto TLS;
  * token OAuth2 client_credentials em cache, com margem;
  * HTTP com retry só para falha transitória;
  * comparação com o que o OFX já gravou em bank_transactions.

SÓ LEITURA: nada aqui grava no banco de dados.
"""
import logging
import os
import re
import sys
import threading
import time
import unicodedata
from collections import defaultdict
from datetime import date, timedelta

import requests

logger = logging.getLogger(__name__)

# Quem espera é uma pessoa na tela, e o app tem só 2 workers (start.sh): uma
# consulta presa segura metade do sistema. Pior caso: 25 + 2 + 25 s.
TIMEOUT = (8, 25)
TENTATIVAS = 2              # rede, 429 e 5xx; 401/403 nunca repete
BACKOFF_BASE = 2
MARGEM_TOKEN = 60           # renova 60s antes de vencer (Sicoob: 300s; Cora: 24h)


class BancoError(Exception):
    """Falha de transporte ou resposta inesperada do banco."""


class BancoAuthError(BancoError):
    """401/403 — client_id, escopo ou certificado recusado."""


class SemCredencial(BancoError):
    """Falta client_id ou certificado — problema de cadastro, não de rede."""


class TransacaoInvalida(BancoError):
    """Transação num formato desconhecido — não se adivinha."""


def _consulta_sefaz():
    """scripts/consulta_sefaz, como o routes/dfe_compras importa."""
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for p in (raiz, os.path.join(raiz, 'scripts')):
        if p not in sys.path:
            sys.path.insert(0, p)
    import consulta_sefaz
    return consulta_sefaz


def env_obrigatoria(nome):
    v = (os.getenv(nome) or '').strip()
    if not v:
        raise SemCredencial(f'{nome} não definida.')
    return v


# ---------------------------------------------------------------------------
# mTLS
# ---------------------------------------------------------------------------
class SessaoMTLS:
    """Uma sessão mTLS NOVA por chamada.

    O contexto pyOpenSSL do AdaptadorCertMemoria não pode ser reusado depois
    de abrir uma conexão, e aqui são pelo menos duas (token e extrato). A
    captura de DFe nunca tropeçou nisso porque faz uma requisição por sessão.
    """

    def __init__(self, cert, chave_priv, cadeia):
        self._material = (cert, chave_priv, cadeia or [])

    def request(self, metodo, url, **kw):
        s = _consulta_sefaz().montar_sessao_mtls(*self._material)
        try:
            return s.request(metodo, url, **kw)
        finally:
            s.close()


def sessao_do_a1(cliente_id):
    """A1 ICP-Brasil do cadastro do DFe: Dropbox -> senha -> PFX em memória."""
    cs = _consulta_sefaz()
    regs = cs._selecionar_ativos(cliente_id=cliente_id)
    if not regs:
        raise SemCredencial(f'Nenhum certificado ativo para cliente_id={cliente_id}.')
    try:
        _cid, _doc, cert, chave_priv, cadeia = cs._abrir_registro(regs[0])
    except RuntimeError as exc:
        raise SemCredencial(str(exc)) from exc
    return SessaoMTLS(cert, chave_priv, cadeia)


def _pem(valor, nome):
    """Conteúdo PEM direto na variável, ou o caminho de um arquivo com ele."""
    v = (valor or '').strip()
    if v.startswith('-----BEGIN'):
        # Painéis que não aceitam quebra de linha costumam gravar '\n' literal.
        return v.replace('\\n', '\n').encode()
    if v and os.path.isfile(v):
        with open(v, 'rb') as f:
            return f.read()
    raise SemCredencial(f'{nome}: esperado o conteúdo PEM (-----BEGIN ...) ou o caminho do arquivo.')


def sessao_de_pem(env_cert, env_chave):
    """Certificado + chave privada em PEM (o par que o banco gera, não ICP-Brasil)."""
    from cryptography import x509
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    cert_pem = _pem(env_obrigatoria(env_cert), env_cert)
    chave_pem = _pem(env_obrigatoria(env_chave), env_chave)
    try:
        certs = x509.load_pem_x509_certificates(cert_pem)
        chave = load_pem_private_key(chave_pem, password=None)
    except ValueError as exc:
        raise SemCredencial(f'Certificado/chave em {env_cert}/{env_chave} ilegível: {exc}') from exc
    # O arquivo pode trazer a cadeia junto: o primeiro é o do cliente.
    return SessaoMTLS(certs[0], chave, certs[1:])


# ---------------------------------------------------------------------------
# Token OAuth2 client_credentials, em cache
# ---------------------------------------------------------------------------
_tokens = {}                # (url_token, client_id, escopo) -> (token, vale_ate_monotonic)
_trava_token = threading.Lock()


def obter_token(sessao, url_token, client_id, escopo=None, rotulo='banco'):
    """Token que ainda vale por pelo menos MARGEM_TOKEN segundos.

    time.monotonic e não relógio de parede: ajuste de hora no servidor não
    pode fazer um token vencido parecer bom.
    """
    chave = (url_token, client_id, escopo or '')
    with _trava_token:
        guardado = _tokens.get(chave)
        if guardado and time.monotonic() < guardado[1]:
            return guardado[0]
        form = {'grant_type': 'client_credentials', 'client_id': client_id}
        if escopo:
            form['scope'] = escopo
        d = json_(chamar(sessao, 'POST', url_token, rotulo=rotulo, data=form), rotulo)
        token = d.get('access_token')
        if not token:
            raise BancoError(f'{rotulo}: resposta do token sem access_token: {sorted(d)}')
        try:
            dura = int(d.get('expires_in') or 300)
        except (TypeError, ValueError):
            dura = 300
        _tokens[chave] = (token, time.monotonic() + max(0, dura - MARGEM_TOKEN))
        return token


def esquecer_token(url_token, client_id, escopo=None):
    with _trava_token:
        _tokens.pop((url_token, client_id, escopo or ''), None)


def get_autenticado(sessao, url, url_token, client_id, escopo=None, rotulo='banco',
                    headers_extra=None, params=None):
    """GET com Bearer. Um 401 com token em cache tenta UMA vez com token novo:
    o banco pode ter revogado antes do relógio do cache."""
    for repete in (True, False):
        headers = {'Authorization': f'Bearer {obter_token(sessao, url_token, client_id, escopo, rotulo)}',
                   'Accept': 'application/json', **(headers_extra or {})}
        try:
            return json_(chamar(sessao, 'GET', url, rotulo=rotulo, params=params,
                                headers=headers), rotulo)
        except BancoAuthError:
            if not repete:
                raise
            esquecer_token(url_token, client_id, escopo)


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def chamar(sessao, metodo, url, rotulo='banco', **kw):
    ultimo = None
    for n in range(TENTATIVAS):
        try:
            r = sessao.request(metodo, url, timeout=TIMEOUT, **kw)
        except requests.RequestException as exc:
            ultimo = exc
            logger.warning('[%s] falha de rede em %s (tentativa %d/%d): %s',
                           rotulo, url, n + 1, TENTATIVAS, exc)
        else:
            if r.status_code in (401, 403):
                raise BancoAuthError(
                    f'{rotulo} recusou (HTTP {r.status_code}) em {url}: {r.text[:200]!r}')
            if r.status_code == 429 or r.status_code >= 500:
                ultimo = BancoError(f'{rotulo} HTTP {r.status_code}: {r.text[:200]!r}')
                logger.warning('[%s] %s em %s (tentativa %d/%d)',
                               rotulo, r.status_code, url, n + 1, TENTATIVAS)
            elif r.status_code >= 400:
                raise BancoError(f'{rotulo} HTTP {r.status_code} em {url}: {r.text[:300]!r}')
            else:
                return r
        if n < TENTATIVAS - 1:
            time.sleep(BACKOFF_BASE ** (n + 1))
    raise BancoError(f'{rotulo} indisponível após {TENTATIVAS} tentativas: {ultimo}')


def json_(r, rotulo='banco'):
    try:
        return r.json() or {}
    except ValueError as exc:
        ct = r.headers.get('Content-Type') or '?'
        amostra = (r.text or '')[:120].replace('\n', ' ')
        raise BancoError(f'{rotulo} devolveu HTTP {r.status_code} com Content-Type {ct}, '
                         f'não JSON. Começo do corpo: {amostra!r}') from exc


# ---------------------------------------------------------------------------
# Período e texto
# ---------------------------------------------------------------------------
def validar_periodo(inicio, fim, incluir_hoje=False):
    """Por padrão só dias FECHADOS (até ontem): quem for GRAVAR não pode pegar
    dia pela metade — a segunda consulta acharia lançamentos novos no meio
    dos antigos. ``incluir_hoje`` é só para quem MOSTRA (a tela de consulta)."""
    limite = date.today() if incluir_hoje else date.today() - timedelta(days=1)
    if fim > limite:
        raise ValueError(f'Período até {fim} passa do permitido ({limite}).')
    if inicio > fim:
        raise ValueError(f'Período invertido: {inicio} > {fim}.')


def sem_acento(txt):
    return unicodedata.normalize('NFKD', str(txt or '')).encode('ascii', 'ignore').decode()


def normal(txt):
    return ' '.join(sem_acento(txt).upper().split())


def prefixo_comum(a, b):
    """Quantos caracteres do começo coincidem (sem acento, maiúsculo)."""
    a, b = normal(a), normal(b)
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def mesmo_texto(texto_api, texto_ofx):
    """O OFX escreveu o mesmo texto? Um é o começo do outro — o OFX costuma
    cortar (o do Sicoob em 32 caracteres)."""
    a, b = normal(texto_api), normal(texto_ofx)
    return bool(a) and bool(b) and (a.startswith(b) or b.startswith(a))


# ---------------------------------------------------------------------------
# Comparação com o OFX já gravado (somente SELECT)
# ---------------------------------------------------------------------------
def _chave(data_tx, tipo, valor):
    return (data_tx, tipo, f'{float(valor):.2f}')


def comparar(api_txs, inicio, fim, account_id, texto_como_ofx):
    """Casa API × bank_transactions(account_id) por (data, tipo, valor),
    contando repetições. Devolve {'casados': [(api, ofx)], 'so_api', 'so_ofx'}.

    Dentro do mesmo (dia, tipo, valor) — 65 grupos de PIX iguais só em
    16-22/10 no Sicoob — o par é decidido pelo TEXTO: primeiro os que
    coincidem mais. Só por data e valor, o PIX do Wisney aparecia ao lado do
    da Pauliana.
    """
    from utils.db import get_db_connection
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """SELECT id, data_transacao, tipo, valor, descricao, memo, fitid
                 FROM bank_transactions
                WHERE account_id = %s AND data_transacao BETWEEN %s AND %s
                ORDER BY data_transacao, id""",
            (account_id, inicio, fim))
        ofx = cur.fetchall()
    finally:
        cur.close()
        conn.close()

    fila = defaultdict(list)
    for o in ofx:
        fila[_chave(o['data_transacao'], o['tipo'], o['valor'])].append(o)
    grupos = defaultdict(list)
    for a in api_txs:
        grupos[_chave(a['data_transacao'], a['tipo'], a['valor'])].append(a)

    conc = conciliacao_de([o['id'] for o in ofx])
    for o in ofx:
        o['conciliacao'] = conc.get(o['id'])

    casados, so_api = [], []
    for k, apis in grupos.items():
        ofxs = fila.pop(k, [])
        pares = sorted(((prefixo_comum(texto_como_ofx(a), o['descricao']), i, j)
                        for i, a in enumerate(apis) for j, o in enumerate(ofxs)),
                       reverse=True)
        usados_a, usados_o = set(), set()
        for _score, i, j in pares:
            if i in usados_a or j in usados_o:
                continue
            usados_a.add(i)
            usados_o.add(j)
            casados.append((apis[i], ofxs[j]))
        so_api += [a for i, a in enumerate(apis) if i not in usados_a]
        fila[k] = [o for j, o in enumerate(ofxs) if j not in usados_o]
    so_ofx = [o for lst in fila.values() for o in lst]
    return {'casados': casados, 'so_api': so_api, 'so_ofx': so_ofx}


def _nomes(cur, sql, ids):
    if not ids:
        return {}
    marks = ','.join(['%s'] * len(ids))
    cur.execute(sql.format(marks=marks), tuple(ids))
    return cur.fetchall()


def conciliacao_de(bt_ids):
    """Para quem foi cada lançamento JÁ conciliado no sistema — o que o texto do
    banco não diz ('DÉB.TIT.COMPE EFETIVADO' foi EQUATORIAL, 03/08/2026).

    {bank_transaction_id: {'tipo', 'texto', 'status'}}. Só SELECT. A ordem é a
    do mais específico para o mais genérico: despesa lançada > fornecedor >
    forma de recebimento > transferência > troco PIX > depósito do caixa.
    """
    if not bt_ids:
        return {}
    from utils.db import get_db_connection
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    out = {}
    try:
        for i in range(0, len(bt_ids), 500):
            ids = bt_ids[i:i + 500]
            base = {r['id']: r for r in _nomes(cur, """
                SELECT bt.id, bt.status, bt.tipo_conciliacao,
                       COALESCE(NULLIF(f.nome_fantasia, ''), f.razao_social) AS fornecedor,
                       fr.nome AS forma, COALESCE(bd.apelido, bo.apelido) AS outra_conta
                  FROM bank_transactions bt
                  LEFT JOIN fornecedores f ON f.id = bt.fornecedor_id
                  LEFT JOIN formas_recebimento fr ON fr.id = bt.forma_recebimento_id
                  LEFT JOIN bank_accounts bd ON bd.id = bt.conta_destino_id
                  LEFT JOIN bank_accounts bo ON bo.id = bt.conta_origem_id
                 WHERE bt.id IN ({marks})""", ids)}
            desp = defaultdict(list)
            for r in _nomes(cur, """
                SELECT ld.bank_transaction_id AS id, ld.fornecedor, ld.valor,
                       cd.nome AS categoria, sd.nome AS subcategoria
                  FROM lancamentos_despesas ld
                  LEFT JOIN categorias_despesas cd ON cd.id = ld.categoria_id
                  LEFT JOIN subcategorias_despesas sd ON sd.id = ld.subcategoria_id
                 WHERE ld.bank_transaction_id IN ({marks})""", ids):
                desp[r['id']].append(r)
            troco = {r['id'] for r in _nomes(cur, """
                SELECT bank_transaction_id AS id FROM troco_pix
                 WHERE bank_transaction_id IN ({marks})""", ids)}
            deposito = {r['id'] for t in ('deposito_bank_vinculos', 'lancamentos_caixa_comprovacao')
                        for r in _nomes(cur, f"""
                SELECT bank_transaction_id AS id FROM {t}
                 WHERE bank_transaction_id IN ({{marks}})""", ids)}
            for i_, r in base.items():
                if desp.get(i_):
                    partes = []
                    for d in desp[i_]:
                        cat = ' / '.join(x for x in (d['categoria'], d['subcategoria']) if x)
                        partes.append(' · '.join(x for x in (d['fornecedor'], cat) if x))
                    tipo, texto = 'despesa', ' + '.join(dict.fromkeys(p for p in partes if p))
                elif r['fornecedor']:
                    tipo, texto = 'fornecedor', r['fornecedor']
                elif r['forma']:
                    tipo, texto = 'forma', r['forma']
                elif r['tipo_conciliacao'] == 'transferencia':
                    tipo, texto = 'transferencia', f"transferência · {r['outra_conta'] or 'outra conta'}"
                elif i_ in troco:
                    tipo, texto = 'troco', 'troco PIX'
                elif i_ in deposito:
                    tipo, texto = 'deposito', 'depósito do caixa'
                else:
                    tipo, texto = ('sem_destino' if r['status'] == 'conciliado' else 'pendente'), ''
                out[i_] = {'tipo': tipo, 'texto': texto, 'status': r['status']}
    finally:
        cur.close()
        conn.close()
    return out


def nomes_por_documento(docs):
    """{cnpj/cpf (só dígitos): (nome, fonte)} — para o PIX enviado do Sicoob, que
    traz o CNPJ de quem recebeu e não o nome ('48.116.722 0001-32' foi o
    PETROLEO TABOCAO, 23/10/2026).

    Ordem, do que reflete o uso real para o cadastro puro:
      1. histórico: o fornecedor com que esse CNPJ já foi conciliado mais vezes
         (paga-se um CNPJ e a nota vem de outro — a conciliação sabe);
      2. memorização (bank_supplier_mapping);
      3. cadastro de fornecedores; 4. cadastro de clientes.
    """
    docs = sorted({re.sub(r'\D', '', d or '') for d in docs} - {''})
    docs = [d for d in docs if len(d) in (11, 14)]
    if not docs:
        return {}
    from utils.db import get_db_connection
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    out = {}
    try:
        consultas = (
            ('conciliações anteriores', """
                SELECT bt.cnpj_cpf AS doc, COALESCE(NULLIF(f.nome_fantasia, ''), f.razao_social) AS nome,
                       COUNT(*) AS n
                  FROM bank_transactions bt JOIN fornecedores f ON f.id = bt.fornecedor_id
                 WHERE bt.cnpj_cpf IN ({marks}) GROUP BY 1, 2 ORDER BY n DESC"""),
            ('memorização', """
                SELECT m.cnpj_cpf AS doc, COALESCE(NULLIF(f.nome_fantasia, ''), f.razao_social) AS nome
                  FROM bank_supplier_mapping m JOIN fornecedores f ON f.id = m.fornecedor_id
                 WHERE m.cnpj_cpf IN ({marks})"""),
            ('fornecedores', """
                SELECT REGEXP_REPLACE(cnpj, '[^0-9]', '') AS doc,
                       COALESCE(NULLIF(nome_fantasia, ''), razao_social) AS nome
                  FROM fornecedores WHERE REGEXP_REPLACE(cnpj, '[^0-9]', '') IN ({marks})"""),
            ('clientes', """
                SELECT REGEXP_REPLACE(cnpj, '[^0-9]', '') AS doc,
                       COALESCE(NULLIF(nome_fantasia, ''), razao_social) AS nome
                  FROM clientes WHERE REGEXP_REPLACE(cnpj, '[^0-9]', '') IN ({marks})"""),
        )
        for fonte, sql in consultas:
            falta = [d for d in docs if d not in out]
            if not falta:
                break
            for r in _nomes(cur, sql, falta):
                if r['doc'] not in out and r['nome']:
                    out[r['doc']] = (r['nome'], fonte)
    finally:
        cur.close()
        conn.close()
    return out


def imprimir_comparacao(mod, inicio, fim):
    """O `python -m integrations.<banco>_extrato INI FIM` de cada adapter."""
    api = mod.ler(inicio, fim, incluir_hoje=True)
    r = mod.comparar(api, inicio, fim)
    iguais = sum(1 for x, o in r['casados'] if mod.mesmo_texto_do_ofx(x, o))
    print(f"\nAPI {len(api)} · casados {len(r['casados'])} · "
          f"só na API {len(r['so_api'])} · só no OFX {len(r['so_ofx'])}")
    print(f"texto igual ao OFX: {iguais} de {len(r['casados'])}")
    print('\n-- amostra casados: API | OFX')
    for x, o in r['casados'][:25]:
        print(f"{x['data_transacao']} {x['tipo'][:1]} {x['valor']:>10.2f}  "
              f"{mod.texto_como_ofx(x)[:40]!r}  |  {(o['descricao'] or '')[:40]!r}  fitid={o['fitid']}")
    for nome in ('so_api', 'so_ofx'):
        if r[nome]:
            print(f'\n-- {nome}')
            for x in r[nome][:15]:
                print(f"{x['data_transacao']} {x['tipo']} {float(x['valor']):.2f} {x['descricao']!r}")
    print('\n[só leitura — nada gravado]')
