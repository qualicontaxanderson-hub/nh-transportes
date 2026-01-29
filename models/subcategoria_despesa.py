"""
Model para Subcategorias de Despesas
Criado em: 2026-01-21
"""
from datetime import datetime
from . import db


class SubcategoriaDespesa(db.Model):
    """Subcategorias de Despesas"""
    
    __tablename__ = "subcategorias_despesas"
    
    id = db.Column(db.Integer, primary_key=True)
    categoria_id = db.Column(db.Integer, db.ForeignKey('categorias_despesas.id'), nullable=False)
    nome = db.Column(db.String(100), nullable=False)
    ativo = db.Column(db.Boolean, nullable=False, default=True)
    criado_em = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    
    def __repr__(self):
        return f"<SubcategoriaDespesa {self.id} - {self.nome}>"
