"""
Model para Categorias de Despesas
Criado em: 2026-01-21
"""
from datetime import datetime
from . import db


class CategoriaDespesa(db.Model):
    """Categorias de Despesas"""
    
    __tablename__ = "categorias_despesas"
    
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    ativo = db.Column(db.Boolean, nullable=False, default=True)
    criado_em = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    
    # Relacionamento com subcategorias
    subcategorias = db.relationship('SubcategoriaDespesa', backref='categoria', lazy=True)
    
    def __repr__(self):
        return f"<CategoriaDespesa {self.id} - {self.nome}>"
