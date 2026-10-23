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

Primeira consulta real (23/10/2026, 16-22/10): 1.059 lançamentos, entradas e
saídas idênticas ao OFX.

mTLS, token em cache, HTTP e comparação moram em integrations/banco_api — o
mesmo para todos os bancos. O certificado é o A1 do Posto, o mesmo do DFe.

Uso:
    python -m integrations.sicoob_extrato 2026-10-20 2026-10-22
"""
import hashlib
import logging
from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from integrations import banco_api as api
from integrations.banco_api import (BancoAuthError, BancoError, SemCredencial,  # noqa: F401
                                    TransacaoInvalida)

logger = logging.getLogger(__name__)

URL_TOKEN = 'https://auth.sicoob.com.br/auth/realms/cooperado/protocol/openid-connect/token'
URL_API = 'https://api.sicoob.com.br/conta-corrente/v4'
ESCOPO = 'cco_consulta'

CLIENTE_ID = 1              # dfe_certificados.cliente_id do Posto (A1 do DFe)
ACCOUNT_ID = 10             # bank_accounts: SICOOB - NH, 5024 / 1481860
COOPERATIVA = '5024'
NUMERO_CONTA = 1481860      # 148.186-0, com o dígito
ENV_CLIENT_ID = 'SICOOB_CLIENT_ID_POSTO'

# Nomes antigos, para quem já importava daqui.
SicoobError = BancoError
SicoobAuthError = BancoAuthError


def abrir_sessao():
    """A1 do Posto (o mesmo do DFe)."""
    return api.sessao_do_a1(CLIENTE_ID)


def buscar_extrato_mes(sessao, ano, mes, dia_inicial, dia_final):
    """GET /extrato/{mes}/{ano} — um mês por chamada. Devolve o JSON cru."""
    cid = api.env_obrigatoria(ENV_CLIENT_ID)
    return api.get_autenticado(
        sessao, f'{URL_API}/extrato/{mes}/{ano}', URL_TOKEN, cid, ESCOPO, rotulo='sicoob',
        headers_extra={'client_id': cid},
        params={'diaInicial': dia_inicial, 'diaFinal': dia_final,
                'numeroContaCorrente': NUMERO_CONTA, 'agruparCNAB': 'false'})


# ---------------------------------------------------------------------------
# Transação da API -> formato do OFXParser
# ---------------------------------------------------------------------------
def _data(bruta):
    """'2026-10-01T00:00:00.000-03:00' ou '01/10/2026' -> date."""
    s = str(bruta or '').strip()
    if len(s) >= 10 and s[4] == '-' and s[7] == '-':
        return date.fromisoformat(s[:10])
    if len(s) >= 10 and s[2] == '/' and s[5] == '/':
        return date(int(s[6:10]), int(s[3:5]), int(s[0:2]))
    raise TransacaoInvalida(f'data não reconhecida: {bruta!r}')


def partes_complemento(memo):
    """'Recebimento Pix|@Wisney Cunha Oliveira|@***.783.651-**|@' ->
    ['Recebimento Pix', 'Wisney Cunha Oliveira', '***.783.651-**'].

    Formato visto na primeira consulta real (23/10/2026): o Sicoob separa os
    campos com '|' e marca o começo de cada um com '@'.
    """
    return [p.strip().lstrip('@').strip() for p in str(memo or '').split('|')
            if p.strip().lstrip('@').strip()]


def para_transacao(t):
    """Uma transação do Sicoob -> dict no formato do OFXParser.get_transactions().

    O sinal vem do 'tipo' (CREDITO/DEBITO). Tipo desconhecido, ou crédito com
    valor negativo, levanta: débito gravado como crédito estraga tudo depois.
    'descricao' = MEMO do OFX, 'memo' (descInfComplementar) = NAME do OFX —
    confirmado na primeira consulta real.
    """
    from integrations.ofx_parser import _extract_cnpj_cpf

    tipo = api.sem_acento(t.get('tipo')).strip().upper()
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
    partes = partes_complemento(memo)
    return {
        'fitid': None,
        'tipo': tipo_ofx,
        'data_transacao': _data(t.get('data')),
        'hora': None,           # o extrato do Sicoob só traz o dia
        'valor': float(abs(bruto).quantize(Decimal('0.01'))),
        'descricao': descricao,
        'memo': memo,
        'cnpj_cpf': cnpj_cpf,
        'tipo_chave': tipo_chave,
        'hash_dedup': None,     # ver hash_api(): só faz sentido quando houver gravação
        'numero_documento': str(t.get('numeroDocumento') or '').strip() or None,
        # Para a tela: 'Recebimento Pix · Nome · CPF' — o nome é o que se procura.
        'quem': partes[1] if len(partes) > 1 else (partes[0] if partes else ''),
        'doc_pessoa': partes[2] if len(partes) > 2 else '',
        'categoria_banco': None,  # o Sicoob não diz; a tela deduz do texto
    }


def texto_como_ofx(tx):
    """O texto que o OFX do Sicoob grava no NAME para esta transação, sem o corte.

    Na mesma consulta: o NAME do OFX é o complemento da API com os campos
    colados por espaço e cortado em 32 caracteres ('Recebimento Pix Edimilson
    Silva' <- 'Recebimento Pix|@Edimilson Silva Miele|@...'). Sem complemento,
    o OFX usa a própria descrição.
    """
    partes = partes_complemento(tx.get('memo'))
    return ' '.join(partes[:2]) if partes else (tx.get('descricao') or '')


def mesmo_texto_do_ofx(tx, ofx):
    """É o que diz se regras e memorizações continuariam casando."""
    return api.mesmo_texto(texto_como_ofx(tx), ofx.get('descricao'))


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


def ler(inicio, fim, sessao=None, incluir_hoje=False):
    """Período na API -> lista no formato do OFXParser (ver banco_api.validar_periodo)."""
    api.validar_periodo(inicio, fim, incluir_hoje)
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


def comparar(api_txs, inicio, fim):
    """API × OFX da conta do Sicoob (bank_accounts.id = 10)."""
    return api.comparar(api_txs, inicio, fim, ACCOUNT_ID, texto_como_ofx)


def main():
    import argparse
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s %(levelname)s [%(name)s] %(message)s')
    ap = argparse.ArgumentParser(description='Extrato Sicoob pela API x OFX gravado (só leitura).')
    ap.add_argument('inicio', type=date.fromisoformat)
    ap.add_argument('fim', type=date.fromisoformat)
    a = ap.parse_args()
    import sys
    api.imprimir_comparacao(sys.modules[__name__], a.inicio, a.fim)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
