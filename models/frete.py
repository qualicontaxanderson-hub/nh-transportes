from models.base import db, datetime


class Frete(db.Model):
    __tablename__ = 'fretes'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # Foreign Keys
    clientes_id = db.Column(db.Integer, db.ForeignKey('clientes.id'), nullable=False)
    fornecedores_id = db.Column(db.Integer, db.ForeignKey('fornecedores.id'), nullable=False)
    motoristas_id = db.Column(db.Integer, db.ForeignKey('motoristas.id'), nullable=False)
    veiculos_id = db.Column(db.Integer, db.ForeignKey('veiculos.id'), nullable=False)
    quantidade_id = db.Column(db.Integer, db.ForeignKey('quantidades.id'), nullable=False)
    origem_id = db.Column(db.Integer, db.ForeignKey('origens.id'), nullable=False)
    destino_id = db.Column(db.Integer, db.ForeignKey('destinos.id'), nullable=False)
    
    # Campos de valores
    preco_produto_unitario = db.Column(db.Numeric(10, 2), nullable=False)
    total_nf_compra = db.Column(db.Numeric(10, 2), nullable=False)
    preco_por_litro = db.Column(db.Numeric(10, 2), nullable=False)
    valor_total_frete = db.Column(db.Numeric(10, 2), nullable=False)
    comissao_motorista = db.Column(db.Numeric(10, 2), default=0)
    valor_cte = db.Column(db.Numeric(10, 2), nullable=False)
    comissao_cte = db.Column(db.Numeric(10, 2), nullable=False)
    lucro = db.Column(db.Numeric(10, 2), nullable=False)
    
    # Campos de controle
    data_frete = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), default='pendente')
    observacoes = db.Column(db.Text)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f'<Frete {self.id} - {self.data_frete}>'
