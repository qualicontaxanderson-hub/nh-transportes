"""
Model para Descargas (Controle de Descargas)
Criado em: 2026-01-21
"""
from datetime import datetime
from . import db


class Descarga(db.Model):
    """Controle de Descargas de Combustível"""
    
    __tablename__ = "descargas"
    
    id = db.Column(db.Integer, primary_key=True)
    frete_id = db.Column(db.Integer, db.ForeignKey('fretes.id'), nullable=False)
    
    data_carregamento = db.Column(db.Date, nullable=False)
    data_descarga = db.Column(db.Date, nullable=False)
    volume_total = db.Column(db.Numeric(10, 2), nullable=False)
    
    # Medidas antes da descarga
    estoque_sistema_antes = db.Column(db.Numeric(10, 2), nullable=True)
    estoque_regua_antes = db.Column(db.Numeric(10, 2), nullable=True)
    
    # Medidas depois da descarga
    estoque_sistema_depois = db.Column(db.Numeric(10, 2), nullable=True)
    estoque_regua_depois = db.Column(db.Numeric(10, 2), nullable=True)
    
    # Abastecimento durante descarga
    abastecimento_durante_descarga = db.Column(db.Numeric(10, 2), nullable=True, default=0)
    
    # Medidas adicionais
    temperatura = db.Column(db.Numeric(5, 2), nullable=True)
    densidade = db.Column(db.Numeric(5, 4), nullable=True)
    
    # Diferenças calculadas
    diferenca_sistema = db.Column(db.Numeric(10, 2), nullable=True)
    diferenca_regua = db.Column(db.Numeric(10, 2), nullable=True)
    
    # Status para descargas em etapas
    status = db.Column(db.String(20), nullable=False, default='pendente')  # pendente, parcial, concluido
    volume_descarregado = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    
    observacoes = db.Column(db.Text, nullable=True)
    
    criado_em = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    atualizado_em = db.Column(db.DateTime, nullable=True, onupdate=datetime.utcnow)
    
    # Relationships
    frete = db.relationship('Frete', backref='descargas', lazy=True)
    etapas = db.relationship('DescargaEtapa', backref='descarga', lazy=True, cascade='all, delete-orphan')
    
    def calcular_diferencas(self):
        """Calcula as diferenças entre estoque antes e depois"""
        if self.estoque_sistema_antes is not None and self.estoque_sistema_depois is not None:
            # Diferença = (Estoque Depois - Estoque Antes) - Volume + Abastecimento
            abastecimento = self.abastecimento_durante_descarga or 0
            self.diferenca_sistema = (
                self.estoque_sistema_depois - self.estoque_sistema_antes - 
                self.volume_descarregado + abastecimento
            )
        
        if self.estoque_regua_antes is not None and self.estoque_regua_depois is not None:
            abastecimento = self.abastecimento_durante_descarga or 0
            self.diferenca_regua = (
                self.estoque_regua_depois - self.estoque_regua_antes - 
                self.volume_descarregado + abastecimento
            )
    
    def __repr__(self):
        return f"<Descarga {self.id} - Frete {self.frete_id}>"
