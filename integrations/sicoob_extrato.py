"""
Extrato do Sicoob pela API (conta corrente, escopo cco_consulta) — SÓ LEITURA.

NÃO GRAVA NADA. Busca o extrato na API, converte para o MESMO formato do
OFXParser.get_transactions() e COMPARA com o que o OFX já gravou em
bank_transactions na conta do Sicoob (bank_accounts.id = 10).

Por que ainda não grava: o OFX dessa conta entra todo dia e está 100%
conciliado (15.560 lançamentos desde 23/06/2026). Duas coisas impedem a API
de entrar ao lado dele sem estragar isso:

  * Deduplicação. O hash_dedup do OFX é fitid|data|valor|descrição, e o FITID
    do Sicoob é SINTÉTICO (data + valor + sequência: '20261022315251'). A API
    não tem esse número, então a mesma transação vinda dos dois lados nunca
    se reconheceria — tudo entraria duas vezes.
  * Conciliação automática. Regras (auto-regra) e memorizações casam pelo
    TEXTO da descrição. Se a API escrever diferente do OFX, param de casar.

A comparação mostra, lado a lado, data/valor/texto da API e do OFX — é o
dado que falta para decidir como (e se) a API substitui o OFX.

mTLS e certificado NÃO são implementados aqui: vêm de scripts/consulta_sefaz
(montar_sessao_mtls e _abrir_registro), os mesmos da captura de DFe.

Uso:
    python -m integrations.sicoob_extrato 2026-10-20 2026-10-22
"""
import hashlib
import logging
import os
import sys
import threading
import time
import unicodedata
from calendar import monthrange
from collections import Counter, defaultdict
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

import requests

logger = logging.getLogger(__name__)

URL_TOKEN = 'https://auth.sicoob.com.br/auth/realms/cooperado/protocol/openid-connect/token'
URL_API = 'https://api.sicoob.com.br/conta-corrente/v4'
ESCOPO = 'cco_consulta'

CLIENTE_ID = 1              # dfe_certificados.cliente_id do Posto (A1 do DFe)
ACCOUNT_ID = 10             # bank_accounts: SICOOB - NH, 5024 / 1481860
COOPERATIVA = '5024'
NUMERO_CONTA = 1481860      # 148.186-0, com o dígito
ENV_CLIENT_ID = 'SICOOB_CLIENT_ID_POSTO'

TIMEOUT = (10, 60)
TENTATIVAS = 3              # rede, 429 e 5xx; 401/403 nunca repete
BACKOFF_BASE = 2
MARGEM_TOKEN = 60           # token de 300s renova aos 240s


class SicoobError(Exception):
    """Falha de transporte ou resposta inesperada do Sicoob."""


class SicoobAuthError(SicoobError):
    """401/403 — client_id, escopo ou certificado recusado."""


class SemCredencial(SicoobError):
    """Falta client_id ou certificado — problema de cadastro, não de rede."""


class TransacaoInvalida(SicoobError):
    """Transação num formato desconhecido — não se adivinha."""


def _consulta_sefaz():
    """scripts/consulta_sefaz, como o routes/dfe_compras importa."""
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for p in (raiz, os.path.join(raiz, 'scripts')):
        if p not in sys.path:
            sys.path.insert(0, p)
    import consulta_sefaz
    return consulta_sefaz


def _client_id():
    cid = (os.getenv(ENV_CLIENT_ID) or '').strip()
    if not cid:
        raise SemCredencial(f'{ENV_CLIENT_ID} não definida.')
    return cid


# ---------------------------------------------------------------------------
# Certificado e sessão
# ---------------------------------------------------------------------------
class SessaoSicoob:
    """Uma sessão mTLS NOVA por chamada.

    O contexto pyOpenSSL do AdaptadorCertMemoria não pode ser reusado depois
    de abrir uma conexão, e aqui são pelo menos duas (token e extrato), em
    hosts diferentes. A captura de DFe nunca tropeçou nisso porque faz uma
    requisição por sessão.
    """

    def __init__(self, cert, chave_priv, cadeia):
        self._material = (cert, chave_priv, cadeia)

    def request(self, metodo, url, **kw):
        s = _consulta_sefaz().montar_sessao_mtls(*self._material)
        try:
            return s.request(metodo, url, **kw)
        finally:
            s.close()


