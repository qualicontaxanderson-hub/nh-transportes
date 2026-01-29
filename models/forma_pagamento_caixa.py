"""
Model para Formas de Pagamento do Caixa
Criado em: 2026-01-21
"""
from datetime import datetime
from . import db


class FormaPagamentoCaixa(db.Model):
    """Formas de Pagamento para Fechamento de Caixa"""
    
    __tablename__ = "formas_pagamento_caixa"
    
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    tipo = db.Column(db.Enum('DEPOSITO_ESPECIE', 'DEPOSITO_CHEQUE_VISTA', 'DEPOSITO_CHEQUE_PRAZO', 
                              'PIX', 'PRAZO', 'CARTAO', 'RETIRADA_PAGAMENTO'), nullable=False)
    ativo = db.Column(db.Boolean, nullable=False, default=True)
    criado_em = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    
    def __repr__(self):
        return f"<FormaPagamentoCaixa {self.id} - {self.nome}>"
