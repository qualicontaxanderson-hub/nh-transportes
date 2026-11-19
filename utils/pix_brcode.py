# -*- coding: utf-8 -*-
"""Pix "copia e cola" estático (BR Code, padrão EMV do Banco Central).

Usado no troco PIX: o ADMIN abre o troco, lê o QR ou copia o código no app do
Cora, e o banco já abre com a chave, o nome e o valor certos. Não passa por
banco nenhum: é só o texto padronizado (veio do Qualicontax, 19/11/2026).

Lições de lá: txid SEMPRE '***' em Pix estático (o identificador vai na
mensagem, campo 26-02; o Inter recusou txid próprio com DS04); nome até 25 e
cidade até 15 caracteres, sem acento, senão alguns bancos dizem "QR inválido".
"""
import re
import unicodedata


def _campo(id_, valor):
    return f'{id_}{len(valor):02d}{valor}'


def _limpo(s, n):
    s = unicodedata.normalize('NFKD', str(s or '')).encode('ascii', 'ignore').decode().upper()
    return re.sub(r'[^A-Z0-9 .\-]', '', s).strip()[:n] or 'X'


def _crc16(texto):
    crc = 0xFFFF
    for ch in texto.encode('utf-8'):
        crc ^= ch << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
    return f'{crc:04X}'


def chave_normalizada(tipo, chave):
    """Chave no formato que o Pix exige, a partir do cadastro do troco
    (troco_pix_clientes.tipo_chave_pix: CPF, CNPJ, TELEFONE, EMAIL,
    CHAVE_ALEATORIA). Devolve None quando a chave não serve (ex.: 'N/A')."""
    t = (tipo or '').strip().upper()
    c = (chave or '').strip()
    if t in ('CPF', 'CNPJ'):
        d = re.sub(r'\D', '', c)
        return d if len(d) == (11 if t == 'CPF' else 14) else None
    if t in ('TELEFONE', 'CELULAR'):
        d = re.sub(r'\D', '', c)
        if d.startswith('55') and len(d) in (12, 13):
            d = d[2:]
        return '+55' + d if len(d) in (10, 11) else None
    if t == 'EMAIL':
        c = c.lower()
        return c if re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', c) else None
    # aleatória: 32 hex com hífens (36 caracteres)
    return c.lower() if re.fullmatch(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}', c) else None


def copia_e_cola(chave, nome, valor=None, cidade='BRASIL', mensagem=''):
    gui = _campo('00', 'br.gov.bcb.pix') + _campo('01', chave)
    if mensagem:
        gui += _campo('02', _limpo(mensagem, 40))
    p = _campo('00', '01') + _campo('26', gui) + _campo('52', '0000') + _campo('53', '986')
    if valor:
        p += _campo('54', f'{float(valor):.2f}')
    p += _campo('58', 'BR') + _campo('59', _limpo(nome, 25)) + _campo('60', _limpo(cidade, 15))
    p += _campo('62', _campo('05', '***'))
    p += '6304'
    return p + _crc16(p)


def qr_svg_data_uri(texto):
    """QR do código em SVG embutido (segno, já usado no cupom NFC-e)."""
    import segno
    return segno.make(texto, error='m').svg_data_uri(scale=7, border=2)
