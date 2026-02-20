"""
Model for Lançamentos de Despesas (Expense Postings)
"""
from datetime import datetime


class LancamentoDespesa:
    """
    Representa um lançamento de despesa no sistema
    """
    
    def __init__(self, id=None, data=None, cliente_id=None, titulo_id=None, categoria_id=None, 
                 subcategoria_id=None, valor=None, fornecedor=None, observacao=None,
                 criado_em=None, atualizado_em=None):
        self.id = id
        self.data = data
        self.cliente_id = cliente_id
        self.titulo_id = titulo_id
        self.categoria_id = categoria_id
        self.subcategoria_id = subcategoria_id
        self.valor = valor
        self.fornecedor = fornecedor
        self.observacao = observacao
        self.criado_em = criado_em
        self.atualizado_em = atualizado_em
    
    def __repr__(self):
        return f"<LancamentoDespesa {self.id} - {self.data} - R$ {self.valor}>"
