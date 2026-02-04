# Script de migração para adicionar suporte a múltiplos clientes por usuário

"""
Este script cria uma tabela de junção para permitir que GERENTE e SUPERVISOR
possam estar associados a múltiplos clientes/postos.

Estrutura:
- usuarios: tabela principal (já existe)
- usuario_clientes: nova tabela de junção (muitos-para-muitos)

NOTA: A coluna 'cliente_id' na tabela 'usuarios' será mantida para 
compatibilidade com PISTA (que tem apenas 1 posto).
"""

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS usuario_clientes (
    id INT AUTO_INCREMENT PRIMARY KEY,
    usuario_id INT NOT NULL,
    cliente_id INT NOT NULL,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE,
    FOREIGN KEY (cliente_id) REFERENCES clientes(id) ON DELETE CASCADE,
    UNIQUE KEY unique_usuario_cliente (usuario_id, cliente_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
"""

# Migrar dados existentes da coluna cliente_id para a nova tabela
MIGRATE_DATA_SQL = """
INSERT IGNORE INTO usuario_clientes (usuario_id, cliente_id)
SELECT id, cliente_id 
FROM usuarios 
WHERE cliente_id IS NOT NULL;
"""

def run_migration():
    """
    Execute esta migração no banco de dados.
    
    Pode ser executado via:
    1. Diretamente no MySQL
    2. Via script Python
    3. Via interface de administração do banco
    """
    print("SQL para criar tabela de junção:")
    print(CREATE_TABLE_SQL)
    print("\nSQL para migrar dados existentes:")
    print(MIGRATE_DATA_SQL)
    print("\nExecute estes comandos no seu banco de dados MySQL.")

if __name__ == "__main__":
    run_migration()
