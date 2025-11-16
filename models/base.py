import sys
import os

# Obter o caminho absoluto do diretório src
# models/base.py está em: /opt/render/project/src/models/base.py
# extensions.py está em: /opt/render/project/src/extensions.py
current_dir = os.path.dirname(os.path.abspath(__file__))  # /opt/render/project/src/models
src_dir = os.path.dirname(current_dir)  # /opt/render/project/src

# Adicionar src ao path se ainda não estiver
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

# Debug: imprimir o path (remover depois de funcionar)
print(f"DEBUG - Current dir: {current_dir}")
print(f"DEBUG - Src dir: {src_dir}")
print(f"DEBUG - sys.path: {sys.path[:3]}")

# Tentar importar extensions
try:
    from extensions import db
    print("DEBUG - extensions imported successfully!")
except ImportError as e:
    print(f"DEBUG - Failed to import extensions: {e}")
    # Tentar caminho alternativo
    import importlib.util
    spec = importlib.util.spec_from_file_location("extensions", os.path.join(src_dir, "extensions.py"))
    if spec and spec.loader:
        extensions = importlib.util.module_from_spec(spec)
        sys.modules['extensions'] = extensions
        spec.loader.exec_module(extensions)
        db = extensions.db
        print("DEBUG - extensions imported via importlib!")
    else:
        raise ImportError(f"Cannot find extensions.py in {src_dir}")

from datetime import datetime

# Exportar para outros módulos usarem
__all__ = ['db', 'datetime']
