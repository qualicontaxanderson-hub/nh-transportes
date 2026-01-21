"""
Model para etapas de descarga (descargas parciais)
Criado em: 2026-01-21
"""
from datetime import datetime
from . import db


class DescargaEtapa(db.Model):
    """Etapas de Descarga de Combustível (para descargas parciais)"""
    
    __tablename__ = "descarga_etapas"
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    descarga_id = db.Column(db.Integer, db.ForeignKey('descargas.id'), nullable=False, index=True)
    data_etapa = db.Column(db.Date, nullable=False, index=True)
    volume_etapa = db.Column(db.Numeric(10, 2), nullable=False)
    
    estoque_sistema_antes = db.Column(db.Numeric(10, 2), nullable=True)
    estoque_regua_antes = db.Column(db.Numeric(10, 2), nullable=True)
    estoque_sistema_depois = db.Column(db.Numeric(10, 2), nullable=True)
    estoque_regua_depois = db.Column(db.Numeric(10, 2), nullable=True)
    
    abastecimento_durante_etapa = db.Column(db.Numeric(10, 2), nullable=True, default=0.00)
    
    diferenca_sistema = db.Column(db.Numeric(10, 2), nullable=True)
    diferenca_regua = db.Column(db.Numeric(10, 2), nullable=True)
    
    observacoes = db.Column(db.Text, nullable=True)
    
    criado_em = db.Column(db.DateTime, nullable=True, default=datetime.utcnow)
    
    def __repr__(self):
        return f"<DescargaEtapa {self.id} - Descarga {self.descarga_id}>"
    
    def calcular_diferencas(self):
        """
        Calcula as diferenças entre estoque antes e depois para esta etapa
        Considera abastecimento durante a etapa
        """
        if self.estoque_sistema_antes is not None and self.estoque_sistema_depois is not None:
            abastecimento = self.abastecimento_durante_etapa or 0
            self.diferenca_sistema = (
                self.estoque_sistema_depois - 
                self.estoque_sistema_antes - 
                self.volume_etapa + 
                abastecimento
            )
        
        if self.estoque_regua_antes is not None and self.estoque_regua_depois is not None:
            abastecimento = self.abastecimento_durante_etapa or 0
            self.diferenca_regua = (
                self.estoque_regua_depois - 
                self.estoque_regua_antes - 
                self.volume_etapa + 
                abastecimento
            )
