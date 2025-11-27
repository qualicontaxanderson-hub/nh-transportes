from datetime import datetime
from . import db


class Frete(db.Model):
    __tablename__ = "fretes"

    id = db.Column(db.Integer, primary_key=True)

    clientes_id = db.Column(db.Integer, nullable=False)
    fornecedores_id = db.Column(db.Integer, nullable=False)
    motoristas_id = db.Column(db.Integer, nullable=False)
    veiculos_id = db.Column(db.Integer, nullable=False)

    quantidade_id = db.Column(db.Integer, nullable=True)
    quantidade_manual = db.Column(db.Numeric(10, 2), nullable=True)

    origem_id = db.Column(db.Integer, nullable=True)
    destino_id = db.Column(db.Integer, nullable=False)

    preco_produto_unitario = db.Column(db.Numeric(10, 2), nullable=False)
    total_nf_compra = db.Column(db.Numeric(10, 2), nullable=False)
    preco_por_litro = db.Column(db.Numeric(10, 2), nullable=False)
    valor_total_frete = db.Column(db.Numeric(10, 2), nullable=False)

    comissao_motorista = db.Column(db.Numeric(10, 2), nullable=True, default=0)
    valor_cte = db.Column(db.Numeric(10, 2), nullable=False)
    comissao_cte = db.Column(db.Numeric(10, 2), nullable=False)
    lucro = db.Column(db.Numeric(10, 2), nullable=False)

    data_frete = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), nullable=True, default="pendente")
    observacoes = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, nullable=True, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=True, default=datetime.utcnow)

    produto_id = db.Column(db.Integer, nullable=True)

    def __repr__(self) -> str:
        return f"<Frete {self.id} - Cliente {self.clientes_id}>"