def abrir_sessao():
    """A1 do Posto (o mesmo do DFe): Dropbox -> senha -> PFX em memória."""
    cs = _consulta_sefaz()
    regs = cs._selecionar_ativos(cliente_id=CLIENTE_ID)
    if not regs:
        raise SemCredencial(f'Nenhum certificado ativo para cliente_id={CLIENTE_ID}.')
    try:
        _cid, _doc, cert, chave_priv, cadeia = cs._abrir_registro(regs[0])
    except RuntimeError as exc:
        raise SemCredencial(str(exc)) from exc
    return SessaoSicoob(cert, chave_priv, cadeia)


# ---------------------------------------------------------------------------
# Token OAuth2 em cache
# ---------------------------------------------------------------------------
_tokens = {}                # (client_id, escopo) -> (token, vale_ate_monotonic)
_trava_token = threading.Lock()


def obter_token(sessao, client_id, escopo=ESCOPO):
    """Token que ainda vale por pelo menos MARGEM_TOKEN segundos.

    time.monotonic e não relógio de parede: ajuste de hora no servidor não
    pode fazer um token vencido parecer bom.
    """
    chave = (client_id, escopo)
    with _trava_token:
        guardado = _tokens.get(chave)
        if guardado and time.monotonic() < guardado[1]:
            return guardado[0]
        r = _chamar(sessao, 'POST', URL_TOKEN, data={
            'grant_type': 'client_credentials',
            'client_id': client_id,
            'scope': escopo,
        })
        d = _json(r)
        token = d.get('access_token')
        if not token:
            raise SicoobError(f'Resposta do token sem access_token: {sorted(d)}')
        try:
            dura = int(d.get('expires_in') or 300)
        except (TypeError, ValueError):
            dura = 300
        _tokens[chave] = (token, time.monotonic() + max(0, dura - MARGEM_TOKEN))
        return token


def esquecer_token(client_id, escopo=ESCOPO):
    with _trava_token:
        _tokens.pop((client_id, escopo), None)


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def _chamar(sessao, metodo, url, **kw):
    ultimo = None
    for n in range(TENTATIVAS):
        try:
            r = sessao.request(metodo, url, timeout=TIMEOUT, **kw)
        except requests.RequestException as exc:
            ultimo = exc
            logger.warning('[sicoob] falha de rede em %s (tentativa %d/%d): %s',
                           url, n + 1, TENTATIVAS, exc)
        else:
            if r.status_code in (401, 403):
                raise SicoobAuthError(
                    f'Sicoob recusou (HTTP {r.status_code}) em {url}: {r.text[:200]!r}')
            if r.status_code == 429 or r.status_code >= 500:
                ultimo = SicoobError(f'Sicoob HTTP {r.status_code}')
                logger.warning('[sicoob] %s em %s (tentativa %d/%d)',
                               r.status_code, url, n + 1, TENTATIVAS)
            elif r.status_code >= 400:
                raise SicoobError(f'Sicoob HTTP {r.status_code} em {url}: {r.text[:300]!r}')
            else:
                return r
        if n < TENTATIVAS - 1:
            time.sleep(BACKOFF_BASE ** (n + 1))
    raise SicoobError(f'Sicoob indisponível após {TENTATIVAS} tentativas: {ultimo}')


def _json(r):
    try:
        return r.json() or {}
    except ValueError as exc:
        ct = r.headers.get('Content-Type') or '?'
        amostra = (r.text or '')[:120].replace('\n', ' ')
        raise SicoobError(f'Sicoob devolveu HTTP {r.status_code} com Content-Type {ct}, '
                          f'não JSON. Começo do corpo: {amostra!r}') from exc


