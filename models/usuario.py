from flask_login import UserMixin
from utils.db import get_db_connection
from werkzeug.security import check_password_hash, generate_password_hash
import logging

logger = logging.getLogger(__name__)

class Usuario(UserMixin):
    def __init__(self, id, username, nome_completo, nivel, ativo=True, senha_hash=None, cliente_id=None):
        self.id = id
        self.username = username
        self.nome_completo = nome_completo
        self.nome = nome_completo  # Alias para compatibilidade
        self.nivel = nivel
        self.ativo = ativo
        self.senha_hash = senha_hash
        self.password = senha_hash  # Alias para compatibilidade
        self.email = ''  # Campo vazio para compatibilidade
        self.cliente_id = cliente_id  # Cliente/Posto vinculado (para PISTA)

    @staticmethod
    def get_by_id(user_id):
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM usuarios WHERE id = %s AND ativo = TRUE", (user_id,))
        user_data = cursor.fetchone()
        cursor.close()
        conn.close()
        if user_data:
            return Usuario(
                id=user_data['id'],
                username=user_data['username'],
                nome_completo=user_data['nome_completo'],
                nivel=user_data['nivel'],
                ativo=user_data['ativo'],
                senha_hash=user_data['password_hash'],
                cliente_id=user_data.get('cliente_id')  # Incluir cliente_id
            )
        return None

    @staticmethod
    def get_by_username(username):
        """Método adicionado para compatibilidade com app.py"""
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM usuarios WHERE username = %s AND ativo = TRUE", (username,))
        user_data = cursor.fetchone()
        cursor.close()
        conn.close()
        if user_data:
            return Usuario(
                id=user_data['id'],
                username=user_data['username'],
                nome_completo=user_data['nome_completo'],
                nivel=user_data['nivel'],
                ativo=user_data['ativo'],
                senha_hash=user_data['password_hash'],
                cliente_id=user_data.get('cliente_id')  # Incluir cliente_id
            )
        return None

    @staticmethod
    def authenticate(username, password):
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM usuarios WHERE username = %s AND ativo = TRUE", (username,))
        user_data = cursor.fetchone()
        cursor.close()
        conn.close()
        if user_data and check_password_hash(user_data['password_hash'], password):
            return Usuario(
                id=user_data['id'],
                username=user_data['username'],
                nome_completo=user_data['nome_completo'],
                nivel=user_data['nivel'],
                ativo=user_data['ativo'],
                senha_hash=user_data['password_hash'],
                cliente_id=user_data.get('cliente_id')  # Incluir cliente_id
            )
        return None

    def check_password(self, senha):
        return check_password_hash(self.senha_hash, senha)

    def alterar_senha(self, nova_senha):
        conn = get_db_connection()
        cursor = conn.cursor()
        novo_hash = generate_password_hash(nova_senha)
        cursor.execute("UPDATE usuarios SET password_hash = %s WHERE id = %s", (novo_hash, self.id))
        conn.commit()
        cursor.close()
        conn.close()
        self.senha_hash = novo_hash
        self.password = novo_hash

    @staticmethod
    def criar_usuario(username, nome_completo, nivel, senha, cliente_id=None):
        conn = get_db_connection()
        cursor = conn.cursor()
        senha_hash = generate_password_hash(senha)
        cursor.execute(
            "INSERT INTO usuarios (username, nome_completo, nivel, ativo, password_hash, cliente_id) VALUES (%s, %s, %s, true, %s, %s)",
            (username, nome_completo, nivel, senha_hash, cliente_id)
        )
        user_id = cursor.lastrowid
        conn.commit()
        cursor.close()
        conn.close()
        return user_id

    @staticmethod
    def listar_todos(incluir_inativos=True):
        """Lista todos os usuários do sistema"""
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        if incluir_inativos:
            query = """
                SELECT u.*, c.razao_social as cliente_nome
                FROM usuarios u
                LEFT JOIN clientes c ON u.cliente_id = c.id
                ORDER BY u.ativo DESC, u.nome_completo
            """
        else:
            query = """
                SELECT u.*, c.razao_social as cliente_nome
                FROM usuarios u
                LEFT JOIN clientes c ON u.cliente_id = c.id
                WHERE u.ativo = TRUE
                ORDER BY u.nome_completo
            """
        cursor.execute(query)
        users = cursor.fetchall()
        cursor.close()
        conn.close()
        return users

    @staticmethod
    def get_by_id_completo(user_id):
        """Busca usuário com informações completas incluindo cliente"""
        try:
            logger.info(f"Buscando usuário completo ID: {user_id}")
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            
            # Tentar query com cliente_id primeiro
            try:
                cursor.execute("""
                    SELECT u.*, c.razao_social as cliente_nome
                    FROM usuarios u
                    LEFT JOIN clientes c ON u.cliente_id = c.id
                    WHERE u.id = %s
                """, (user_id,))
                logger.info("Query com cliente_id executada com sucesso")
            except Exception as e:
                # Se falhar (campo cliente_id não existe), tentar sem ele
                logger.warning(f"Campo cliente_id não existe, buscando sem ele: {str(e)}")
                cursor.execute("""
                    SELECT u.*, NULL as cliente_nome
                    FROM usuarios u
                    WHERE u.id = %s
                """, (user_id,))
            
            user_data = cursor.fetchone()
            cursor.close()
            conn.close()
            
            if user_data:
                logger.info(f"Usuário encontrado: {user_data.get('username', 'N/A')}")
            else:
                logger.warning(f"Usuário {user_id} não encontrado")
            
            return user_data
        except Exception as e:
            logger.error(f"Erro ao buscar usuário completo {user_id}: {str(e)}", exc_info=True)
            return None

    def atualizar(self, username=None, nome_completo=None, nivel=None, cliente_id=None):
        """Atualiza os dados do usuário"""
        conn = get_db_connection()
        cursor = conn.cursor()
        
        updates = []
        params = []
        
        if username is not None:
            updates.append("username = %s")
            params.append(username)
            self.username = username
        
        if nome_completo is not None:
            updates.append("nome_completo = %s")
            params.append(nome_completo)
            self.nome_completo = nome_completo
            self.nome = nome_completo
        
        if nivel is not None:
            updates.append("nivel = %s")
            params.append(nivel)
            self.nivel = nivel
        
        # Atualizar cliente_id (pode ser None para remover associação)
        if cliente_id is not None:
            updates.append("cliente_id = %s")
            params.append(cliente_id if cliente_id else None)
        
        if updates:
            params.append(self.id)
            query = f"UPDATE usuarios SET {', '.join(updates)} WHERE id = %s"
            cursor.execute(query, params)
            conn.commit()
        
        cursor.close()
        conn.close()

    def desativar(self):
        """Desativa o usuário"""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE usuarios SET ativo = FALSE WHERE id = %s", (self.id,))
        conn.commit()
        cursor.close()
        conn.close()
        self.ativo = False

    def ativar(self):
        """Ativa o usuário"""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE usuarios SET ativo = TRUE WHERE id = %s", (self.id,))
        conn.commit()
        cursor.close()
        conn.close()
        self.ativo = True

    @staticmethod
    def username_existe(username, excluir_id=None):
        """Verifica se um username já existe (útil para validação)"""
        conn = get_db_connection()
        cursor = conn.cursor()
        if excluir_id:
            cursor.execute("SELECT id FROM usuarios WHERE username = %s AND id != %s", (username, excluir_id))
        else:
            cursor.execute("SELECT id FROM usuarios WHERE username = %s", (username,))
        existe = cursor.fetchone() is not None
        cursor.close()
        conn.close()
        return existe

    @staticmethod
    def get_clientes_usuario(usuario_id):
        """
        Retorna lista de IDs dos clientes associados a um usuário.
        Funciona com ambos os sistemas: cliente_id único (PISTA) e múltiplos (GERENTE/SUPERVISOR).
        """
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cliente_ids = []
        
        try:
            # Primeiro, verificar se existe a tabela usuario_clientes
            cursor.execute("SHOW TABLES LIKE 'usuario_clientes'")
            tabela_existe = cursor.fetchone() is not None
            
            if tabela_existe:
                # Buscar da tabela de junção
                cursor.execute("""
                    SELECT cliente_id 
                    FROM usuario_clientes 
                    WHERE usuario_id = %s
                """, (usuario_id,))
                rows = cursor.fetchall()
                cliente_ids = [row['cliente_id'] for row in rows]
            
            # Se não encontrou nada na tabela de junção, buscar da coluna cliente_id
            if not cliente_ids:
                cursor.execute("SELECT cliente_id FROM usuarios WHERE id = %s", (usuario_id,))
                row = cursor.fetchone()
                if row and row['cliente_id']:
                    cliente_ids = [row['cliente_id']]
        
        except Exception as e:
            logger.error(f"Erro ao buscar clientes do usuário {usuario_id}: {e}")
        
        finally:
            cursor.close()
            conn.close()
        
        return cliente_ids

    @staticmethod
    def set_clientes_usuario(usuario_id, cliente_ids):
        """
        Define os clientes associados a um usuário.
        
        Args:
            usuario_id: ID do usuário
            cliente_ids: Lista de IDs de clientes (pode ser vazia ou None)
        
        Para PISTA: deve ter exatamente 1 cliente
        Para GERENTE/SUPERVISOR: pode ter múltiplos clientes
        """
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            # Verificar se tabela de junção existe
            cursor.execute("SHOW TABLES LIKE 'usuario_clientes'")
            tabela_existe = cursor.fetchone() is not None
            
            if not tabela_existe:
                # Se não existe, criar a tabela
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS usuario_clientes (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        usuario_id INT NOT NULL,
                        cliente_id INT NOT NULL,
                        criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE,
                        FOREIGN KEY (cliente_id) REFERENCES clientes(id) ON DELETE CASCADE,
                        UNIQUE KEY unique_usuario_cliente (usuario_id, cliente_id)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """)
                conn.commit()
            
            # Limpar associações existentes
            cursor.execute("DELETE FROM usuario_clientes WHERE usuario_id = %s", (usuario_id,))
            
            # Adicionar novas associações
            if cliente_ids:
                for cliente_id in cliente_ids:
                    if cliente_id:  # Ignorar valores None ou vazios
                        cursor.execute("""
                            INSERT IGNORE INTO usuario_clientes (usuario_id, cliente_id)
                            VALUES (%s, %s)
                        """, (usuario_id, cliente_id))
            
            # Para PISTA (compatibilidade), manter cliente_id na tabela usuarios
            # Se tem apenas 1 cliente, atualizar também a coluna cliente_id
            if cliente_ids and len(cliente_ids) == 1:
                cursor.execute("""
                    UPDATE usuarios SET cliente_id = %s WHERE id = %s
                """, (cliente_ids[0], usuario_id))
            else:
                # Se tem 0 ou múltiplos, limpar cliente_id
                cursor.execute("""
                    UPDATE usuarios SET cliente_id = NULL WHERE id = %s
                """, (usuario_id,))
            
            conn.commit()
            
        except Exception as e:
            conn.rollback()
            logger.error(f"Erro ao definir clientes do usuário {usuario_id}: {e}")
            raise
        
        finally:
            cursor.close()
            conn.close()

