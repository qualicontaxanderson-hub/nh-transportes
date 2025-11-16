from extensions import db
from datetime import datetime


class Destino(db.Model):
    __tablename__ = 'destinos'
    
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    cidade = db.Column(db.String(100))
    estado = db.Column(db.String(2), default='GO')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relacionamento com fretes
    fretes = db.relationship('Frete', backref='destino', lazy=True)
    
    def __repr__(self):
        return f'<Destino {self.nome}>'
