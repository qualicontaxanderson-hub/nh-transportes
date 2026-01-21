"""
Model para Lançamentos de Caixa (Fechamento de Caixa)
Criado em: 2026-01-21
"""
from datetime import datetime
from . import db


class LancamentoCaixa(db.Model):
    """Lançamentos de Fechamento de Caixa"""
    
    __tablename__ = "lancamentos_caixa"
    
    id = db.Column(db.Integer, primary_key=True)
    data = db.Column(db.Date, nullable=False)
    data_lancamento = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=True)
    observacao = db.Column(db.Text, nullable=True)
    total_receitas = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    total_comprovacao = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    diferenca = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    status = db.Column(db.Enum('ABERTO', 'FECHADO'), nullable=False, default='ABERTO')
    criado_em = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    atualizado_em = db.Column(db.DateTime, nullable=True, onupdate=datetime.utcnow)
    
    # Relacionamentos
    receitas = db.relationship('LancamentoCaixaReceita', backref='lancamento_caixa', lazy=True, cascade='all, delete-orphan')
    comprovacoes = db.relationship('LancamentoCaixaComprovacao', backref='lancamento_caixa', lazy=True, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f"<LancamentoCaixa {self.id} - {self.data}>"


class LancamentoCaixaReceita(db.Model):
    """Receitas e Entradas do Caixa (Lado Esquerdo)"""
    
    __tablename__ = "lancamentos_caixa_receitas"
    
    id = db.Column(db.Integer, primary_key=True)
    lancamento_caixa_id = db.Column(db.Integer, db.ForeignKey('lancamentos_caixa.id'), nullable=False)
    tipo = db.Column(db.Enum('VENDAS_POSTO', 'LUBRIFICANTES', 'ARLA', 'TROCO_PIX', 'EMPRESTIMOS', 'OUTROS'), nullable=False)
    descricao = db.Column(db.String(200), nullable=True)
    valor = db.Column(db.Numeric(10, 2), nullable=False)
    criado_em = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    
    def __repr__(self):
        return f"<LancamentoCaixaReceita {self.id} - {self.tipo} - R$ {self.valor}>"


class LancamentoCaixaComprovacao(db.Model):
    """Comprovações do Caixa (Lado Direito)"""
    
    __tablename__ = "lancamentos_caixa_comprovacao"
    
    id = db.Column(db.Integer, primary_key=True)
    lancamento_caixa_id = db.Column(db.Integer, db.ForeignKey('lancamentos_caixa.id'), nullable=False)
    forma_pagamento_id = db.Column(db.Integer, db.ForeignKey('formas_pagamento_caixa.id'), nullable=True)
    bandeira_cartao_id = db.Column(db.Integer, db.ForeignKey('bandeiras_cartao.id'), nullable=True)
    descricao = db.Column(db.String(200), nullable=True)
    valor = db.Column(db.Numeric(10, 2), nullable=False)
    criado_em = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    
    # Relacionamentos
    forma_pagamento = db.relationship('FormaPagamentoCaixa', backref='comprovacoes', lazy=True)
    
    def __repr__(self):
        return f"<LancamentoCaixaComprovacao {self.id} - R$ {self.valor}>"
