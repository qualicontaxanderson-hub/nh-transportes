from datetime import datetime
from . import db


class Cliente(db.Model):
    __tablename__ = "clientes"

    id = db.Column(db.Integer, primary_key=True)
    razao_social = db.Column(db.String(200), nullable=False)
    nome_fantasia = db.Column(db.String(200), nullable=True)
    contato = db.Column(db.String(100), nullable=True)
    telefone = db.Column(db.String(15), nullable=True)
    cnpj = db.Column(db.String(18), nullable=True)
    ie = db.Column(db.String(20), nullable=True)
    email = db.Column(db.String(100), nullable=True)
    endereco = db.Column(db.String(200), nullable=True)
    numero = db.Column(db.String(20), nullable=True)
    complemento = db.Column(db.String(100), nullable=True)
    bairro = db.Column(db.String(100), nullable=True)
    municipio = db.Column(db.String(100), nullable=True)
    destino_id = db.Column(db.Integer, nullable=True)
    uf = db.Column(db.String(2), nullable=True)
    cep = db.Column(db.String(10), nullable=True)
    data_registro = db.Column(db.DateTime, nullable=True, default=datetime.utcnow)
    paga_comissao = db.Column(db.Boolean, nullable=True, default=True)
    percentual_cte = db.Column(db.Float, nullable=True, default=0.0)
    cte_integral = db.Column(db.Boolean, nullable=True, default=False)

    def __repr__(self) -> str:
        return f"<Cliente {self.id} - {self.razao_social}>"
