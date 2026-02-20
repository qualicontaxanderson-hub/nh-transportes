import re

class OFXParser:
    def __init__(self, ofx_content):
        self.ofx_content = ofx_content

    def extract_transactions(self):
        transactions = []
        # Use regex to find CNPJ and CPF
        cnpj_pattern = re.compile(r'\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b')
        cpf_pattern = re.compile(r'\b\d{3}\.\d{3}\.\d{3}-\d{2}\b')

        # Sample regex to demonstrate purposes; adjust as necessary for OFX structure
        # Extract transactions based on some criteria; here is a placeholder
        transactions_data = re.findall(r'<transaction>(.*?)</transaction>', self.ofx_content, re.DOTALL)
        for transaction in transactions_data:
            cnpj = cnpj_pattern.search(transaction)
            cpf = cpf_pattern.search(transaction)
            if cnpj or cpf:
                transactions.append({
                    'transaction': transaction.strip(),
                    'cnpj': cnpj.group() if cnpj else None,
                    'cpf': cpf.group() if cpf else None
                })

        # Deduplicate transactions by using a hash
        seen = set()
        unique_transactions = []
        for trans in transactions:
            trans_hash = hash(trans['transaction'])
            if trans_hash not in seen:
                seen.add(trans_hash)
                unique_transactions.append(trans)

        return unique_transactions
