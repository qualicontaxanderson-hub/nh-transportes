"""
Extrato do Cora pela API (Integração Direta) — SÓ LEITURA.

NÃO GRAVA NADA. Mesmo desenho do sicoob_extrato: busca o extrato, converte
para o formato do OFXParser.get_transactions() e COMPARA com o que o OFX já
gravou em bank_transactions na conta.

Duas contas, o mesmo código — cada uma com as SUAS credenciais (o Cora gera
client_id, certificado e chave por conta):

  * posto  CORA - NH GTBA   0001 / 3456427-0   bank_accounts.id = 3
  * prest  CORA - PREST     0001 / 27677832    bank_accounts.id = 4
                            (PREST SERVICE STATION PETROL LTDA)

Conferido na documentação oficial em 23/10/2026 (developers.cora.com.br):

  * Integração Direta, produção: https://matls-clients.api.cora.com.br
  * Token: POST /token, form grant_type=client_credentials & client_id, com
    o certificado e a private key do Cora em TODA requisição (mTLS). O token
    vale 24h (expires_in 86400). Sem escopo nesta modalidade.
  * Extrato: GET /bank-statement/statement?start=AAAA-MM-DD&end=AAAA-MM-DD
    &page=N&perPage=500 — máximo 500 por página ("acima de 500 dá 503/504"),
    sem contador de páginas: lê até vir uma página menor que perPage.
  * Valores INTEIROS EM CENTAVOS. entries[].type: CREDIT | DEBIT | UNBLOCK |
    BLOCK (fechado — define o sinal). transaction.type: TRANSFER, PAYMENT,
    PIX, FEE, CARD, BANK_DOMICILE... — enum ABERTO: "integrações não devem
    falhar nem descartar a entrada ao encontrar um valor fora desta lista".
  * aggregations.creditTotal/debitTotal: o total do PERÍODO inteiro, dito
    pelo próprio banco, independente da paginação — usado para provar que
    nenhuma página se perdeu.

O certificado NÃO é o A1 ICP-Brasil: é o par (certificate.pem +
private-key.key) que o Cora gera em Conta > Integrações via APIs. Vem das
variáveis CORA_CERT_<CONTA> e CORA_KEY_<CONTA> (o conteúdo PEM, ou o caminho
do arquivo). mTLS, token em cache, HTTP e comparação: integrations/banco_api.

Uso:
    python -m integrations.cora_extrato posto 2026-10-20 2026-10-22
    python -m integrations.cora_extrato prest 2026-10-20 2026-10-22
"""
import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from integrations import banco_api as api
from integrations.banco_api import (BancoAuthError, BancoError, SemCredencial,  # noqa: F401
                                    TransacaoInvalida)

logger = logging.getLogger(__name__)

URL_BASE = 'https://matls-clients.api.cora.com.br'
URL_TOKEN = f'{URL_BASE}/token'
URL_EXTRATO = f'{URL_BASE}/bank-statement/statement'

POR_PAGINA = 500
MAX_PAGINAS = 60            # 30.000 lançamentos: muito acima de 31 dias de uma conta
BRT = timezone(timedelta(hours=-3))   # sem horário de verão desde 2019

# entries[].type -> sinal. UNBLOCK/BLOCK também mexem no saldo disponível.
TIPO_REGISTRO = {'CREDIT': 'CREDIT', 'UNBLOCK': 'CREDIT', 'DEBIT': 'DEBIT', 'BLOCK': 'DEBIT'}


# ---------------------------------------------------------------------------
# Lançamento da API -> formato do OFXParser (igual para todas as contas)
# ---------------------------------------------------------------------------
def _quando(bruta):
    """'2023-04-06T09:00:00+00' (UTC) -> datetime no horário de Brasília.

    A data do lançamento é a de BRASÍLIA: um PIX das 22h de Goiatuba chega
    como 01h do dia seguinte em UTC, e seria contado no dia errado.
    """
    s = str(bruta or '').strip().replace('Z', '+00:00')
    s = re.sub(r'([+-]\d{2})$', r'\1:00', s)          # '+00' -> '+00:00'
    try:
        dt = datetime.fromisoformat(s)
    except ValueError as exc:
        raise TransacaoInvalida(f'createdAt não reconhecido: {bruta!r}') from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(BRT)


def _doc_formatado(identity):
    d = re.sub(r'\D', '', str(identity or ''))
    if len(d) == 11:
        return f'{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}'
    if len(d) == 14:
        return f'{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}'
    return d


