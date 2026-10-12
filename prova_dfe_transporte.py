# -*- coding: utf-8 -*-
"""Prova do leitor de placa/motorista (utils/dfe_transporte) com os jeitos
reais que cada distribuidora escreve -- trechos copiados dos XMLs.

  python prova_dfe_transporte.py
"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from utils.dfe_transporte import extrair_placa_motorista as ler

CASOS = [
    ('Dislub: nome grudado no rótulo',
     '<infCpl>Envelope :  1-65163 Motorista : WELINGTON BRAZ BATISTAPlaca : RDT-7H76 / TFO3I53 / Em</infCpl>',
     ('RDT7H76', 'WELINGTON BRAZ BATISTA')),
    ('Tabocão: "Nome do Motorista =" no infCpl, placa com UF no infAdProd',
     '<det><infAdProd>Placa(s) = GO TFZ-1H25 GO RXP-0I78 - Nome Motorista= MARCOS ANTONIO BATISTA</infAdProd></det>'
     '<infCpl>- Nome do Motorista = MARCOS ANTONIO BATISTA - Produto a ser retirado</infCpl>',
     ('TFZ1H25', 'MARCOS ANTONIO BATISTA')),
    ('Temape: "Veiculo = X/ Motorista = Y" + obsCont PLACA',
     '<infCpl>IE: 107550547. # Veiculo = RDT7H76/ Motorista = WELINGTON BRAZ BATISTA</infCpl>'
     '<obsCont xCampo="PLACA"><xTexto>RDT7H76</xTexto></obsCont>',
     ('RDT7H76', 'WELINGTON BRAZ BATISTA')),
    ('Watt: infAdFisco, nome colado em números',
     '<infAdFisco>Placas: RDT-7H76 / TFO-3I53 / Motorista: WELINGTON BRAZ BATISTA0,0000,000</infAdFisco>',
     ('RDT7H76', 'WELINGTON BRAZ BATISTA')),
    ('ALE: "Veículo: TFO3I53_01 / Motorista:NOME" + CPF',
     '<infCpl>Veículo: TFO3I53_01 / Motorista:WELINGTON BATISTA    Ponto de Venda</infCpl>'
     '<obsCont xCampo="PLACA"><xTexto>TFO3I53_01</xTexto></obsCont>',
     ('TFO3I53', 'WELINGTON BATISTA')),
    ('veicTransp estruturado',
     '<transp><veicTransp><placa>RXP0I78</placa><UF>GO</UF></veicTransp></transp>',
     ('RXP0I78', None)),
    ('nome com RG dentro da palavra (JORGE) não corta',
     '<infCpl>Motorista: JORGE SILVA - CPF 123</infCpl>', (None, 'JORGE SILVA')),
    ('"COMB. P/ MOTOR" não é motorista',
     '<infCpl>COMB. P/ MOTOR INCLUSIVE DERIV. DE PETROLEO</infCpl>', (None, None)),
    ('nota sem nada', '<infCpl>Boletim de conformidade</infCpl>', (None, None)),
]

ok = True
for nome, xml, esperado in CASOS:
    obtido = ler(xml)
    bate = obtido == esperado
    ok = ok and bate
    print(('  OK   ' if bate else '  FALHA') + ' %s -> %s%s'
          % (nome, obtido, '' if bate else '  (esperado %s)' % (esperado,)))
print('\nRESULTADO: ' + ('TUDO OK' if ok else 'HÁ FALHA'))
sys.exit(0 if ok else 1)
