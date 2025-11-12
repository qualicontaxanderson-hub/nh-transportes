**Caminho no GitHub:** `utils/formatadores.py`

```python
import re

def formatar_cnpj(cnpj):
    if not cnpj:
        return None
    cnpj_numeros = re.sub(r'\D', '', str(cnpj))
    if len(cnpj_numeros) != 14:
        return cnpj
    return f"{cnpj_numeros[0:2]}.{cnpj_numeros[2:5]}.{cnpj_numeros[5:8]}/{cnpj_numeros[8:12]}-{cnpj_numeros[12:14]}"

def formatar_ie_goias(ie):
    if not ie:
        return None
    ie_numeros = re.sub(r'\D', '', str(ie))
    if len(ie_numeros) != 9:
        return ie
    return f"{ie_numeros[0:2]}.{ie_numeros[2:5]}.{ie_numeros[5:8]}-{ie_numeros[8:9]}"

def formatar_telefone(telefone):
    if not telefone:
        return None
    tel_numeros = re.sub(r'\D', '', str(telefone))
    if len(tel_numeros) == 11:
        return f"({tel_numeros[0:2]}) {tel_numeros[2:7]}-{tel_numeros[7:11]}"
    elif len(tel_numeros) == 10:
        return f"({tel_numeros[0:2]}) {tel_numeros[2:6]}-{tel_numeros[6:10]}"
    return telefone

def formatar_cep(cep):
    if not cep:
        return None
    cep_numeros = re.sub(r'\D', '', str(cep))
    if len(cep_numeros) != 8:
        return cep
    return f"{cep_numeros[0:5]}-{cep_numeros[5:8]}"

def formatar_moeda(valor):
    if valor is None:
        return "R$ 0,00"
    return f"R$ {float(valor):,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
```

---
