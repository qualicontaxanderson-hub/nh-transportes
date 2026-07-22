# -*- coding: utf-8 -*-
"""
Classificação de FORMA DE RECEBIMENTO das vendas (vendas_xml).

Devolve UMA das classes:
  PIX APP · PIX Manual · Débito APP · Débito Manual · Crédito APP ·
  Crédito Manual · Dinheiro · Cheque · Prazo · Transferência · Combo

REGRA (validada em 60 dias, 0 ambíguas):
  EIXO 1 — TIPO:
    - card_bandeira == 'Outros'                          -> PIX
    - card_bandeira em {Visa, Mastercard, Elo, Cabal, Amex, Hipercard}
      OU (card_bandeira vazio E tef_terminal preenchido) -> Cartão (Débito/Crédito pela forma)
    - Dinheiro / Cheque / Prazo / Transferência          -> pela própria forma_pagamento
    - forma com '+' (ex.: 'Dinheiro+Cartao Debito')      -> Combo
  EIXO 2 — ORIGEM (só PIX e Cartão):
    - autorização = NSU real (numérico 5+ dígitos, ou alfanumérico >= 25 chars) -> APP
    - autorização = dummy (000001..0099), texto/nome, ou vazia                  -> Manual

IMPORTANTE — o eixo APP/Manual serve para CONCILIAÇÃO (origem do dinheiro:
maquininha vs lançamento manual/conta), NÃO para detectar preço errado.
Validado: Débito/Crédito cobram o acréscimo ~95% das vezes tanto no APP quanto
no Manual — a diferença de preço é do TIPO (PIX = à vista, Cartão = +degrau),
não da origem. Para "acréscimo não cobrado" compare preço praticado x tabela do
dia, NÃO use esta classe.

Campos aceitos (todos de vendas_xml, nível cabeçalho):
  forma_pagamento, card_bandeira, card_credenciadora, card_autorizacao, tef_terminal
"""
import re
import unicodedata

_BANDEIRAS_REAIS = {'Visa', 'Mastercard', 'Elo', 'Cabal', 'Amex', 'Hipercard'}
_RE_DUMMY = re.compile(r'0*[1-9]\d?$')   # 000001..000099 (placeholder do SGA)


def _sem_acento(s):
    """Remove acentos e normaliza (resolve 'Cartão Débito' -> 'cartao debito')."""
    return ''.join(c for c in unicodedata.normalize('NFKD', s or '')
                   if not unicodedata.combining(c))


def _origem_app(card_autorizacao):
    """True se a autorização parece um NSU REAL (veio da maquininha = APP)."""
    a = (card_autorizacao or '').strip()
    if a == '':
        return False                       # vazia -> manual
    if _RE_DUMMY.match(a):
        return False                       # dummy 000001.. -> manual
    if a.isdigit() and len(a) >= 5:
        return True                        # NSU numérico (curto/longo)
    if len(a) >= 25:
        return True                        # NSU alfanumérico de ~30 chars
    return False                           # texto/nome/código curto -> manual


def classificar_recebimento(forma_pagamento, card_bandeira=None,
                            card_credenciadora=None, card_autorizacao=None,
                            tef_terminal=None):
    """Classe de recebimento (str). Ver docstring do módulo para a regra completa.

    Ex.:
      classificar_recebimento('Cartao Debito', 'Outros', '011..', '004324', 'PDV1')
        -> 'PIX APP'
      classificar_recebimento('Cartao Debito', 'Visa', '011..', '307840', 'V9B..')
        -> 'Débito APP'
      classificar_recebimento('Cartao Debito', 'Outros', '', 'PIX MENESES', 'PDV1')
        -> 'PIX Manual'
    """
    fp = (forma_pagamento or '').strip()
    fpn = _sem_acento(fp).lower()          # normaliza acento/mojibake

    if '+' in fp:
        return 'Combo'
    if fpn == 'dinheiro':
        return 'Dinheiro'
    if fpn == 'cheque':
        return 'Cheque'
    if 'prazo' in fpn or 'loja' in fpn:    # 'Credito Loja/Prazo', 'Credito Loja'
        return 'Prazo'
    if 'transf' in fpn:                     # 'Transferencia/Carteira', 'Transf. Bancaria'
        return 'Transferência'

    is_deb = 'debito' in fpn
    is_cred = 'credito' in fpn
    if not (is_deb or is_cred):
        return 'Outros'                    # forma inesperada (não deve ocorrer)

    band = (card_bandeira or '').strip()
    # bandeira 'Outros' = PIX; qualquer outra (real, OU vazia com/sem tef) = Cartão.
    # (Validação: bandeira vazia sem tef não ocorre -> 0 ambíguas.)
    tipo = 'PIX' if band == 'Outros' else 'Cartão'

    origem = 'APP' if _origem_app(card_autorizacao) else 'Manual'

    if tipo == 'PIX':
        return f'PIX {origem}'
    return f"{'Débito' if is_deb else 'Crédito'} {origem}"


# Cor sugerida por classe (hex do texto; fundo = cor + transparência).
CORES_RECEBIMENTO = {
    'PIX APP':        '#0d9488',   # turquesa
    'PIX Manual':     '#b45309',   # âmbar (manual = ponto de conciliação)
    'Débito APP':     '#1d4ed8',   # azul
    'Débito Manual':  '#2563eb',
    'Crédito APP':    '#7c3aed',   # roxo
    'Crédito Manual': '#8b5cf6',
    'Dinheiro':       '#059669',   # verde
    'Cheque':         '#475569',   # cinza
    'Prazo':          '#d97706',   # laranja
    'Transferência':  '#0891b2',   # ciano
    'Combo':          '#64748b',   # slate
    'Outros':         '#64748b',
}


def cor_recebimento(classe):
    """Hex da cor do texto para a classe (fallback slate)."""
    return CORES_RECEBIMENTO.get(classe, '#64748b')