def para_transacao(e):
    """Um entries[] do Cora -> dict no formato do OFXParser.get_transactions().

    O sinal vem de entries[].type (lista FECHADA na documentação): tipo fora
    dela levanta, porque crédito lido como débito estraga tudo. Já o
    transaction.type é lista ABERTA: valor novo vira categoria genérica.
    """
    tipo = TIPO_REGISTRO.get(str(e.get('type') or '').upper())
    if not tipo:
        raise TransacaoInvalida(f'entries.type desconhecido: {e.get("type")!r}')
    try:
        centavos = int(e.get('amount'))
    except (TypeError, ValueError) as exc:
        raise TransacaoInvalida(f'amount ilegível: {e.get("amount")!r}') from exc
    if centavos < 0:
        raise TransacaoInvalida(f'amount negativo (o sinal vem de type): {e!r}')

    quando = _quando(e.get('createdAt'))
    trx = e.get('transaction') or {}
    contra = trx.get('counterParty') or {}
    nome = str(contra.get('name') or '').strip()
    doc = _doc_formatado(contra.get('identity'))
    descricao = str(trx.get('description') or '').strip()
    categoria = str(trx.get('type') or '').upper() or None
    if str(e.get('type')).upper() in ('BLOCK', 'UNBLOCK'):
        categoria = 'BLOCK'
    texto = ' - '.join(p for p in (descricao, nome, doc) if p)
    return {
        'fitid': None,          # o FITID do OFX do Cora é um UUID; o id da API é 'ent_...'
        'tipo': tipo,
        'data_transacao': quando.date(),
        'hora': quando.strftime('%H:%M'),
        'valor': centavos / 100.0,
        'descricao': texto,
        'memo': categoria or '',
        'cnpj_cpf': re.sub(r'\D', '', str(contra.get('identity') or '')) or None,
        'tipo_chave': None,
        'hash_dedup': None,
        'numero_documento': None,
        'id_banco': e.get('id'),
        'quem': nome or descricao,
        'doc_pessoa': doc,
        'categoria_banco': categoria,
        'bruto': e,             # o lançamento como o Cora mandou (/extrato-online/bruto)
    }


# O começo do texto do OFX do Cora por (tipo do banco, sentido) — medido nos
# OFX de ago-out/2026 das contas 3 e 4: 'Transf Pix enviada' (252),
# 'Transf Pix recebida' (98), 'Boleto pago' (32), 'Transferência enviada' (33),
# 'Pagamento recebido' (2). 'Pgto QR Code Pix' (71) também é PIX de saída e não
# dá para separar pelo tipo: sai como 'Transf Pix enviada', e quando o OFX
# chegar o texto dele substitui (bank_import._save_transactions).
_PREFIXO_OFX = {
    ('PIX', 'DEBIT'): 'Transf Pix enviada',
    ('PIX', 'CREDIT'): 'Transf Pix recebida',
    ('TRANSFER', 'DEBIT'): 'Transferência enviada',
    ('TRANSFER', 'CREDIT'): 'Transferência recebida',
    ('PAYMENT', 'DEBIT'): 'Boleto pago',
    ('PAYMENT', 'CREDIT'): 'Pagamento recebido',
}


def texto_como_ofx(tx):
    """O OFX do Cora grava 'Transf Pix enviada - Nome - 000.000.000-00':
    o tipo, o nome e o documento de quem está do outro lado. É por esse texto
    que as regras e memorizações casam, então a API grava igual. Tipo fora da
    tabela: o texto do próprio banco."""
    prefixo = _PREFIXO_OFX.get((tx.get('categoria_banco'), tx.get('tipo')))
    nome = (tx.get('quem') or '').strip()
    if not prefixo or not nome:
        return tx.get('descricao') or ''
    return ' - '.join(p for p in (prefixo, nome, tx.get('doc_pessoa')) if p)


def mesmo_texto_do_ofx(tx, ofx):
    return api.mesmo_texto(texto_como_ofx(tx), ofx.get('descricao'))


def hash_api(tx, repeticao=0):
    """Com o id do próprio banco a chave é estável; sem ele, data+valor+texto."""
    base = tx.get('id_banco') or (f"{tx['data_transacao']}|{tx['tipo']}|{tx['valor']:.2f}|"
                                  f"{tx['descricao']}|#{repeticao}")
    return hashlib.sha256(f'cora-api|{base}'.encode('utf-8')).hexdigest()


def _conferir_total(entradas, agg):
    """A soma lida tem de bater com o total do próprio banco, senão alguma
    página se perdeu e a tela NÃO pode dizer "veio tudo".

    A documentação não diz se BLOCK/UNBLOCK entram no creditTotal/debitTotal:
    aceita com e sem eles. Qualquer outra diferença é página perdida.
    """
    def soma(tipos):
        return sum(int(e['amount']) for e in entradas if str(e.get('type')).upper() in tipos)
    quer_c, quer_d = int(agg.get('creditTotal') or 0), int(agg.get('debitTotal') or 0)
    if not (quer_c in (soma({'CREDIT'}), soma({'CREDIT', 'UNBLOCK'}))
            and quer_d in (soma({'DEBIT'}), soma({'DEBIT', 'BLOCK'}))):
        raise BancoError(
            f'cora: a soma lida ({soma({"CREDIT"}) / 100:.2f} entradas, '
            f'{soma({"DEBIT"}) / 100:.2f} saídas) não bate com o total do banco '
            f'({quer_c / 100:.2f} / {quer_d / 100:.2f}). Extrato incompleto — não confie '
            f'nesta consulta.')


