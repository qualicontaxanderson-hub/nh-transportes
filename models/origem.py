import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extensions import db
from datetime import datetime


class Origem(db.Model):
    __tablename__ = 'origens'
    
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    cidade = db.Column(db.String(100))
    estado = db.Column(db.String(2), default='GO')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Origem {self.nome}>'
