"""
Boleto registrado pelo Cora (Integração Direta, mTLS) — emitir, consultar,
cancelar e dar baixa.

Usa as MESMAS credenciais do extrato (CORA_CLIENT_ID_<CONTA>, CORA_CERT_<CONTA>,
CORA_KEY_<CONTA>): o acesso do Cora vale para extrato e boleto. Conferido em
18/11/2026: as duas contas listam /v2/invoices/.

Pedido 18/11/2026: a Prest passa a emitir pelo Cora (mensalidade com 100
boletos/mês inclusos; a Efí cobra R$ 1,45 por boleto). O NH fica pronto para
quando precisar (fiado).

Como a cobrança do Cora é reconhecida no resto do sistema: o id do Cora
começa com 'inv_' (os da Efí são números). Esse id vai em cobrancas.charge_id
— não precisou de coluna nova. `eh_cora(charge_id)` decide o caminho.

Documentação oficial (developers.cora.com.br), conferida em 18/11/2026:
  * POST   /v2/invoices/            emitir (Idempotency-Key obrigatória)
  * GET    /v2/invoices/{id}        detalhe (status, pagamentos, PDF, PIX)
  * DELETE /v2/invoices/{id}        cancelar (só não pago; 204 sem corpo)
  * services: só o PRIMEIRO item vale — os fretes vão juntos num item só.
  * valor mínimo R$ 5,00; vencimento >= hoje.
  * Não existe alterar vencimento: cancela e emite outro.
"""
import logging
import re
import uuid
from datetime import date

from integrations import banco_api as api
from integrations.banco_api import BancoError  # noqa: F401  (quem chama captura)
from integrations.cora_extrato import URL_BASE, URL_TOKEN, ContaCora

logger = logging.getLogger(__name__)

URL_INVOICES = f'{URL_BASE}/v2/invoices/'

# chave -> conta do Cora (as mesmas do extrato)
CONTAS = {
    'prest': ContaCora('prest', 'CORA - PREST', 4),
    'posto': ContaCora('posto', 'CORA - NH GTBA', 3),
}

# status do Cora -> status em cobrancas
STATUS_PAGO = {'PAID'}
STATUS_CANCELADO = {'CANCELLED'}


def eh_cora(charge_id):
    return str(charge_id or '').startswith('inv_')


def _so_digitos(s):
    return re.sub(r'\D', '', str(s or ''))


def _chamar(conta, metodo, url, json=None, headers=None, params=None):
    """Chamada autenticada. Um 401 com token em cache tenta UMA vez com token novo."""
    c = CONTAS[conta]
    sessao = c.abrir_sessao()
    cid = api.env_obrigatoria(c.env_client_id)
    rotulo = f'cora-boleto-{conta}'
    for repete in (True, False):
        h = {'Authorization': f'Bearer {api.obter_token(sessao, URL_TOKEN, cid, rotulo=rotulo)}',
             'Accept': 'application/json', **(headers or {})}
        try:
            return api.chamar(sessao, metodo, url, rotulo=rotulo, json=json, params=params, headers=h)
        except api.BancoAuthError:
            if not repete:
                raise
            api.esquecer_token(URL_TOKEN, cid)


def montar_corpo(cliente, valor_centavos, vencimento, nome_servico, descricao, codigo=None):
    """cliente: dict com nome, documento, email, endereco, numero, bairro,
    cidade, uf, cep, complemento. Endereço só vai se estiver COMPLETO (o Cora
    exige todos os campos quando o endereço é enviado; não inventamos CEP)."""
    doc = _so_digitos(cliente.get('documento'))
    if len(doc) not in (11, 14):
        raise ValueError('Cliente sem CPF/CNPJ válido no cadastro — o boleto exige.')
    nome = (cliente.get('nome') or '').strip()
    if len(nome) < 3:
        raise ValueError('Cliente sem nome no cadastro.')
    if int(valor_centavos) < 500:
        raise ValueError('O Cora não emite boleto abaixo de R$ 5,00.')
    if vencimento < date.today():
        raise ValueError('Vencimento no passado.')

    customer = {'name': nome[:255],
                'document': {'identity': doc, 'type': 'CPF' if len(doc) == 11 else 'CNPJ'}}
    email = (cliente.get('email') or '').strip()
    if email and '@' in email:
        customer['email'] = email.split(';')[0].split(',')[0].strip()[:255]
    end = {'street': (cliente.get('endereco') or '').strip(),
           'number': (cliente.get('numero') or '').strip() or 'S/N',
           'district': (cliente.get('bairro') or '').strip(),
           'city': (cliente.get('cidade') or '').strip(),
           'state': (cliente.get('uf') or '').strip().upper()[:2],
           'zip_code': _so_digitos(cliente.get('cep'))}
    if all([end['street'], end['district'], end['city'], len(end['state']) == 2, len(end['zip_code']) == 8]):
        comp = (cliente.get('complemento') or '').strip()
        if comp:
            end['complement'] = comp[:255]
        customer['address'] = end

    corpo = {
        'customer': customer,
        'services': [{'name': nome_servico[:255], 'description': (descricao or '')[:255],
                      'amount': int(valor_centavos)}],
        'payment_terms': {'due_date': vencimento.isoformat()},
        'payment_forms': ['BANK_SLIP', 'PIX'],
    }
    if codigo:
        corpo['code'] = str(codigo)[:64]
    return corpo


