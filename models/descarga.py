"""
Model para controle de descargas de combustível
Criado em: 2026-01-21
"""
from datetime import datetime
from . import db


class Descarga(db.Model):
    """Controle de Descargas de Combustível"""
    
    __tablename__ = "descargas"
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    frete_id = db.Column(db.BigInteger, nullable=False, index=True)
    data_carregamento = db.Column(db.Date, nullable=False)
    data_descarga = db.Column(db.Date, nullable=False, index=True)
    volume_total = db.Column(db.Numeric(10, 2), nullable=False)
    
    estoque_sistema_antes = db.Column(db.Numeric(10, 2), nullable=True)
    estoque_regua_antes = db.Column(db.Numeric(10, 2), nullable=True)
    estoque_sistema_depois = db.Column(db.Numeric(10, 2), nullable=True)
    estoque_regua_depois = db.Column(db.Numeric(10, 2), nullable=True)
    
    abastecimento_durante_descarga = db.Column(db.Numeric(10, 2), nullable=True, default=0.00)
    temperatura = db.Column(db.Numeric(5, 2), nullable=True)
    densidade = db.Column(db.Numeric(5, 4), nullable=True)
    
    diferenca_sistema = db.Column(db.Numeric(10, 2), nullable=True)
    diferenca_regua = db.Column(db.Numeric(10, 2), nullable=True)
    
    status = db.Column(db.String(20), nullable=False, default='pendente', index=True)
    volume_descarregado = db.Column(db.Numeric(10, 2), nullable=False, default=0.00)
    
    observacoes = db.Column(db.Text, nullable=True)
    
    criado_em = db.Column(db.DateTime, nullable=True, default=datetime.utcnow)
    atualizado_em = db.Column(db.DateTime, nullable=True, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationship with etapas
    etapas = db.relationship('DescargaEtapa', backref='descarga', lazy=True, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f"<Descarga {self.id} - Frete {self.frete_id}>"
    
    def calcular_diferencas(self):
        """
        Calcula as diferenças entre estoque antes e depois
        Considera abastecimento durante a descarga
        """
        if self.estoque_sistema_antes is not None and self.estoque_sistema_depois is not None:
            # Diferença = (Depois - Antes) - Volume Descarregado + Abastecimento
            abastecimento = self.abastecimento_durante_descarga or 0
            self.diferenca_sistema = (
                self.estoque_sistema_depois - 
                self.estoque_sistema_antes - 
                self.volume_descarregado + 
                abastecimento
            )
        
        if self.estoque_regua_antes is not None and self.estoque_regua_depois is not None:
            abastecimento = self.abastecimento_durante_descarga or 0
            self.diferenca_regua = (
                self.estoque_regua_depois - 
                self.estoque_regua_antes - 
                self.volume_descarregado + 
                abastecimento
            )
    
    def atualizar_volume_descarregado(self):
        """
        Atualiza o volume descarregado baseado nas etapas
        """
        if self.etapas:
            self.volume_descarregado = sum(
                etapa.volume_etapa or 0 for etapa in self.etapas
            )
        else:
            self.volume_descarregado = self.volume_total
    
    def atualizar_status(self):
        """
        Atualiza o status baseado no volume descarregado
        """
        if self.volume_descarregado >= self.volume_total:
            self.status = 'completo'
        elif self.volume_descarregado > 0:
            self.status = 'em_andamento'
        else:
            self.status = 'pendente'
