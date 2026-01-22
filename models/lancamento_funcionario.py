from models import db
import datetime

class LancamentoFuncionario(db.Model):
    __tablename__ = 'lancamentosfuncionarios_v2'
    
    id = db.Column(db.Integer, primary_key=True)
    clienteid = db.Column('clienteid', db.Integer, nullable=False)
    funcionarioid = db.Column('funcionarioid', db.Integer, db.ForeignKey('funcionarios.id'), nullable=False)
    mes = db.Column(db.String(7), nullable=False)  # Format: MMM/YYYY ex: JAN/2026
    rubricaid = db.Column('rubricaid', db.Integer, db.ForeignKey('rubricas.id'), nullable=False)
    valor = db.Column(db.Numeric(12, 2), nullable=False)
    percentual = db.Column(db.Numeric(5, 2), nullable=True)
    referencia = db.Column(db.String(100), nullable=True)
    observacao = db.Column(db.String(255), nullable=True)
    caminhaoid = db.Column('caminhaoid', db.Integer, db.ForeignKey('veiculos.id'), nullable=True)
    statuslancamento = db.Column('statuslancamento', db.Enum('PENDENTE', 'PROCESSADO', 'PAGO', 'CANCELADO'), default='PENDENTE')
    datavencimento = db.Column('datavencimento', db.Date, nullable=True)
    datapagamento = db.Column('datapagamento', db.Date, nullable=True)
    criadoem = db.Column('criadoem', db.DateTime, default=datetime.datetime.utcnow)
    atualizadoem = db.Column('atualizadoem', db.DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    
    # Relationships
    funcionario = db.relationship('Funcionario', backref='lancamentos')
    rubrica = db.relationship('Rubrica', backref='lancamentos')
    
    def __repr__(self):
        return f'<LancamentoFuncionario {self.funcionarioid} - {self.mes}>'
