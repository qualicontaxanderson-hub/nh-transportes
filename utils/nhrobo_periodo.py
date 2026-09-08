# -*- coding: utf-8 -*-
"""De que documento e de que periodo e o arquivo que acabou de chegar.

Existe para a aba Historico responder "extrato de agosto" em vez de so
"arquivo.ofx". Quem pergunta no escritorio nunca pergunta pelo nome do arquivo:
pergunta se o extrato de agosto ja veio.

TRES FONTES, NESTA ORDEM:

  1. o conteudo -- OFX diz DTSTART/DTEND, XML de nota diz a data de emissao e o
     SPED diz o periodo no registro 0000. E o unico jeito que nao chuta;
  2. o nome do arquivo, quando o conteudo nao diz nada (planilha, PDF);
  3. nada -- e a tela mostra um travessao.

O travessao e resposta, nao falha. Periodo chutado e o erro que ninguem
percebe: quem le a tela acredita, e so descobre meses depois, na conferencia.

NADA AQUI PODE LEVANTAR EXCECAO PARA CIMA. Isto roda no caminho do upload,
depois de o arquivo ja estar no Dropbox: estourar aqui trocaria um periodo
desconhecido -- que a tela sabe mostrar -- por uma linha de historico perdida.
"""
import calendar
import datetime as _dt
import re

#: Ate onde ler do arquivo. DTSTART de OFX, registro 0000 de SPED e dhEmi de
#: XML vivem todos no comeco; ler um SPED de 300 MB inteiro para achar uma data
#: que esta na primeira linha so gastaria memoria do servidor.
_LIMITE_LEITURA = 512 * 1024

#: O rotulo que a tela mostra. Vale por familia, nao por extensao: para quem
#: olha a lista, .xlsx e .csv sao a mesma coisa -- planilha.
_POR_EXT = {
    '.ofx': 'extrato',
    '.xml': 'xml',
    '.txt': 'texto',
    '.xlsx': 'planilha', '.xls': 'planilha', '.csv': 'planilha',
    '.pdf': 'pdf',
    '.jpg': 'imagem', '.jpeg': 'imagem', '.png': 'imagem',
    '.zip': 'zip',
    '.pfx': 'certificado', '.p12': 'certificado',
    '.dec': 'declaracao', '.rec': 'recibo',
}

_ULTIMO_DIA = lambda a, m: calendar.monthrange(a, m)[1]


def _texto(conteudo):
    """Os primeiros KB como texto, sem nunca falhar.

    latin-1 de proposito: ele aceita qualquer byte. utf-8 estoura no meio de um
    SPED com acento em ISO-8859-1, que e como a maioria sai dos sistemas
    fiscais -- e o arquivo bom ficaria sem periodo por causa de um cedilha.
    """
    if not conteudo:
        return ''
    if isinstance(conteudo, str):
        return conteudo[:_LIMITE_LEITURA]
    return conteudo[:_LIMITE_LEITURA].decode('latin-1', 'replace')


def _data(ano, mes, dia):
    try:
        return _dt.date(int(ano), int(mes), int(dia))
    except (ValueError, TypeError):
        return None


# ── o conteudo ───────────────────────────────────────────────────────────────

def _do_ofx(txt):
    """DTSTART/DTEND do extrato. Formato OFX: AAAAMMDD, com hora opcional."""
    def pega(tag):
        m = re.search(r'<%s>\s*(\d{8})' % tag, txt, re.I)
        return _data(m.group(1)[:4], m.group(1)[4:6], m.group(1)[6:8]) if m else None

    ini, fim = pega('DTSTART'), pega('DTEND')
    if ini or fim:
        return ini or fim, fim or ini
    # Extrato sem cabecalho de periodo ainda tem as datas dos lancamentos. E o
    # periodo REAL do que veio, que e o que a pessoa quer saber.
    datas = [d for d in (_data(x[:4], x[4:6], x[6:8])
                         for x in re.findall(r'<DTPOSTED>\s*(\d{8})', txt, re.I)) if d]
    return (min(datas), max(datas)) if datas else (None, None)


def _do_xml(txt):
    """A data de emissao da nota. Um dia so: emissao nao tem intervalo."""
    m = re.search(r'<(?:dhEmi|dEmi|dhRecbto)>\s*(\d{4})-(\d{2})-(\d{2})', txt)
    if not m:
        return None, None
    d = _data(m.group(1), m.group(2), m.group(3))
    return d, d


