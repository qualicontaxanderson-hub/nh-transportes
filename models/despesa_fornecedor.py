"""
Model para Fornecedores de Despesas
Fornecedores vinculados a categorias específicas de despesas
"""

class DespesaFornecedor:
    """Model para Fornecedor de Despesa"""
    
    def __init__(self, id=None, nome=None, categoria_id=None, ativo=1, criado_em=None):
        self.id = id
        self.nome = nome
        self.categoria_id = categoria_id
        self.ativo = ativo
        self.criado_em = criado_em
    
    def __repr__(self):
        return f"<DespesaFornecedor {self.id}: {self.nome} (Categoria: {self.categoria_id})>"
