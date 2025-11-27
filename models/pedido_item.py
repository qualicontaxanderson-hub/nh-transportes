from datetime import datetime
from . import db


class PedidoItem(db.Model):
    __tablename__ = "pedidos_itens"

    id = db.Column(db.Integer, primary_key=True)
    pedido_id = db.Column(db.Integer, nullable=False)
    cliente_id = db.Column(db.Integer, nullable=False)
    produto_id = db.Column(db.Integer, nullable=False)
    fornecedor_id = db.Column(db.Integer, nullable=False)
    origem_id = db.Column(db.Integer, nullable=False)
    base_id = db.Column(db.Integer, nullable=True)  # nova coluna no banco

    quantidade = db.Column(db.Numeric(10, 2), nullable=False)
    quantidade_id = db.Column(db.Integer, nullable=True)
    tipo_quantidade = db.Column(db.String(20), nullable=True, default="metros")
    preco_unitario = db.Column(db.Numeric(10, 3), nullable=False)
    total_nf = db.Column(db.Numeric(12, 2), nullable=False)
    created_at = db.Column(db.DateTime, nullable=True, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<PedidoItem {self.id} - Pedido {self.pedido_id}>"
