import re
import hashlib
from datetime import datetime


# Expressões regulares para extração de CNPJ e CPF
_RE_CNPJ = re.compile(r'\b(\d{2}[\.\s]?\d{3}[\.\s]?\d{3}[\/\s]?\d{4}[\-\s]?\d{2})\b')
_RE_CPF = re.compile(r'\b(\d{3}[\.\s]?\d{3}[\.\s]?\d{3}[\-\s]?\d{2})\b')


def _digits_only(value: str) -> str:
    """Retorna apenas os dígitos numéricos de *value*."""
    return re.sub(r'\D', '', value)


def _validate_cnpj(cnpj: str) -> bool:
    """Validação estrutural básica de CNPJ (verifica apenas o comprimento)."""
    digits = _digits_only(cnpj)
    return len(digits) == 14 and not digits == digits[0] * 14


def _validate_cpf(cpf: str) -> bool:
    """Validação estrutural básica de CPF (verifica apenas o comprimento)."""
    digits = _digits_only(cpf)
    return len(digits) == 11 and not digits == digits[0] * 11


def _extract_cnpj_cpf(text: str):
    """
    Extrai o primeiro CNPJ ou CPF válido encontrado em *text*.

    Retorna uma tupla (valor_somente_digitos, tipo_str) onde tipo_str é 'cnpj'
    ou 'cpf', ou (None, None) caso nada seja encontrado.
    """
    if not text:
        return None, None

    # Tenta CNPJ primeiro (mais específico)
    for match in _RE_CNPJ.finditer(text):
        candidate = _digits_only(match.group(1))
        if _validate_cnpj(candidate):
            return candidate, 'cnpj'

    # Fallback para CPF
    for match in _RE_CPF.finditer(text):
        candidate = _digits_only(match.group(1))
        if _validate_cpf(candidate):
            return candidate, 'cpf'

    return None, None