def campos(inv):
    """Resposta do Cora -> o que o sistema guarda em cobrancas."""
    bs = ((inv.get('payment_options') or {}).get('bank_slip') or {})
    return {
        'charge_id': inv.get('id'),
        'status': inv.get('status'),
        'pdf_url': bs.get('url'),
        'barcode': bs.get('digitable') or bs.get('barcode'),
        'pix': (inv.get('pix') or {}).get('emv'),
        'total_pago': inv.get('total_paid'),
        'data_pagamento': inv.get('occurrence_date'),
    }


def emitir(conta, corpo, idem_key=None):
    """Cria o boleto. A Idempotency-Key é a mesma em todas as tentativas desta
    chamada: se a rede cair depois do Cora criar, a repetição devolve o MESMO
    boleto em vez de um segundo."""
    idem_key = idem_key or str(uuid.uuid4())
    r = _chamar(conta, 'POST', URL_INVOICES, json=corpo,
                headers={'Content-Type': 'application/json', 'Idempotency-Key': idem_key})
    inv = api.json_(r, f'cora-boleto-{conta}')
    if not str(inv.get('id') or '').startswith('inv_'):
        raise BancoError(f'Cora não devolveu o id do boleto: chaves {sorted(inv)[:10]}')
    return inv


def consultar(conta, charge_id):
    r = _chamar(conta, 'GET', URL_INVOICES + str(charge_id))
    return api.json_(r, f'cora-boleto-{conta}')


def cancelar(conta, charge_id):
    """True se cancelou (ou já estava cancelado). Levanta BancoError se o Cora
    recusar — ex.: boleto já pago (REC-0006)."""
    try:
        _chamar(conta, 'DELETE', URL_INVOICES + str(charge_id))
        return True
    except BancoError:
        try:
            if consultar(conta, charge_id).get('status') in STATUS_CANCELADO:
                return True
        except Exception:
            pass
        raise


# ---------------------------------------------------------------------------
# Baixa automática: pergunta ao Cora pelos boletos em aberto daqui
# ---------------------------------------------------------------------------
def reconciliar(conn, conta='prest', logger_=None):
    """Para cada cobrança do Cora em aberto (pendente/erro/NULL), consulta o
    boleto: PAID -> 'pago' (pago_via_provedor=1, data do pagamento);
    CANCELLED -> 'cancelado' (libera os fretes). Devolve resumo."""
    log = logger_ or logger
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id, charge_id FROM cobrancas WHERE charge_id LIKE 'inv\\_%%' "
                "AND (status IS NULL OR status NOT IN ('pago','cancelado'))")
    abertos = cur.fetchall() or []
    pagos = cancelados = 0
    for row in abertos:
        try:
            f = campos(consultar(conta, row['charge_id']))
        except Exception as e:
            log.warning('[cora_boleto] consulta %s falhou: %s', row['charge_id'], e)
            continue
        if f['status'] in STATUS_PAGO:
            cur.execute("UPDATE cobrancas SET status='pago', pago_via_provedor=1, data_pagamento=%s "
                        "WHERE id=%s AND (status IS NULL OR status<>'pago')",
                        (f['data_pagamento'] or date.today().isoformat(), row['id']))
            conn.commit()
            pagos += cur.rowcount
        elif f['status'] in STATUS_CANCELADO:
            marcar_cancelado(conn, row['id'], 'cancelado no Cora')
            cancelados += 1
    cur.close()
    return {'abertos': len(abertos), 'pagos': pagos, 'cancelados': cancelados}


def marcar_cancelado(conn, cobranca_id, motivo, liberar_fretes=True):
    """Mesmo efeito do _persist_cancel_to_db da Efí: cobrança 'cancelado' e
    fretes liberados para nova emissão (só os que não têm outra cobrança viva)."""
    cur = conn.cursor()
    cur.execute("UPDATE cobrancas SET status='cancelado', data_cancelamento=NOW(), "
                "provider_cancel_response=%s WHERE id=%s AND (status IS NULL OR status<>'pago')",
                (motivo[:200], cobranca_id))
    if liberar_fretes:
        cur.execute("""
            UPDATE fretes f SET f.boleto_emitido = FALSE
             WHERE f.id IN (SELECT frete_id FROM cobrancas WHERE id=%s AND frete_id IS NOT NULL
                            UNION SELECT frete_id FROM cobrancas_freites WHERE cobranca_id=%s)
               AND NOT EXISTS (SELECT 1 FROM cobrancas cb WHERE cb.frete_id = f.id
                                 AND (cb.status IS NULL OR cb.status <> 'cancelado'))
               AND NOT EXISTS (SELECT 1 FROM cobrancas_freites cf JOIN cobrancas cb ON cb.id = cf.cobranca_id
                                WHERE cf.frete_id = f.id AND (cb.status IS NULL OR cb.status <> 'cancelado'))
        """, (cobranca_id, cobranca_id))
    conn.commit()
    cur.close()
