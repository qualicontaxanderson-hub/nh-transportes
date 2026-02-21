import re
import hashlib
from datetime import datetime


# Regex patterns for CNPJ and CPF extraction
_RE_CNPJ = re.compile(r'\b(\d{2}[\.\s]?\d{3}[\.\s]?\d{3}[\/\s]?\d{4}[\-\s]?\d{2})\b')
_RE_CPF = re.compile(r'\b(\d{3}[\.\s]?\d{3}[\.\s]?\d{3}[\-\s]?\d{2})\b')


def _digits_only(value: str) -> str:
    """Return only digit characters from *value*."""
    return re.sub(r'\D', '', value)


def _validate_cnpj(cnpj: str) -> bool:
    """Basic structural CNPJ validation (length only)."""
    digits = _digits_only(cnpj)
    return len(digits) == 14 and not digits == digits[0] * 14


def _validate_cpf(cpf: str) -> bool:
    """Basic structural CPF validation (length only)."""
    digits = _digits_only(cpf)
    return len(digits) == 11 and not digits == digits[0] * 11


def _extract_cnpj_cpf(text: str):
    """
    Extract the first valid CNPJ or CPF from *text*.

    Returns a tuple (value_digits_only, type_str) where type_str is 'cnpj'
    or 'cpf', or (None, None) if nothing was found.
    """
    if not text:
        return None, None

    # Try CNPJ first (more specific)
    for match in _RE_CNPJ.finditer(text):
        candidate = _digits_only(match.group(1))
        if _validate_cnpj(candidate):
            return candidate, 'cnpj'

    # Fallback to CPF
    for match in _RE_CPF.finditer(text):
        candidate = _digits_only(match.group(1))
        if _validate_cpf(candidate):
            return candidate, 'cpf'

    return None, None


class OFXParser:
    """
    Parser for OFX (Open Financial Exchange) bank statement files.

    Supports both SGML-style OFX (v1.x) and XML-style OFX (v2.x).
    """

    def __init__(self, content: str):
        """
        Initialise the parser with the raw OFX file content.

        :param content: Raw string content of the OFX file.
        """
        self._raw = content
        self._body = self._extract_body(content)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_account_info(self) -> dict:
        """Return a dict with basic account information from the OFX header."""
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
        Parse and return a list of transaction dicts.

        Each dict contains:
            - fitid (str)
            - tipo  ('DEBIT' or 'CREDIT')
            - data_transacao (datetime.date)
            - valor (float, always positive)
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
            # Fallback for SGML OFX v1.x files that omit the closing </STMTTRN> tag.
            # Split on each <STMTTRN> opening and take content up to the next
            # aggregate boundary or end-of-list marker.
            raw_parts = re.split(r'<STMTTRN>', self._body, flags=re.IGNORECASE)
            for part in raw_parts[1:]:  # skip everything before the first <STMTTRN>
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
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_body(content: str) -> str:
        """
        Strip OFX v1.x headers (everything before the first '<') and return
        the XML-like body, normalising self-closing SGML tags to XML.
        """
        # Find the start of the XML body
        idx = content.find('<')
        if idx == -1:
            return content
        body = content[idx:]

        # Convert SGML self-closing tags: <TAG>value → <TAG>value</TAG>
        # Only when the closing tag is NOT already present immediately after.
        def _maybe_close(m):
            tag = m.group(1)
            value = m.group(2).strip()
            close_tag = f'</{tag}>'
            # Check whether the original body already has the closing tag right after this match
            after = body[m.end():]
            if after.lower().startswith(close_tag.lower()):
                return m.group(0)  # closing tag already present – leave unchanged
            return f'<{tag}>{value}{close_tag}'

        body = re.sub(
            r'<([A-Z0-9.]+)>([^<\n]+)',
            _maybe_close,
            body,
        )
        return body

    def _find_tag(self, tag_path: str) -> str:
        """
        Find the text content of a (possibly nested) tag in the OFX body.
        *tag_path* uses '>' as a separator for nested lookups (best-effort).
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
        """Parse a single <STMTTRN> block and return a transaction dict."""

        def tag(name):
            # Primary: XML / normalized SGML (closing tag present)
            m = re.search(
                rf'<{re.escape(name)}>(.*?)</{re.escape(name)}>',
                block,
                re.IGNORECASE | re.DOTALL,
            )
            if m:
                return m.group(1).strip()
            # Fallback: raw SGML leaf tag (value ends at next tag or line break)
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

        # Parse amount
        try:
            amount = float(trnamt.replace(',', '.'))
        except (ValueError, AttributeError):
            return None

        # Determine DEBIT / CREDIT
        if trntype in ('DEBIT', 'CHECK', 'PAYMENT', 'CASH', 'ATM', 'FEE', 'SRVCHG'):
            tipo = 'DEBIT'
            valor = abs(amount)
        elif trntype in ('CREDIT', 'DEP', 'INT', 'DIV', 'DIRECTDEP', 'XFER'):
            tipo = 'CREDIT'
            valor = abs(amount)
        else:
            # Fallback: negative amount → debit, positive → credit
            tipo = 'DEBIT' if amount < 0 else 'CREDIT'
            valor = abs(amount)

        # Parse date
        try:
            data_transacao = self._parse_date(dtposted)
        except ValueError:
            return None

        # Description: prefer NAME, fall back to MEMO
        descricao = name or memo or ''

        # Extract CNPJ / CPF from description + memo
        combined = f'{descricao} {memo}'
        cnpj_cpf, tipo_chave = _extract_cnpj_cpf(combined)

        # Generate deduplication hash
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
        Parse OFX date strings such as 20231215, 20231215120000,
        20231215120000[-3:BRT] into a datetime.date object.
        """
        # Strip timezone suffix like [-3:BRT]
        dtstring = re.sub(r'\[.*\]', '', dtstring).strip()
        _fmt_lengths = {'%Y%m%d%H%M%S': 14, '%Y%m%d%H%M': 12, '%Y%m%d': 8}
        for fmt, n in _fmt_lengths.items():
            try:
                return datetime.strptime(dtstring[:n], fmt).date()
            except ValueError:
                continue
        raise ValueError(f'Cannot parse OFX date: {dtstring!r}')

    @staticmethod
    def _make_hash(fitid: str, dtposted: str, trnamt: str, descricao: str) -> str:
        """Generate a SHA-256 hex digest for deduplication."""
        raw = f'{fitid}|{dtposted}|{trnamt}|{descricao}'
        return hashlib.sha256(raw.encode('utf-8')).hexdigest()