def _do_sped(txt):
    """DT_INI e DT_FIN do registro 0000, em DDMMAAAA.

    Nao conto campos por posicao: o 0000 do SPED Fiscal e o do Contribuicoes
    tem layouts diferentes, e o layout muda de ano para ano. Duas datas seguidas
    na linha 0000 sao o periodo nos dois -- e e o unico par de datas que aparece
    ali.
    """
    linha = next((l for l in txt.splitlines() if l.startswith('|0000|')), None)
    if not linha:
        return None, None
    campos = linha.split('|')
    datas = []
    for c in campos:
        if re.fullmatch(r'\d{8}', c or ''):
            d = _data(c[4:], c[2:4], c[:2])       # DDMMAAAA
            if d:
                datas.append(d)
    if len(datas) >= 2:
        return min(datas[:2]), max(datas[:2])
    return (datas[0], datas[0]) if datas else (None, None)


# ── o nome ───────────────────────────────────────────────────────────────────

#: Mes e ano no nome do arquivo. As tres formas que aparecem de verdade:
#: "07-2026", "2026-07" e "072026". Nome de mes por extenso ficou de fora de
#: proposito -- "agosto.ofx" nao diz de que ano, e o ano do arquivo nem sempre e
#: o ano do documento (o SPED de dezembro se manda em janeiro).
_NO_NOME = [
    re.compile(r'(?<!\d)(0[1-9]|1[0-2])[-_./ ](20\d{2})(?!\d)'),      # 07-2026
    re.compile(r'(?<!\d)(20\d{2})[-_./ ](0[1-9]|1[0-2])(?!\d)'),      # 2026-07
    re.compile(r'(?<!\d)(0[1-9]|1[0-2])(20\d{2})(?!\d)'),             # 072026
]


def _do_nome(nome):
    """O mes inteiro, quando o nome diz qual e.

    O (?<!\\d) e o (?!\\d) nao sao capricho: sem eles, a chave de 44 digitos de
    uma NF-e casa com qualquer coisa, e toda nota ganharia um periodo inventado.
    """
    base = re.sub(r'\.[A-Za-z0-9]{1,5}$', '', nome or '')
    for i, rx in enumerate(_NO_NOME):
        m = rx.search(base)
        if not m:
            continue
        mes, ano = (m.group(2), m.group(1)) if i == 1 else (m.group(1), m.group(2))
        ini = _data(ano, mes, 1)
        if ini:
            return ini, _data(ano, mes, _ULTIMO_DIA(int(ano), int(mes)))
    return None, None


# ── a porta de entrada ───────────────────────────────────────────────────────

def identificar(nome, conteudo=None, ext=None):
    """(tipo, periodo_ini, periodo_fim, fonte) do arquivo que chegou.

    fonte e 'arquivo' quando saiu de dentro dele, 'nome' quando saiu do nome, e
    None quando nada disse -- e ai as duas datas tambem sao None.
    """
    try:
        return _identificar(nome, conteudo, ext)
    except Exception:                      # noqa: BLE001 -- ver o cabecalho
        return (None, None, None, None)


def _identificar(nome, conteudo, ext):
    ext = (ext or re.sub(r'^.*(\.[A-Za-z0-9]{1,5})$', r'\1', nome or '')).lower()
    tipo = _POR_EXT.get(ext)
    txt = _texto(conteudo)

    ini = fim = None
    if ext == '.ofx':
        ini, fim = _do_ofx(txt)
    elif ext == '.xml':
        ini, fim = _do_xml(txt)
        # O XML diz o que ele e melhor do que a extensao: NF-e, NFC-e e CT-e
        # sao tres coisas diferentes na mesma extensao.
        if re.search(r'<infCte\b', txt):
            tipo = 'cte'
        elif re.search(r'<infNFe\b', txt):
            tipo = 'nfce' if re.search(r'<mod>\s*65', txt) else 'nfe'
    elif ext == '.txt':
        ini, fim = _do_sped(txt)
        if ini:
            tipo = 'sped'

    if ini or fim:
        return (tipo, ini or fim, fim or ini, 'arquivo')

    ini, fim = _do_nome(nome)
    if ini:
        return (tipo, ini, fim, 'nome')
    return (tipo, None, None, None)


def rotulo(ini, fim):
    """O periodo como a tela mostra. Vazio quando nao ha periodo."""
    if not ini and not fim:
        return ''
    if not fim or ini == fim:
        return (ini or fim).strftime('%d/%m/%Y')
    if (ini.year, ini.month) == (fim.year, fim.month) \
            and ini.day == 1 and fim.day == _ULTIMO_DIA(fim.year, fim.month):
        # Mes fechado e o caso comum (SPED, extrato mensal): "08/2026" diz mais
        # rapido do que "01/08 a 31/08/2026".
        return ini.strftime('%m/%Y')
    if ini.year == fim.year:
        return '%s a %s' % (ini.strftime('%d/%m'), fim.strftime('%d/%m/%Y'))
    return '%s a %s' % (ini.strftime('%d/%m/%Y'), fim.strftime('%d/%m/%Y'))
