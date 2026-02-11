import os
from dotenv import load_dotenv

# Carrega variáveis de ambiente do arquivo .env (se existir)
load_dotenv()

class Config:
    # Configurações do Banco de Dados
    # Usa variáveis de ambiente se disponíveis, caso contrário usa valores padrão
    DB_HOST = os.environ.get('DB_HOST', 'centerbeam.proxy.rlwy.net')
    DB_PORT = int(os.environ.get('DB_PORT', 56026))
    DB_USER = os.environ.get('DB_USER', 'root')
    DB_PASSWORD = os.environ.get('DB_PASSWORD', 'CYTzzRYLVmEJGDexxXpgepWgpvebdSrV')
    DB_NAME = os.environ.get('DB_NAME', 'railway')
    
    # URI do Banco de Dados
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or f'mysql+mysqlconnector://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}'
    
    # Chave Secreta - usa variável de ambiente ou valor padrão
    SECRET_KEY = os.environ.get('SECRET_KEY', 'nh-transportes-2025-secret')
    
    # Configurações da Aplicação
    APP_NAME = "NH Transportes"
    DEBUG = os.environ.get('FLASK_DEBUG', '0') == '1'
    ITEMS_PER_PAGE = 20
