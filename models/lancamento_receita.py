from datetime import datetime
from . import db


class LancamentoReceita(db.Model):
    """Lançamentos de receitas (postagens/entradas)"""
    
    __tablename__ = "lancamentos_receitas"
    
    id = db.Column(db.Integer, primary_key=True)
    data = db.Column(db.Date, nullable=False)
    receita_id = db.Column(db.Integer, db.ForeignKey('receitas.id'), nullable=False)
    valor = db.Column(db.Numeric(10, 2), nullable=False)
    observacao = db.Column(db.Text, nullable=True)
    criado_em = db.Column(db.DateTime, nullable=True, default=datetime.utcnow)
    
    # Relacionamento com receita
    receita = db.relationship('Receita', backref='lancamentos', lazy=True)
    
    def __repr__(self) -> str:
        return f"<LancamentoReceita {self.id} - {self.data} - R$ {self.valor}>"