def buscar_extrato_mes(sessao, ano, mes, dia_inicial, dia_final):
    """GET /extrato/{mes}/{ano} — um mês por chamada. Devolve o JSON cru.

    401 com token em cache tenta UMA vez com token novo: o banco pode ter
    revogado antes do relógio do cache.
    """
    url = f'{URL_API}/extrato/{mes}/{ano}'
    params = {'diaInicial': dia_inicial, 'diaFinal': dia_final,
              'numeroContaCorrente': NUMERO_CONTA, 'agruparCNAB': 'false'}
    cid = _client_id()
    for repete in (True, False):
        headers = {'Authorization': f'Bearer {obter_token(sessao, cid)}',
                   'client_id': cid, 'Accept': 'application/json'}
        try:
            return _json(_chamar(sessao, 'GET', url, params=params, headers=headers))
        except SicoobAuthError:
            if not repete:
                raise
            esquecer_token(cid)


# ---------------------------------------------------------------------------
# Transação da API -> formato do OFXParser
# ---------------------------------------------------------------------------
def _sem_acento(txt):
    return unicodedata.normalize('NFKD', str(txt or '')).encode('ascii', 'ignore').decode()


def _data(bruta):
    """'2026-10-01T00:00:00.000-03:00' ou '01/10/2026' -> date."""
    s = str(bruta or '').strip()
    if len(s) >= 10 and s[4] == '-' and s[7] == '-':
        return date.fromisoformat(s[:10])
    if len(s) >= 10 and s[2] == '/' and s[5] == '/':
        return date(int(s[6:10]), int(s[3:5]), int(s[0:2]))
    raise TransacaoInvalida(f'data não reconhecida: {bruta!r}')


def para_transacao(t):
    """Uma transação do Sicoob -> dict no formato do OFXParser.get_transactions().

    O sinal vem do 'tipo' (CREDITO/DEBITO). Tipo desconhecido, ou crédito com
    valor negativo, levanta: débito gravado como crédito estraga tudo depois.
    'descricao' <- descricao da API; 'memo' <- descInfComplementar — palpite
    até a comparação com o OFX mostrar a correspondência real.
    """
    from integrations.ofx_parser import _extract_cnpj_cpf

    tipo = _sem_acento(t.get('tipo')).strip().upper()
    if tipo.startswith('CRED'):
        tipo_ofx = 'CREDIT'
    elif tipo.startswith('DEB'):
        tipo_ofx = 'DEBIT'
    else:
        raise TransacaoInvalida(f'tipo desconhecido: {t.get("tipo")!r}')
    try:
        bruto = Decimal(str(t.get('valor')).replace(',', '.'))
    except InvalidOperation as exc:
        raise TransacaoInvalida(f'valor ilegível: {t.get("valor")!r}') from exc
    if bruto < 0 and tipo_ofx == 'CREDIT':
        raise TransacaoInvalida(f'crédito com valor negativo: {t!r}')

    descricao = str(t.get('descricao') or '').strip()
    memo = str(t.get('descInfComplementar') or '').strip()
    cnpj_cpf, tipo_chave = _extract_cnpj_cpf(f'{descricao} {memo} {t.get("cpfCnpj") or ""}')
    return {
        'fitid': None,
        'tipo': tipo_ofx,
        'data_transacao': _data(t.get('data')),
        'valor': float(abs(bruto).quantize(Decimal('0.01'))),
        'descricao': descricao,
        'memo': memo,
        'cnpj_cpf': cnpj_cpf,
        'tipo_chave': tipo_chave,
        'hash_dedup': None,     # ver hash_api(): só faz sentido quando houver gravação
        'numero_documento': str(t.get('numeroDocumento') or '').strip() or None,
    }


def hash_api(tx, repeticao):
    """Hash estável da transação da API, com prefixo próprio — não colide com o do OFX
    (fitid|data|valor|descrição) e repete igual a cada consulta do mesmo dia."""
    raw = (f"sicoob-api|{tx['data_transacao']}|{tx['tipo']}|{tx['valor']:.2f}|"
           f"{tx['descricao']}|{tx['memo']}|{tx['numero_documento'] or ''}|#{repeticao}")
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def _meses(inicio, fim):
    d = inicio
    while d <= fim:
        ate = min(date(d.year, d.month, monthrange(d.year, d.month)[1]), fim)
        yield d.year, d.month, d.day, ate.day
        d = ate + timedelta(days=1)


