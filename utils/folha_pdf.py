"""Lê o PDF da folha de pagamento e devolve, por pessoa, o que vai para a tela
de Lançamento de Funcionários (06/11/2026).

Entende dois formatos:
  - "Relação de Cálculo" (analítico do sistema de folha da contabilidade):
    SALÁRIO BASE = Proventos; FGTS = soma dos eventos de FGTS; quem foi
    demitido no mês tem 13º/férias/1/3 separados em Rescisão e o resto
    (saldo de salário, extras, feriado...) em SALÁRIO BASE.
  - "Recibo de Pagamento" avulso (quem ainda não está registrado):
    evento 1102 = Vale Alimentação; o resto dos proventos = SALÁRIO BASE.
Holerite ("Demonstrativo de Pagamento") e TRCT repetem o que já está na
Relação de Cálculo: são reconhecidos e ignorados.
"""
import io
import re

_VAL = r'\d{1,3}(?:\.\d{3})*,\d{2}'
# um evento: código, tipo (1 provento, 2 vantagem, 3 desconto, 4 informativo),
# descrição, referência opcional (horas, %, avos) e valor
_EVENTO = re.compile(
    r'(?P<cod>\d{1,4}) (?P<t>[1-4]) (?P<desc>.+?) '
    r'(?:(?P<ref>\d{1,3}:\d{2} hs|\d+,\d{2} %|\d+ Avos) )?'
    r'(?P<val>' + _VAL + r')(?! ?%| ?hs| ?Avos)(?= |$)')
_RESCISAO = re.compile(r'13o|13º|f[ée]rias|1/3', re.I)


def _num(s):
    return round(float(s.replace('.', '').replace(',', '.')), 2)


def _texto(conteudo):
    from pypdf import PdfReader
    r = PdfReader(io.BytesIO(conteudo))
    return '\n'.join((p.extract_text() or '') for p in r.pages)


def _relacao_calculo(txt):
    pessoas = []
    blocos = re.split(r'\nFunc: +\d+ +', '\n' + txt)[1:]
    for b in blocos:
        nome = re.match(r'(.+?) +Adm ', b)
        prov = re.search(r'Proventos: +(' + _VAL + ')', b)
        if not nome or not prov:
            continue
        demitido = bool(re.search(r'Situação: +Demitido', b))
        eventos = []
        for linha in b.split('\n'):
            for m in _EVENTO.finditer(linha.strip()):
                eventos.append((m.group('t'), m.group('desc').strip(), _num(m.group('val'))))
        proventos = _num(prov.group(1))
        fgts = round(sum(v for t, d, v in eventos if t == '4' and d.upper().startswith('FGTS')), 2)
        rescisao = 0.0
        if demitido:
            rescisao = round(sum(v for t, d, v in eventos if t == '1' and _RESCISAO.search(d)), 2)
        # INSS do empregado (1950 normal, 1951 s/ 13º): só vai para a tela
        # nos motoristas, de quem a empresa não desconta (vira despesa)
        inss = round(sum(v for t, d, v in eventos if t == '3' and d.upper().startswith('INSS')), 2)
        p = {'nome': nome.group(1).strip(), 'origem': 'folha',
             'salario_base': round(proventos - rescisao, 2), 'fgts': fgts, 'inss': inss}
        if rescisao:
            p['rescisao'] = rescisao
            p['demitido'] = True
        pessoas.append(p)
    return pessoas


def _recibo_avulso(txt):
    m = re.search(r'NOME DO FUNCIONÁRIO.*\n\s*\d+ +([A-ZÀ-Ü][A-ZÀ-Ü .]+?)\s*\n', txt)
    if not m:
        return []
    sal = va = 0.0
    for cod, val in re.findall(r'^\s*(\d{1,4}) +\S+ +(' + _VAL + r')\s*$', txt, re.M):
        if cod == '1102':
            va += _num(val)
        else:
            sal += _num(val)
    p = {'nome': m.group(1).strip(), 'origem': 'recibo', 'salario_base': round(sal, 2)}
    if va:
        p['va'] = round(va, 2)
    return [p]


def ler(conteudo, nome_arquivo=''):
    """-> (pessoas, aviso). aviso explica quando o arquivo é ignorado."""
    try:
        txt = _texto(conteudo)
    except Exception as e:  # PDF corrompido / protegido
        return [], 'não deu para ler o PDF (%s)' % e.__class__.__name__
    if 'Relação de Cálculo' in txt:
        return _relacao_calculo(txt), None
    if 'TERMO DE RESCIS' in txt:
        return [], 'TRCT: os valores da rescisão já vêm da Relação de Cálculo'
    if 'Demonstrativo de Pagamento' in txt:
        return [], 'holerite: os valores já vêm da Relação de Cálculo'
    if 'RECIBO DE PAGAMENTO' in txt:
        return _recibo_avulso(txt), None
    return [], 'formato não reconhecido'
