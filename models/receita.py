from datetime import datetime
from . import db


class Receita(db.Model):
    """Cadastro de tipos de receitas vinculadas a clientes"""
    
    __tablename__ = "receitas"
    
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(200), nullable=False)
    cliente_id = db.Column(db.Integer, db.ForeignKey('clientes.id'), nullable=False)
    ativo = db.Column(db.Boolean, nullable=False, default=True)
    criado_em = db.Column(db.DateTime, nullable=True, default=datetime.utcnow)
    
    # Relacionamento com cliente
    cliente = db.relationship('Cliente', backref='receitas', lazy=True)
    
    def __repr__(self) -> str:
        return f"<Receita {self.id} - {self.nome}>"
