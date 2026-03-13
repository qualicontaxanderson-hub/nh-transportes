import mysql.connector
from mysql.connector import pooling, Error
from config import Config
import logging
import time

# Configure logging
logger = logging.getLogger(__name__)

# Connection pool configuration
_connection_pool = None

# Reconnection constants
RECONNECT_ATTEMPTS = 3
RECONNECT_DELAY = 1  # seconds

# Shared connection parameters for pool and fallback connections
CONNECTION_PARAMS = {
    'host': Config.DB_HOST,
    'port': Config.DB_PORT,
    'user': Config.DB_USER,
    'password': Config.DB_PASSWORD,
    'database': Config.DB_NAME,
    'autocommit': False,  # Explicit transaction control
    'connect_timeout': Config.DB_CONNECT_TIMEOUT,
    'charset': 'utf8mb4',
    'use_unicode': True,
}

def _get_connection_pool():
    """
    Get or create the MySQL connection pool.
    Uses singleton pattern to ensure only one pool exists.
    """
    global _connection_pool
    
    if _connection_pool is None:
        try:
            pool_config = {
                'pool_name': 'nh_transportes_pool',
                'pool_size': Config.DB_POOL_SIZE,
                # pool_reset_session=True (default) issues ROLLBACK when a connection is
                # returned to the pool, clearing its MVCC snapshot.  Without this,
                # connections returned mid-transaction hold a stale InnoDB REPEATABLE READ
                # snapshot, causing recently-committed rows to appear unchanged (e.g. a
                # bank_transaction just set to 'conciliado' reappearing as 'pendente').
                # Dead connections on acquire are already handled by ping(reconnect=True).
                'pool_reset_session': True,
                **CONNECTION_PARAMS
            }
            _connection_pool = pooling.MySQLConnectionPool(**pool_config)
            logger.info(f"MySQL connection pool created successfully (size: {Config.DB_POOL_SIZE})")
        except Error as e:
            logger.error(f"Error creating connection pool: {e}")
            raise
    
    return _connection_pool

def get_db_connection():
    """
    Get a database connection from the pool.
    Falls back to a direct connection if the pool is unavailable.
    Pings the connection to detect and recover stale connections obtained
    from the pool (common when Railway proxy closes idle connections).
    
    Returns:
        mysql.connector.connection: A database connection from the pool
        
    Raises:
        Error: If unable to get connection from pool or direct fallback
    """
    try:
        pool = _get_connection_pool()
        connection = pool.get_connection()
        
        # Ping / reconnect if the pooled connection has gone stale.
        # This handles Railway proxy drop-outs without raising to the caller.
        try:
            connection.ping(reconnect=True, attempts=RECONNECT_ATTEMPTS, delay=RECONNECT_DELAY)
        except Error:
            # ping() already attempted reconnect; if still broken, fall through
            # to the direct-connection fallback below.
            raise
            
        return connection
    except Error as e:
        logger.error(f"Error getting connection from pool: {e}")
        # Fallback to direct connection if pool fails
        logger.warning("Falling back to direct connection")
        for attempt in range(1, RECONNECT_ATTEMPTS + 1):
            try:
                return mysql.connector.connect(**CONNECTION_PARAMS)
            except Error as direct_err:
                logger.warning(f"Direct connection attempt {attempt}/{RECONNECT_ATTEMPTS} failed: {direct_err}")
                if attempt < RECONNECT_ATTEMPTS:
                    time.sleep(RECONNECT_DELAY)
        raise

