"""
Model para vincular produtos que cada cliente pode vender
Usado para filtrar produtos disponíveis por posto
Criado em: 2026-01-13
"""
from datetime import datetime
from . import db


class ClienteProduto(db.Model):
    """Relacionamento Cliente x Produto (quais produtos o cliente vende)"""
    
    __tablename__ = "cliente_produtos"
    
    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey('clientes.id'), nullable=False)
    produto_id = db.Column(db.Integer, db.ForeignKey('produto.id'), nullable=False)
    ativo = db.Column(db.Boolean, default=True, nullable=False)
    criado_em = db.Column(db.DateTime, nullable=True, default=datetime.utcnow)
    
    def __repr__(self):
        return f"<ClienteProduto cliente_id={self.cliente_id} produto_id={self.produto_id}>"
    
    @staticmethod
    def produtos_do_cliente(cliente_id):
        """Retorna lista de produtos que o cliente pode vender"""
        from models.produto import Produto
        
        vinculos = ClienteProduto.query.filter_by(
            cliente_id=cliente_id,
            ativo=True
        ).all()
        
        produtos = []
        for v in vinculos:
            produto = Produto.query.get(v.produto_id)
            if produto:
                produtos.append(produto)
        
        return produtos
    
    @staticmethod
    def cliente_pode_vender(cliente_id, produto_id):
        """Verifica se o cliente está autorizado a vender determinado produto"""
        vinculo = ClienteProduto.query.filter_by(
            cliente_id=cliente_id,
            produto_id=produto_id,
            ativo=True
        ).first()
        return vinculo is not None
