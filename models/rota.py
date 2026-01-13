from models import db
import datetime

class Rota(db.Model):
    __tablename__ = 'rotas'
    
    id = db.Column(db.Integer, primary_key=True)
    origem_id = db.Column(db.Integer, db.ForeignKey('origens.id'), nullable=False)
    destino_id = db.Column(db.Integer, db.ForeignKey('destinos.id'), nullable=False)
    valor_por_litro = db.Column(db.Float, nullable=False)
    ativo = db.Column(db.Boolean, default=True)
    criado_em = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    
    # Relacionamentos comentados temporariamente - modelos Origem/Destino não existem
    # origem = db.relationship('Origem', backref='rotas_origem')
    # destino = db.relationship('Destino', backref='rotas_destino')
    
    def __repr__(self):
        # Modificado para usar IDs ao invés dos objetos relacionados
        return f'<Rota {self.origem_id} -> {self.destino_id}: R$ {self.valor_por_litro}/L>'