# ---------------------------------------------------------------------------
# Uma conta Cora: credenciais próprias, a mesma leitura
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ContaCora:
    """Tem a mesma cara de um módulo adapter (ler, comparar, mesmo_texto_do_ofx)
    — é o que a tela e o banco_api.imprimir_comparacao chamam."""
    chave: str
    rotulo: str
    account_id: int             # bank_accounts.id — onde está o OFX desta conta

    @property
    def env_client_id(self):
        return f'CORA_CLIENT_ID_{self.chave.upper()}'

    @property
    def env_cert(self):
        return f'CORA_CERT_{self.chave.upper()}'

    @property
    def env_chave(self):
        return f'CORA_KEY_{self.chave.upper()}'

    # o que não depende da conta, exposto aqui para a interface ficar inteira
    texto_como_ofx = staticmethod(texto_como_ofx)
    mesmo_texto_do_ofx = staticmethod(mesmo_texto_do_ofx)

    def abrir_sessao(self):
        """O par certificado + chave que o Cora gerou PARA ESTA CONTA."""
        return api.sessao_de_pem(self.env_cert, self.env_chave)

    def buscar_pagina(self, sessao, inicio, fim, pagina):
        cid = api.env_obrigatoria(self.env_client_id)
        return api.get_autenticado(
            sessao, URL_EXTRATO, URL_TOKEN, cid, rotulo=f'cora-{self.chave}',
            params={'start': inicio.isoformat(), 'end': fim.isoformat(),
                    'page': pagina, 'perPage': POR_PAGINA})

    def ler(self, inicio, fim, sessao=None, incluir_hoje=False):
        """Período na API -> lista no formato do OFXParser, todas as páginas."""
        api.validar_periodo(inicio, fim, incluir_hoje)
        sessao = sessao or self.abrir_sessao()
        # Um dia a mais de cada lado: a documentação não diz se start/end são
        # dias em UTC ou em Brasília, e o PIX das 22h de Brasília já é o dia
        # seguinte em UTC. Pede-se a mais e filtra-se aqui, no horário de Brasília.
        pede_ini, pede_fim = inicio - timedelta(days=1), fim + timedelta(days=1)
        entradas, vistos, agg = [], set(), None
        for pagina in range(1, MAX_PAGINAS + 1):
            d = self.buscar_pagina(sessao, pede_ini, pede_fim, pagina)
            lote = d.get('entries') or []
            if not isinstance(lote, list):
                raise TransacaoInvalida(f'entries não é lista: chaves {sorted(d)}')
            if agg is None and isinstance(d.get('aggregations'), dict):
                agg = d['aggregations']
            novos = [e for e in lote if e.get('id') not in vistos]
            if lote and not novos:
                # A página repetiu a anterior: o parâmetro page não está sendo
                # obedecido. Parar aqui evita laço infinito e lista dobrada.
                raise BancoError(f'cora: a página {pagina} repetiu lançamentos já lidos.')
            vistos.update(e.get('id') for e in novos)
            entradas += novos
            if len(lote) < POR_PAGINA:
                break
        else:
            raise BancoError(f'cora: mais de {MAX_PAGINAS} páginas — período grande demais.')

        txs = [para_transacao(e) for e in entradas]
        if agg:
            _conferir_total(entradas, agg)
        return [t for t in txs if inicio <= t['data_transacao'] <= fim]

    def comparar(self, api_txs, inicio, fim):
        """API × OFX desta conta."""
        return api.comparar(api_txs, inicio, fim, self.account_id, texto_como_ofx)


POSTO = ContaCora('posto', 'CORA - NH', 3)       # 0001 / 3456427-0
PREST = ContaCora('prest', 'CORA - PREST', 4)    # 0001 / 27677832
CONTAS = {c.chave: c for c in (POSTO, PREST)}


def main():
    import argparse
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s %(levelname)s [%(name)s] %(message)s')
    ap = argparse.ArgumentParser(description='Extrato Cora pela API x OFX gravado (só leitura).')
    ap.add_argument('conta', choices=sorted(CONTAS))
    ap.add_argument('inicio', type=date.fromisoformat)
    ap.add_argument('fim', type=date.fromisoformat)
    a = ap.parse_args()
    api.imprimir_comparacao(CONTAS[a.conta], a.inicio, a.fim)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
