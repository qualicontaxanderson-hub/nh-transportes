from models import db
import datetime

class LancamentoFuncionario(db.Model):
    __tablename__ = 'lancamentos_funcionarios_v2'
    
    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, nullable=False)
    funcionario_id = db.Column(db.Integer, db.ForeignKey('funcionarios.id'), nullable=False)
    mes = db.Column(db.String(7), nullable=False)  # Format: MMM/YYYY ex: JAN/2026
    rubrica_id = db.Column(db.Integer, db.ForeignKey('rubricas.id'), nullable=False)
    valor = db.Column(db.Numeric(12, 2), nullable=False)
    percentual = db.Column(db.Numeric(5, 2), nullable=True)
    referencia = db.Column(db.String(100), nullable=True)
    observacao = db.Column(db.String(255), nullable=True)
    caminhao_id = db.Column(db.Integer, db.ForeignKey('veiculos.id'), nullable=True)
    status_lancamento = db.Column(db.Enum('PENDENTE', 'PROCESSADO', 'PAGO', 'CANCELADO'), default='PENDENTE')
    data_vencimento = db.Column(db.Date, nullable=True)
    data_pagamento = db.Column(db.Date, nullable=True)
    criado_em = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    atualizado_em = db.Column(db.DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    
    # Relationships
    funcionario = db.relationship('Funcionario', backref='lancamentos')
    rubrica = db.relationship('Rubrica', backref='lancamentos')
    
    def __repr__(self):
        return f'<LancamentoFuncionario {self.funcionario_id} - {self.mes}>'
