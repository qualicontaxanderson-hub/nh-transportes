**Caminho no GitHub:** `models/usuario.py`

```python
from flask_login import UserMixin
from werkzeug.security import check_password_hash
from utils.db import get_db_connection

class Usuario(UserMixin):
    def __init__(self, id, username, nome_completo, nivel):
        self.id = id
        self.username = username
        self.nome_completo = nome_completo
        self.nivel = nivel
    
    @staticmethod
    def get_by_id(user_id):
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT id, username, nome_completo, nivel 
            FROM usuarios WHERE id = %s AND ativo = TRUE
        """, (user_id,))
        user_data = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if user_data:
            return Usuario(user_data['id'], user_data['username'],
                          user_data['nome_completo'], user_data['nivel'])
        return None
    
    @staticmethod
    def authenticate(username, password):
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT id, username, password_hash, nome_completo, nivel
            FROM usuarios WHERE username = %s AND ativo = TRUE
        """, (username,))
        user_data = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if user_data and check_password_hash(user_data['password_hash'], password):
            return Usuario(user_data['id'], user_data['username'],
                          user_data['nome_completo'], user_data['nivel'])
        return None
    
    def is_admin(self):
        return self.nivel == 'admin'
```

---
