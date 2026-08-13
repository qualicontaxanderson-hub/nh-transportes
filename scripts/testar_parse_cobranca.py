# -*- coding: utf-8 -*-
"""Testa a extracao de cobranca (<cobr><dup>) e forma de pagamento (<pag>).

Nao precisa de banco nem de rede: monta XML de NF-e na mao e passa pelo parser
de verdade (scripts/processa_dfe.py). O que importa aqui e o parser NUNCA
derrubar a captura — nota sem <cobr> e o caso mais comum de combustivel.

Uso:
    python scripts/testar_parse_cobranca.py
"""
import os
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# consulta_sefaz monta os parametros de conexao no import e exige DB_PASSWORD.
# Aqui nada conecta — e so parse de XML —, entao uma senha de mentira serve.
os.environ.setdefault('DB_PASSWORD', 'teste-offline')
os.environ.setdefault('SECRET_KEY', 'x')

import processa_dfe as p  # noqa: E402

NS = 'http://www.portalfiscal.inf.br/nfe'


def nfe(miolo=''):
    """NF-e minima e valida o bastante para o parser aceitar."""
    return ET.fromstring("""<nfeProc xmlns="%s" versao="4.00">
      <NFe><infNFe Id="NFe52260802284585000144550020000008381000008387" versao="4.00">
        <ide><nNF>838</nNF><serie>2</serie><mod>55</mod>
             <dhEmi>2026-08-01T09:15:00-03:00</dhEmi></ide>
        <emit><CNPJ>02284585000144</CNPJ><xNome>DISTRIBUIDORA TABOCAO LTDA</xNome></emit>
        <dest><CNPJ>11111111000111</CNPJ></dest>
        <det nItem="1"><prod><cProd>GC</cProd><xProd>GASOLINA COMUM</xProd>
            <NCM>27101259</NCM><uCom>LT</uCom><qCom>5000.0000</qCom>
            <vUnCom>1.7400</vUnCom><vProd>8700.00</vProd></prod></det>
        <total><ICMSTot><vNF>8700.00</vNF></ICMSTot></total>
        %s
      </infNFe></NFe>
      <protNFe><infProt><cStat>100</cStat></infProt></protNFe>
    </nfeProc>""" % (NS, miolo))


def caso(nome, miolo, checar):
    nota = p.extrair_nota(nfe(miolo))
    checar(nota)
    print('OK  %s' % nome)


def main():
    # 1) Combustivel tipico: parcela unica, vencimento no dia seguinte.
    def c1(n):
        assert len(n['duplicatas']) == 1, n['duplicatas']
        d = n['duplicatas'][0]
        assert d['vencimento'] == '2026-08-02', d
        assert d['valor'] == '8700.00', d
        assert n['pagamento']['ind'] == '1' and n['pagamento']['tipo'] == '15', n['pagamento']
    caso('parcela unica (combustivel)', """
        <cobr><fat><nFat>838</nFat><vOrig>8700.00</vOrig><vLiq>8700.00</vLiq></fat>
          <dup><nDup>001</nDup><dVenc>2026-08-02</dVenc><vDup>8700.00</vDup></dup></cobr>
        <pag><detPag><indPag>1</indPag><tPag>15</tPag><vPag>8700.00</vPag></detPag></pag>
    """, c1)

    # 2) A vista, SEM bloco de cobranca — o caso mais comum. Nao pode quebrar.
    def c2(n):
        assert n['duplicatas'] == [], n['duplicatas']
        assert n['pagamento']['ind'] == '0', n['pagamento']
        assert n['valor_total'] == '8700.00'      # o resto da nota segue intacto
    caso('a vista, sem <cobr>', """
        <pag><detPag><indPag>0</indPag><tPag>01</tPag><vPag>8700.00</vPag></detPag></pag>
    """, c2)

    # 3) Nota parcelada (pneu/peca): tem de virar N linhas, na ordem.
    def c3(n):
        vencs = [d['vencimento'] for d in n['duplicatas']]
        assert vencs == ['2026-09-01', '2026-10-01', '2026-11-01'], vencs
        assert [d['n_dup'] for d in n['duplicatas']] == ['001', '002', '003']
    caso('parcelada 30/60/90', """
        <cobr>
          <dup><nDup>001</nDup><dVenc>2026-09-01</dVenc><vDup>2900.00</vDup></dup>
          <dup><nDup>002</nDup><dVenc>2026-10-01</dVenc><vDup>2900.00</vDup></dup>
          <dup><nDup>003</nDup><dVenc>2026-11-01</dVenc><vDup>2900.00</vDup></dup>
        </cobr>
    """, c3)

    # 4) Duplicata SEM nDup (o campo e opcional): precisa numerar sozinho,
    #    senao a chave unica (documento_id, n_dup) colide e some parcela.
    def c4(n):
        assert [d['n_dup'] for d in n['duplicatas']] == ['001', '002'], n['duplicatas']
    caso('sem nDup (numera sozinho)', """
        <cobr>
          <dup><dVenc>2026-09-01</dVenc><vDup>100.00</vDup></dup>
          <dup><dVenc>2026-10-01</dVenc><vDup>100.00</vDup></dup>
        </cobr>
    """, c4)

    # 5) Data torta nao pode virar excecao nem gravar lixo no campo DATE.
    def c5(n):
        assert n['duplicatas'][0]['vencimento'] is None, n['duplicatas']
        assert n['duplicatas'][0]['valor'] == '100.00'
    caso('dVenc invalido vira NULL', """
        <cobr><dup><nDup>001</nDup><dVenc>0000-00-00</dVenc><vDup>100.00</vDup></dup></cobr>
    """, c5)

    # 6) Sem <pag> nenhum (layout antigo): nao pode estourar.
    def c6(n):
        assert n['pagamento'] == {'ind': None, 'tipo': None}, n['pagamento']
        assert n['duplicatas'] == []
    caso('sem <pag> e sem <cobr>', '', c6)

    # 7) indPag no <ide> (layout 3.10) em vez de <detPag>.
    def c7(n):
        assert n['pagamento']['ind'] == '1', n['pagamento']
    caso('indPag no layout antigo', """
        <indPag>1</indPag>
        <cobr><dup><nDup>001</nDup><dVenc>2026-08-02</dVenc><vDup>8700.00</vDup></dup></cobr>
    """, c7)

    print('\nTudo certo: o vencimento sai da nota e nenhum caso derruba a captura.')


if __name__ == '__main__':
    main()
