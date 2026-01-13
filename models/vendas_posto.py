"""
Model para vendas do posto de gasolina
Criado em: 2025-01-13
"""
from datetime import datetime
from . import db


class VendasPosto(db.Model):
    """Vendas do Posto de Gasolina"""
    
    __tablename__ = "vendas_posto"
    
    id = db.Column(db.Integer, primary_key=True)
    data_movimento = db.Column(db.Date, nullable=False, default=datetime.utcnow)
    
    cliente_id = db.Column(db.Integer, db.ForeignKey('clientes.id'), nullable=True)
    produto_id = db.Column(db.Integer, db.ForeignKey('produto.id'), nullable=False)
    vendedor_id = db.Column(db.Integer, nullable=True)
    
    quantidade_litros = db.Column(db.Numeric(10, 3), nullable=False, default=0)
    preco_medio = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    valor_total = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    
    criado_em = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    atualizado_em = db.Column(db.DateTime, nullable=True, onupdate=datetime.utcnow)
    
    cliente = db.relationship('Cliente', backref='vendas_posto', lazy=True)
    produto = db.relationship('Produto', backref='vendas_posto', lazy=True)
    
    def __repr__(self):
        return f"<VendasPosto {self.id} - {self.data_movimento}>"
