"""
Auto-migration runner: executes pending SQL files from /migrations/ at startup.

Tracks applied migrations in the `schema_migrations` table so each file runs
exactly once.  Errors in individual statements are logged as warnings and
recorded — they do not crash the application.
"""
import os
import logging

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'migrations')

_TRACKING_DDL = """
CREATE TABLE IF NOT EXISTS `schema_migrations` (
    `id`             INT AUTO_INCREMENT PRIMARY KEY,
    `migration_name` VARCHAR(255) NOT NULL,
    `applied_at`     DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `success`        TINYINT(1)  NOT NULL DEFAULT 1,
    `error_message`  TEXT        NULL,
    UNIQUE KEY `uq_sm_name` (`migration_name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""


def _parse_statements(sql_content):
    """Split SQL file into individual statements, skipping blank/comment-only chunks."""
    statements = []
    for raw in sql_content.split(';'):
        non_comment = [
            line for line in raw.split('\n')
            if line.strip() and not line.strip().startswith('--')
        ]
        if non_comment:
            statements.append(raw.strip())
    return statements


def run_pending_migrations(app):
    """
    Scan migrations/ directory, compare against schema_migrations table, and
    execute any files not yet recorded as successful.  Safe to call on every
    startup — already-applied migrations are skipped.
    """
    from utils.db import get_db_connection

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # Guarantee the tracking table exists
        cur.execute(_TRACKING_DDL)
        conn.commit()

        # Fetch already-applied migration names
        cur.execute("SELECT migration_name FROM schema_migrations WHERE success = 1")
        applied = {row[0] for row in cur.fetchall()}

        if not os.path.isdir(MIGRATIONS_DIR):
            app.logger.warning("[migrations] Diretório não encontrado: %s", MIGRATIONS_DIR)
            cur.close()
            conn.close()
            return

        all_sql = sorted(f for f in os.listdir(MIGRATIONS_DIR) if f.endswith('.sql'))
        pending = [f for f in all_sql if f not in applied]

        if not pending:
            app.logger.info("[migrations] Nenhuma migration pendente.")
            cur.close()
            conn.close()
            return

        app.logger.info("[migrations] %d migration(s) pendente(s): %s", len(pending), pending)

        applied_count = 0
        for name in pending:
            _run_one(app, conn, cur, name)
            applied_count += 1

        cur.close()
        conn.close()
        app.logger.info("[migrations] Concluído: %d migration(s) processada(s).", applied_count)

    except Exception:
        app.logger.warning(
            "[migrations] Runner falhou na inicialização (não crítico — app continua).",
            exc_info=True,
        )


def _run_one(app, conn, cur, name):
    """Execute a single migration file and record the result."""
    file_path = os.path.join(MIGRATIONS_DIR, name)
    try:
        with open(file_path, 'r', encoding='utf-8') as fh:
            sql_content = fh.read()

        statements = _parse_statements(sql_content)
        stmt_warnings = []

        for stmt in statements:
            if not stmt:
                continue
            try:
                cur.execute(stmt)
                # Consume result sets (SELECT statements) to keep the cursor clean
                if cur.description is not None:
                    cur.fetchall()
                conn.commit()
            except Exception as e:
                warn_msg = str(e)[:400]
                stmt_warnings.append(warn_msg)
                app.logger.warning("[migrations] %s — statement warning: %s", name, warn_msg)
                try:
                    conn.rollback()
                except Exception:
                    pass

        error_summary = '; '.join(stmt_warnings[:3])[:800] if stmt_warnings else None
        cur.execute(
            """INSERT INTO schema_migrations (migration_name, success, error_message)
               VALUES (%s, 1, %s)
               ON DUPLICATE KEY UPDATE
                   applied_at     = NOW(),
                   success        = 1,
                   error_message  = VALUES(error_message)""",
            (name, error_summary),
        )
        conn.commit()

        if stmt_warnings:
            app.logger.warning(
                "[migrations] %s aplicada com %d aviso(s) (colunas/índices já existentes são normais).",
                name, len(stmt_warnings),
            )
        else:
            app.logger.info("[migrations] %s aplicada com sucesso.", name)

    except Exception as e:
        err = str(e)[:800]
        app.logger.warning("[migrations] %s falhou: %s", name, err, exc_info=True)
        try:
            cur.execute(
                """INSERT INTO schema_migrations (migration_name, success, error_message)
                   VALUES (%s, 0, %s)
                   ON DUPLICATE KEY UPDATE
                       applied_at    = NOW(),
                       success       = 0,
                       error_message = VALUES(error_message)""",
                (name, err),
            )
            conn.commit()
        except Exception:
            pass