class OFXParser:
    """
    Parser para arquivos de extrato bancário no formato OFX (Open Financial Exchange).

    Suporta tanto o formato SGML (OFX v1.x) quanto o formato XML (OFX v2.x).
    """

    def __init__(self, content: str):
        """
        Inicializa o parser com o conteúdo bruto do arquivo OFX.

        :param content: Conteúdo textual bruto do arquivo OFX.
        """
        self._raw = content
        self._body = self._extract_body(content)

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    def get_account_info(self) -> dict:
        """Retorna um dicionário com informações básicas da conta extraídas do cabeçalho OFX."""
        return {
            'banco_nome': self._find_tag('FI>ORG') or self._find_tag('ORG') or '',
            'banco_id': self._find_tag('FI>FID') or self._find_tag('BANKID') or '',
            'agencia': self._find_tag('BRANCHID') or '',
            'conta': self._find_tag('ACCTID') or '',
            'tipo_conta': self._find_tag('ACCTTYPE') or '',
            'moeda': self._find_tag('CURDEF') or 'BRL',
        }

    def get_transactions(self) -> list:
        """
        Faz o parse e retorna uma lista de dicionários de transações.

        Cada dicionário contém:
            - fitid (str)
            - tipo  ('DEBIT' ou 'CREDIT')
            - data_transacao (datetime.date)
            - valor (float, sempre positivo)
            - descricao (str)
            - memo (str)
            - cnpj_cpf (str | None)
            - tipo_chave ('cnpj' | 'cpf' | None)
            - hash_dedup (str)
        """
        transactions = []
        stmttrn_blocks = re.findall(
            r'<STMTTRN>(.*?)</STMTTRN>',
            self._body,
            re.DOTALL | re.IGNORECASE,
        )
        if not stmttrn_blocks:
            # Fallback para arquivos SGML OFX v1.x que omitem a tag de fechamento </STMTTRN>.
            # Divide pelo marcador de abertura <STMTTRN> e captura o conteúdo até
            # o próximo delimitador de bloco ou marcador de fim de lista.
            raw_parts = re.split(r'<STMTTRN>', self._body, flags=re.IGNORECASE)
            for part in raw_parts[1:]:  # ignora tudo antes do primeiro <STMTTRN>
                end_m = re.search(
                    r'</BANKTRANLIST>|</STMTTRNRS>|</STMTTRN>|</OFX>',
                    part,
                    re.IGNORECASE,
                )
                stmttrn_blocks.append(part[:end_m.start()] if end_m else part)
        for block in stmttrn_blocks:
            tx = self._parse_transaction_block(block)
            if tx:
                transactions.append(tx)
        return transactions

    # ------------------------------------------------------------------
    # Auxiliares internos
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_body(content: str) -> str:
        """
        Remove o cabeçalho OFX v1.x (tudo antes do primeiro '<') e retorna
        o corpo no formato XML, normalizando tags SGML auto-fechadas para XML.
        """
        # Localiza o início do corpo XML
        idx = content.find('<')
        if idx == -1:
            return content
        body = content[idx:]

        # Normaliza CRLF do Windows e CR soltos para que um \r não seja confundido
        # com valor de tag, o que causaria <STMTTRN>\r → <STMTTRN>\r</STMTTRN>
        # e quebraria a extração de transações.
        body = body.replace('\r\n', '\n').replace('\r', '\n')

        # Converte tags SGML auto-fechadas: <TAG>valor → <TAG>valor</TAG>
        # Apenas quando a tag de fechamento NÃO já estiver presente logo após.
        def _maybe_close(m):
            tag = m.group(1)
            value = m.group(2).strip()
            close_tag = f'</{tag}>'
            # Verifica se o corpo original já possui a tag de fechamento após este trecho
            after = body[m.end():]
            if after.lower().startswith(close_tag.lower()):
                return m.group(0)  # tag de fechamento já presente – mantém sem alteração
            return f'<{tag}>{value}{close_tag}'

        # [^<\r\n]+ – exclui CR para que quebras de linha do Windows não entrem como valores
        body = re.sub(
            r'<([A-Z0-9.]+)>([^<\r\n]+)',
            _maybe_close,
            body,
        )
        return body

    def _find_tag(self, tag_path: str) -> str:
        """
        Localiza o conteúdo textual de uma tag (possivelmente aninhada) no corpo OFX.
        *tag_path* usa '>' como separador para buscas aninhadas (melhor esforço).
        """
        parts = tag_path.split('>')
        search = self._body
        for part in parts:
            pattern = re.compile(
                rf'<{re.escape(part)}>(.*?)</{re.escape(part)}>',
                re.DOTALL | re.IGNORECASE,
            )
            m = pattern.search(search)
            if not m:
                return ''
            search = m.group(1)
        return search.strip()

    def _parse_transaction_block(self, block: str) -> dict | None:
        """Faz o parse de um bloco <STMTTRN> e retorna um dicionário de transação."""

        def tag(name):
            # Primário: XML / SGML normalizado (tag de fechamento presente)
            m = re.search(
                rf'<{re.escape(name)}>(.*?)</{re.escape(name)}>',
                block,
                re.IGNORECASE | re.DOTALL,
            )
            if m:
                return m.group(1).strip()
            # Fallback: tag SGML folha bruta (valor termina na próxima tag ou quebra de linha)
            m2 = re.search(
                rf'<{re.escape(name)}>\s*([^<\r\n]+)',
                block,
                re.IGNORECASE,
            )
            return m2.group(1).strip() if m2 else ''

        trntype = tag('TRNTYPE').upper()
        dtposted = tag('DTPOSTED') or tag('DTUSER') or ''
        trnamt = tag('TRNAMT')
        fitid = tag('FITID')
        name = tag('NAME')
        memo = tag('MEMO')

        # Converte o valor para float
        try:
            amount = float(trnamt.replace(',', '.'))
        except (ValueError, AttributeError):
            return None

        # Determina DÉBITO / CRÉDITO
        if trntype in ('DEBIT', 'CHECK', 'PAYMENT', 'CASH', 'ATM', 'FEE', 'SRVCHG'):
            tipo = 'DEBIT'
            valor = abs(amount)
        elif trntype in ('CREDIT', 'DEP', 'INT', 'DIV', 'DIRECTDEP', 'XFER'):
            tipo = 'CREDIT'
            valor = abs(amount)
        else:
            # Fallback: valor negativo → débito, positivo → crédito
            tipo = 'DEBIT' if amount < 0 else 'CREDIT'
            valor = abs(amount)

        # Converte a data
        try:
            data_transacao = self._parse_date(dtposted)
        except ValueError:
            return None

        # Descrição: prefere NAME, usa MEMO como alternativa
        descricao = name or memo or ''

        # Extrai CNPJ / CPF da descrição + memo
        combined = f'{descricao} {memo}'
        cnpj_cpf, tipo_chave = _extract_cnpj_cpf(combined)

        # Gera o hash para deduplicação
        hash_dedup = self._make_hash(fitid, dtposted, trnamt, descricao)

        return {
            'fitid': fitid,
            'tipo': tipo,
            'data_transacao': data_transacao,
            'valor': valor,
            'descricao': descricao,
            'memo': memo,
            'cnpj_cpf': cnpj_cpf,
            'tipo_chave': tipo_chave,
            'hash_dedup': hash_dedup,
        }

    @staticmethod
    def _parse_date(dtstring: str):
        """
        Converte strings de data OFX como 20231215, 20231215120000,
        20231215120000[-3:BRT] em um objeto datetime.date.
        """
        # Remove o sufixo de fuso horário como [-3:BRT]
        dtstring = re.sub(r'\[.*\]', '', dtstring).strip()
        _fmt_lengths = {'%Y%m%d%H%M%S': 14, '%Y%m%d%H%M': 12, '%Y%m%d': 8}
        for fmt, n in _fmt_lengths.items():
            try:
                return datetime.strptime(dtstring[:n], fmt).date()
            except ValueError:
                continue
        raise ValueError(f'Não foi possível converter a data OFX: {dtstring!r}')

    @staticmethod
    def _make_hash(fitid: str, dtposted: str, trnamt: str, descricao: str) -> str:
        """Gera um digest SHA-256 em hexadecimal para deduplicação."""
        raw = f'{fitid}|{dtposted}|{trnamt}|{descricao}'
        return hashlib.sha256(raw.encode('utf-8')).hexdigest()
