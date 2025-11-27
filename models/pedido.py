from datetime import datetime
from . import db


class Pedido(db.Model):
    __tablename__ = "pedidos"

    id = db.Column(db.Integer, primary_key=True)
    numero = db.Column(db.String(20), nullable=False, unique=True)
    data_pedido = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), nullable=True, default="Pendente")
    observacoes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=True, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=True, default=datetime.utcnow)

    motorista_id = db.Column(db.Integer, nullable=True)
    forma_pagamento_fornecedor = db.Column(db.String(20), nullable=True)

    def __repr__(self) -> str:
        return f"<Pedido {self.id} - {self.numero}>"
