from extensions import db
from datetime import datetime


class Veiculo(db.Model):
    __tablename__ = 'veiculos'
    
    id = db.Column(db.Integer, primary_key=True)
    placa = db.Column(db.String(10), unique=True, nullable=False)
    modelo = db.Column(db.String(50))
    marca = db.Column(db.String(50))
    ano = db.Column(db.Integer)
    capacidade = db.Column(db.Numeric(10, 2))
    tipo = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relacionamento com fretes
    fretes = db.relationship('Frete', backref='veiculo', lazy=True, foreign_keys='Frete.veiculos_id')
    
    def __repr__(self):
        return f'<Veiculo {self.placa}>'
