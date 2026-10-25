"""
Troco PIX × o que o BANCO diz de quem recebeu.

O cadastro do cliente PIX é digitado na pista ("WLTECI", "NELSOM"); o banco
devolve no extrato o nome e o CPF/CNPJ do DONO da chave. Nada aqui grava: o
nome e o documento do banco vêm, na hora, dos trocos já conciliados
(troco_pix.bank_transaction_id -> bank_transactions), então nunca ficam velhos
nem precisam de coluna nova.

Medido em 24/10/2026 nos 259 clientes com troco conciliado: cada um caiu
sempre no MESMO documento (nenhum variou); 182 com o nome igual, 66 parecidos
(digitação, nome incompleto) e 10 em que a chave é de OUTRA pessoa — o
cadastro MARCELO ROSA DE OLIVEIRA tem como chave o CPF da ALVANIRA. Esses não
podem ser "corrigidos": a tela só avisa.

Nada aqui é decidido sozinho: a tela mostra a diferença e quem quiser troca
o nome no botão "Atualizar nome" (só para os parecidos).
"""
import re
import unicodedata
from difflib import SequenceMatcher

# 'Transf Pix enviada - NOME - 000.000.000-00' (Cora). O MEI vem com a raiz
# do CNPJ na frente: '50.597.413 JEAN SIMIONI DOS SANTOS'.
_TEXTO = re.compile(r'^.*?\s-\s(?P<nome>.+?)\s+-\s+[\d./-]+\s*$')
_RAIZ_MEI = re.compile(r'^\d{2}\.\d{3}\.\d{3}\s+')


def sem_acento(txt):
    t = unicodedata.normalize('NFKD', txt or '').encode('ascii', 'ignore').decode()
    return re.sub(r'\s+', ' ', t.upper()).strip()


def so_digitos(txt):
    return re.sub(r'\D', '', txt or '')


def doc_formatado(d):
    if len(d) == 11:
        return f'{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}'
    if len(d) == 14:
        return f'{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}'
    return d


def _conserta(txt):
    """'ABÃ­LIO' -> 'ABÍLIO': parte dos OFX foi gravada com o UTF-8 lido
    como Latin-1. Só troca se a volta der certo."""
    if 'Ã' not in txt and 'Â' not in txt:
        return txt
    try:
        return txt.encode('latin-1').decode('utf-8')
    except (UnicodeEncodeError, UnicodeDecodeError):
        return txt


def nome_do_texto(descricao):
    """O nome do favorecido no texto do banco, em maiúsculas; None se o
    texto não tem o formato 'tipo - NOME - documento'."""
    m = _TEXTO.match(descricao or '')
    if not m:
        return None
    nome = _RAIZ_MEI.sub('', _conserta(m.group('nome'))).strip()
    return re.sub(r'\s+', ' ', nome.upper()) or None


# Sufixo de empresa não diz quem é: 'MENEZES E MENEZES' e 'MENESES E MENESES
# TRANSPORTES LTDA' são a mesma.
_SUFIXOS = re.compile(r'\b(LTDA|EIRELI|ME|EPP|MEI|S\.?A|UNIPESSOAL|TRANSPORTES?|LOGISTICA|E|DOS?|DAS?)\b')


def _essencia(nome):
    return re.sub(r'\s+', ' ', _SUFIXOS.sub(' ', sem_acento(nome))).strip()


def comparar_nome(cliente, banco):
    """'igual' | 'parecido' | 'outra' — o cadastro × o banco.

    Parecido: diferença de digitação/acento ou nome incompleto. O resto é
    chave de OUTRA pessoa — mesmo quando a chave é um CPF/CNPJ: o cadastro
    MARCELO ROSA DE OLIVEIRA tem o CPF da ALVANIRA como chave, e "atualizar"
    trocaria o cliente pela pessoa que recebe.
    """
    a, b = sem_acento(cliente.get('nome_completo')), sem_acento(banco['nome'])
    if a == b:
        return 'igual'
    ea, eb = _essencia(a), _essencia(b)
    if ea and eb and (ea in eb or eb in ea or SequenceMatcher(None, ea, eb).ratio() >= 0.8):
        return 'parecido'
    return 'outra'


def do_banco(cursor, cliente_ids=None):
    """{cliente_id: {'nome', 'doc', 'docs', 'data'}} pelos trocos conciliados.
    'nome'/'doc' são os do troco mais recente; 'docs' todos os documentos em
    que os trocos dele já caíram."""
    filtro, args = '', []
    if cliente_ids:
        filtro = f" AND tp.troco_pix_cliente_id IN ({','.join(['%s'] * len(cliente_ids))})"
        args = list(cliente_ids)
    cursor.execute(
        f"""SELECT tp.troco_pix_cliente_id AS cid, bt.data_transacao, bt.descricao, bt.cnpj_cpf
              FROM troco_pix tp
              JOIN bank_transactions bt ON bt.id = tp.bank_transaction_id
             WHERE tp.troco_pix_cliente_id IS NOT NULL{filtro}
             ORDER BY bt.data_transacao, bt.id""",
        args,
    )
    r = {}
    for row in cursor.fetchall():
        doc = so_digitos(row['cnpj_cpf'])
        nome = nome_do_texto(row['descricao'])
        g = r.setdefault(row['cid'], {'nome': None, 'doc': None, 'docs': set(), 'data': None})
        if doc:
            g['docs'].add(doc)
        if nome:            # o mais recente vence (ORDER BY data)
            g['nome'], g['doc'], g['data'] = nome, doc, row['data_transacao']
            g['doc_fmt'] = doc_formatado(doc)
    return r
