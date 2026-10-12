# -*- coding: utf-8 -*-
"""Placa e motorista de uma NF-e de compra, lidos do XML.

A NF-e não tem campo próprio de motorista e a placa só às vezes vem em
<veicTransp>. Cada distribuidora escreve do seu jeito — por isso a busca vai
do campo estruturado pro texto livre:

  placa:     <veicTransp><placa>  ->  <obsCont xCampo="PLACA">  ->  texto livre
             ("Placa: RDT7H76", "Veiculo = TFO3I53_01", "Placa(s) = GO TFZ-1H25")
  motorista: <obsCont xCampo="MOTORISTA">  ->  texto livre
             ("Motorista: FULANO - CPF", "Nome do Motorista = FULANO")

  texto livre = infCpl, infAdProd (por item) e infAdFisco.
  Vários veículos (cavalo + carreta): fica a primeira placa.

Só leitura do XML: não decide nada, só devolve o que achou (ou None).
"""
import re
import unicodedata

_PLACA = r'([A-Z]{3})-?\s?(\d[A-Z0-9]\d{2})'
_RE_VEIC = re.compile(r'<veicTransp>.*?<placa>\s*([A-Za-z0-9-]+)\s*</placa>', re.S)
_RE_OBS = re.compile(r'<obsCont\s+xCampo="([^"]+)"\s*>\s*<xTexto>(.*?)</xTexto>', re.S | re.I)
_RE_LIVRE = re.compile(r'<(infCpl|infAdProd|infAdFisco)>(.*?)</\1>', re.S)
# "Placa: X", "Veiculo = X/", "Placa(s) = GO TFZ-1H25" (UF na frente), "Placas: X / Y"
_RE_PLACA_TXT = re.compile(
    r'(?:PLACA|VE[IÍ]CULO|CAVALO)(?:\(S\)|S)?\s*[:.=\-]?\s*(?:[A-Z]{2}\s)?' + _PLACA, re.I)
# nome: palavras de letras separadas por UM espaço; para em dígito, travessão,
# dois espaços ou fim de tag
_RE_MOT_TXT = re.compile(
    r'MOTORISTA\s*[:.=\-]?\s*([A-ZÀ-Ú][A-ZÀ-Ú]+(?: [A-ZÀ-Ú][A-ZÀ-Ú]*)*)', re.I)
# rótulo grudado no nome ("BATISTAPlaca : ...") corta mesmo sem espaço;
# os curtos/comuns (RG, CAVALO) só como palavra, pra não cortar JORGE
_PARA = re.compile(r'(CPF|CNH|PLACA|VE[IÍ]CULO|\bRG\b|\bCAVALO\b|\bCARRETA\b).*$', re.I)


def _placa(txt):
    m = re.search(_PLACA, (txt or '').upper())
    return (m.group(1) + m.group(2)) if m else None


def _nome(txt):
    nome = _PARA.sub('', (txt or '').strip()).strip(' -:.=')
    nome = re.sub(r'\s+', ' ', nome).upper()
    return nome[:60] if len(nome) >= 5 else None


def extrair_placa_motorista(xml):
    """xml: str ou bytes do XML da NF-e. Devolve (placa, motorista)."""
    if isinstance(xml, bytes):
        xml = xml.decode('utf-8', errors='replace')
    xml = unicodedata.normalize('NFC', xml or '')
    placa = motorista = None

    m = _RE_VEIC.search(xml)
    if m:
        placa = _placa(m.group(1))
    obs = {k.strip().upper(): v for k, v in _RE_OBS.findall(xml)}
    if not placa and 'PLACA' in obs:
        placa = _placa(obs['PLACA'])
    if 'MOTORISTA' in obs:
        motorista = _nome(obs['MOTORISTA'])

    livre = ' '.join(t for _, t in _RE_LIVRE.findall(xml))
    if not placa:
        m = _RE_PLACA_TXT.search(livre)
        if m:
            placa = m.group(1).upper() + m.group(2).upper()
    if not motorista:
        m = _RE_MOT_TXT.search(livre)
        if m:
            motorista = _nome(m.group(1))
    return placa, motorista
