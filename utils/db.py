import mysql.connector
from mysql.connector import pooling, Error
from config import Config
import logging

# Configure logging
logger = logging.getLogger(__name__)

# Connection pool configuration
_connection_pool = None

def _get_connection_pool():
    """
    Get or create the MySQL connection pool.
    Uses singleton pattern to ensure only one pool exists.
    """
    global _connection_pool
    
    if _connection_pool is None:
        try:
            _connection_pool = pooling.MySQLConnectionPool(
                pool_name="nh_transportes_pool",
                pool_size=10,  # Maximum number of connections in the pool
                pool_reset_session=True,  # Reset session variables on connection return
                host=Config.DB_HOST,
                port=Config.DB_PORT,
                user=Config.DB_USER,
                password=Config.DB_PASSWORD,
                database=Config.DB_NAME,
                autocommit=False,  # Explicit transaction control
                connect_timeout=10,  # Connection timeout in seconds
                # Additional connection parameters for reliability
                charset='utf8mb4',
                use_unicode=True,
            )
            logger.info("MySQL connection pool created successfully")
        except Error as e:
            logger.error(f"Error creating connection pool: {e}")
            raise
    
    return _connection_pool

def get_db_connection():
    """
    Get a database connection from the pool.
    
    Returns:
        mysql.connector.connection: A database connection from the pool
        
    Raises:
        Error: If unable to get connection from pool
    """
    try:
        pool = _get_connection_pool()
        connection = pool.get_connection()
        
        # Test connection and reconnect if necessary
        if not connection.is_connected():
            connection.reconnect(attempts=3, delay=1)
            
        return connection
    except Error as e:
        logger.error(f"Error getting connection from pool: {e}")
        # Fallback to direct connection if pool fails
        logger.warning("Falling back to direct connection")
        return mysql.connector.connect(
            host=Config.DB_HOST,
            port=Config.DB_PORT,
            user=Config.DB_USER,
            password=Config.DB_PASSWORD,
            database=Config.DB_NAME,
            autocommit=False,
            connect_timeout=10,
            charset='utf8mb4',
            use_unicode=True,
        )
