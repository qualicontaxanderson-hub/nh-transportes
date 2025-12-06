import re

def parse_moeda(valor):
    """
    Converte uma string/valor monetário (pt-BR) para float.
    Exemplos aceitos:
      "R$ 1.234,56" -> 1234.56
      "1.234,56"    -> 1234.56
      "1234.56"     -> 1234.56
      1234.56       -> 1234.56
      None or ''    -> 0.0
    Em caso de erro, retorna 0.0
    """
    try:
        if valor is None or valor == '':
            return 0.0
        # já é número
        if isinstance(valor, (int, float)):
            return float(valor)
        s = str(valor).strip()
        # remover símbolo R$ e espaços
        s = s.replace('R$', '').replace('r$', '').strip()
        # tratar formatos com milhar e decimal no pt-BR: 1.234,56
        # se tem '.' e ',' -> remover pontos (milhares) e trocar ',' por '.'
        if '.' in s and ',' in s:
            s = s.replace('.', '').replace(',', '.')
        else:
            # se só tem ',' -> trocar por '.' ; se só tem '.' assume-se ponto decimal
            if ',' in s:
                s = s.replace(',', '.')
        # remover quaisquer caracteres não numéricos (exceto '-' e '.')
        s = re.sub(r'[^0-9\.-]', '', s)
        if s == '' or s == '-' or s == '.':
            return 0.0
        return float(s)
    except Exception:
        return 0.0
