# -*- coding: utf-8 -*-
"""Cupom (NFC-e 65) e nota (NF-e 55) em PDF, iguais aos do app Qualicontax
(20/11/2026).

- NFC-e: utils/danfce.py (cópia do gerador da Qualicontax).
- NF-e:  brazilfiscalreport.danfe.Danfe (a mesma biblioteca e versão de lá).

O XML vem da pasta SAIDAS do Posto no Dropbox (a mesma que
integrations/vendas_pagamentos lê): <SAIDAS>/AAAA/MM/<chave>.xml. Aqui SÓ SE
LÊ: nada é gravado, movido nem apagado lá — a pasta é da Qualicontax.
Só para desenvolvimento: VENDAS_XML_LOCAL=<pasta SAIDAS sincronizada>.
"""
import os


def _ler_local(chave):
    base = (os.environ.get('VENDAS_XML_LOCAL') or '').strip()
    if not base:
        return None
    p = os.path.join(base, '20' + chave[2:4], chave[4:6], chave + '.xml')
    if os.path.exists(p):
        with open(p, 'rb') as f:
            return f.read()
    return None


def xml_da_chave(chave):
    """Bytes do XML autorizado, ou None se não achar."""
    chave = ''.join(ch for ch in (chave or '') if ch.isdigit())
    if len(chave) != 44:
        return None
    if os.environ.get('VENDAS_XML_LOCAL'):
        return _ler_local(chave)
    from integrations.dropbox_ofx import _criar_dbx, is_configured
    from integrations.vendas_pagamentos import _base
    if not is_configured():
        return None
    dbx = _criar_dbx()
    base = _base(dbx)
    if not base:
        return None
    # a chave traz AAMM da emissão (posições 3-6); o XML do fim do mês pode
    # cair na pasta do mês seguinte
    ano, mes = 2000 + int(chave[2:4]), int(chave[4:6])
    seguinte = (ano + 1, 1) if mes == 12 else (ano, mes + 1)
    for a, m in ((ano, mes), seguinte):
        try:
            _, resp = dbx.files_download('%s/%04d/%02d/%s.xml' % (base, a, m, chave))
            return resp.content
        except Exception:
            continue
    return None


def pdf_da_chave(chave):
    """(pdf_bytes, None) ou (None, motivo)."""
    try:
        xml = xml_da_chave(chave)
    except Exception as e:
        print('[cupom_pdf] XML %s: %s' % (chave, e))
        xml = None
    if not xml:
        return None, 'XML da nota ainda não está na pasta do Dropbox.'
    modelo = chave[20:22]
    try:
        if modelo == '65':
            from utils.danfce import gerar_danfce_pdf
            return gerar_danfce_pdf(xml), None
        from brazilfiscalreport.danfe import Danfe
        txt = xml.decode('utf-8', 'ignore') if isinstance(xml, bytes) else xml
        return bytes(Danfe(xml=txt).output()), None
    except Exception as e:
        print('[cupom_pdf] PDF %s: %s' % (chave, e))
        return None, 'Não consegui montar o PDF desta nota.'
