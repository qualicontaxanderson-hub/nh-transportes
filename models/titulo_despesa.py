"""
Model para Títulos de Despesas (Main Expense Categories)
Criado em: 2026-02-12
"""
from datetime import datetime
from . import db


class TituloDespesa(db.Model):
    """Títulos principais de Despesas (ex: DESPESAS OPERACIONAIS, IMPOSTOS, etc)"""
    
    __tablename__ = "titulos_despesas"
    
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    descricao = db.Column(db.Text, nullable=True)
    ativo = db.Column(db.Boolean, nullable=False, default=True)
    ordem = db.Column(db.Integer, nullable=False, default=0)
    criado_em = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    
    # Relacionamento com categorias
    categorias = db.relationship('CategoriaDespesa', backref='titulo', lazy=True, order_by='CategoriaDespesa.ordem')
    
    def __repr__(self):
        return f"<TituloDespesa {self.id} - {self.nome}>"
