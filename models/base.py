import sys
import os

# Adicionar o diretório src ao path
src_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if src_path not in sys.path:
    sys.path.insert(0, src_path)

# Agora importar extensions
from extensions import db
from datetime import datetime

# Exportar para outros módulos usarem
__all__ = ['db', 'datetime']
