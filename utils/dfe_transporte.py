# -*- coding: utf-8 -*-
"""Placa e motorista de uma NF-e de compra, lidos do XML.

A NF-e não tem campo próprio de motorista e a placa só às vezes vem em
<veicTransp>. Cada distribuidora escreve do seu jeito — por isso a busca vai
do campo estruturado pro texto livre:

  placa:     <veicTransp><placa>  ->  <obsCont xCampo="PLACA">  ->  infCpl
             ("Placa: RDT7H76", "Veículo: TFO3I53_01")
  motorista: <obsCont xCampo="MOTORISTA">  ->  infCpl ("Motorista: FULANO - CPF")

Só leitura do XML: não decide nada, só devolve o que achou (ou None).
"""
import re
import unicodedata

_PLACA = r'([A-Z]{3})-?\s?(\d[A-Z0-9]\d{2})'
_RE_VEIC = re.compile(r'<veicTransp>.*?<placa>\s*([A-Za-z0-9-]+)\s*</placa>', re.S)
_RE_OBS = re.compile(r'<obsCont\s+xCampo="([^"]+)"\s*>\s*<xTexto>(.*?)</xTexto>', re.S | re.I)
_RE_INFCPL = re.compile(r'<infCpl>(.*?)</infCpl>', re.S)
_RE_PLACA_TXT = re.compile(r'(?:PLACA|VE[IÍ]CULO|CAVALO)\s*[:.\-]?\s*' + _PLACA, re.I)
# nome: letras e espaços simples; para em CPF, travessão, dígito, outro rótulo
# ou dois espaços seguidos (o texto livre das distribuidoras é cheio deles)
_RE_MOT_TXT = re.compile(
    r'MOTORISTA\s*[:.\-]?\s*([A-ZÀ-Ú][A-ZÀ-Ú]+(?: [A-ZÀ-Ú][A-ZÀ-Ú]*)*)', re.I)
_PARA = re.compile(r'\b(CPF|CNH|PLACA|RG|VE[IÍ]CULO|CAVALO|CARRETA)\b.*$', re.I)


def _placa(txt):
    m = re.search(_PLACA, (txt or '').upper())
    return (m.group(1) + m.group(2)) if m else None


def _nome(txt):
    nome = _PARA.sub('', (txt or '').strip()).strip(' -:.')
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

    cpl = ' '.join(_RE_INFCPL.findall(xml))
    if not placa:
        m = _RE_PLACA_TXT.search(cpl)
        if m:
            placa = m.group(1).upper() + m.group(2).upper()
    if not motorista:
        m = _RE_MOT_TXT.search(cpl)
        if m:
            motorista = _nome(m.group(1))
    return placa, motorista
