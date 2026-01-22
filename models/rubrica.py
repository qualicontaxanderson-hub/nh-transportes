from models import db
import datetime

class Rubrica(db.Model):
    __tablename__ = 'rubricas'
    
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    descricao = db.Column(db.String(255), nullable=True)
    tipo = db.Column(db.Enum('SALARIO', 'BENEFICIO', 'DESCONTO', 'IMPOSTO', 'ADIANTAMENTO', 'OUTRO'), nullable=False)
    percentualouvalorfixo = db.Column('percentualouvalorfixo', db.Enum('PERCENTUAL', 'VALOR_FIXO'), default='VALOR_FIXO')
    ativo = db.Column(db.Boolean, default=True, nullable=False)
    ordem = db.Column(db.Integer, default=1)
    criadoem = db.Column('criadoem', db.DateTime, default=datetime.datetime.utcnow)
    
    def __repr__(self):
        return f'<Rubrica {self.nome}>'
