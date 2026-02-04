import os
from dotenv import load_dotenv

# Carrega variáveis de ambiente do arquivo .env
load_dotenv()

class Config:
    # Configurações do Banco de Dados - SEMPRE use variáveis de ambiente
    DB_HOST = os.environ.get('DB_HOST', 'centerbeam.proxy.rlwy.net')
    DB_PORT = int(os.environ.get('DB_PORT', 56026))
    DB_USER = os.environ.get('DB_USER', 'root')
    DB_PASSWORD = os.environ.get('DB_PASSWORD')  # OBRIGATÓRIO via .env
    DB_NAME = os.environ.get('DB_NAME', 'railway')
    
    # URI do Banco de Dados
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or f'mysql+mysqlconnector://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}'
    
    # Chave Secreta - SEMPRE use variável de ambiente
    SECRET_KEY = os.environ.get('SECRET_KEY')  # OBRIGATÓRIO via .env
    if not SECRET_KEY:
        raise ValueError("SECRET_KEY must be set in environment variables or .env file")
    
    # Configurações da Aplicação
    APP_NAME = "NH Transportes"
    DEBUG = os.environ.get('FLASK_DEBUG', '0') == '1'
    ITEMS_PER_PAGE = 20