def ler(inicio, fim, sessao=None):
    """Período na API -> lista no formato do OFXParser. Só dias FECHADOS (até ontem):
    dia pela metade faria a segunda consulta achar lançamentos novos no meio
    dos antigos."""
    if fim >= date.today():
        raise ValueError(f'Só dias fechados: fim {fim} precisa ser antes de hoje.')
    if inicio > fim:
        raise ValueError(f'Período invertido: {inicio} > {fim}.')
    sessao = sessao or abrir_sessao()
    txs = []
    for ano, mes, di, df in _meses(inicio, fim):
        d = buscar_extrato_mes(sessao, ano, mes, di, df)
        res = d.get('resultado')
        if not isinstance(res, dict) or not isinstance(res.get('transacoes'), list):
            raise TransacaoInvalida(
                f'resposta sem resultado.transacoes ({ano}-{mes:02d}): chaves {sorted(d)}')
        txs += [para_transacao(t) for t in res['transacoes']]
    fora = [t for t in txs if not inicio <= t['data_transacao'] <= fim]
    if fora:
        logger.warning('[sicoob] %d transações fora de %s..%s descartadas.', len(fora), inicio, fim)
    return [t for t in txs if inicio <= t['data_transacao'] <= fim]


# ---------------------------------------------------------------------------
# Comparação com o OFX já gravado (somente SELECT)
# ---------------------------------------------------------------------------
def _chave(data_tx, tipo, valor):
    return (data_tx, tipo, f'{float(valor):.2f}')


def comparar(api_txs, inicio, fim):
    """Casa API × bank_transactions(conta 10) por (data, tipo, valor), contando
    repetições. Devolve {'casados': [(api, ofx)], 'so_api': [...], 'so_ofx': [...]}."""
    from utils.db import get_db_connection
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """SELECT id, data_transacao, tipo, valor, descricao, memo, fitid
                 FROM bank_transactions
                WHERE account_id = %s AND data_transacao BETWEEN %s AND %s
                ORDER BY data_transacao, id""",
            (ACCOUNT_ID, inicio, fim))
        ofx = cur.fetchall()
    finally:
        cur.close()
        conn.close()

    fila = defaultdict(list)
    for o in ofx:
        fila[_chave(o['data_transacao'], o['tipo'], o['valor'])].append(o)
    casados, so_api = [], []
    for a in api_txs:
        k = _chave(a['data_transacao'], a['tipo'], a['valor'])
        if fila[k]:
            casados.append((a, fila[k].pop(0)))
        else:
            so_api.append(a)
    so_ofx = [o for lst in fila.values() for o in lst]
    return {'casados': casados, 'so_api': so_api, 'so_ofx': so_ofx}


def main():
    import argparse
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s %(levelname)s [%(name)s] %(message)s')
    ap = argparse.ArgumentParser(description='Extrato Sicoob pela API x OFX gravado (só leitura).')
    ap.add_argument('inicio', type=date.fromisoformat)
    ap.add_argument('fim', type=date.fromisoformat)
    a = ap.parse_args()

    api = ler(a.inicio, a.fim)
    r = comparar(api, a.inicio, a.fim)
    print(f"\nAPI {len(api)} · casados {len(r['casados'])} · "
          f"só na API {len(r['so_api'])} · só no OFX {len(r['so_ofx'])}")
    textos = Counter((x['descricao'] == o['descricao'], x['memo'] == (o['memo'] or ''))
                     for x, o in r['casados'])
    print(f"texto igual ao OFX (descricao, memo): {dict(textos)}")
    print('\n-- amostra casados: API | OFX')
    for x, o in r['casados'][:25]:
        print(f"{x['data_transacao']} {x['tipo'][:1]} {x['valor']:>10.2f}  "
              f"{x['descricao'][:32]!r} / {x['memo'][:30]!r}  |  "
              f"{(o['descricao'] or '')[:32]!r} / {(o['memo'] or '')[:30]!r}  fitid={o['fitid']}  doc={x['numero_documento']}")
    for nome in ('so_api', 'so_ofx'):
        if r[nome]:
            print(f'\n-- {nome}')
            for x in r[nome][:15]:
                print(f"{x['data_transacao']} {x['tipo']} {float(x['valor']):.2f} {x['descricao']!r}")
    print('\n[só leitura — nada gravado]')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
