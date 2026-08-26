"""
Auto-migration runner: executes pending SQL files from /migrations/ at startup.

Tracks applied migrations in the `schema_migrations` table so each file runs
exactly once.  Errors in individual statements are logged as warnings and
recorded — they do not crash the application.
"""
import os
import re
import logging

logger = logging.getLogger(__name__)

# Erros que so dizem "isso ja existe" — rodar a migration de novo nao muda
# nada, entao valem como aplicada. Qualquer outro erro e falha de verdade.
_JA_APLICADO = {
    1050,  # tabela ja existe
    1060,  # coluna duplicada
    1061,  # indice duplicado
    1062,  # linha duplicada (seed rodando de novo)
    1091,  # DROP de coluna/indice que nao existe
    1826,  # chave estrangeira duplicada
}


def _codigo_do_erro(e):
    """Numero do erro MySQL, venha ele do driver ou so do texto."""
    n = getattr(e, 'errno', None)
    if isinstance(n, int):
        return n
    achou = re.match(r'\s*\(?(\d{4})', str(e))
    return int(achou.group(1)) if achou else None

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
        avisos = []   # "ja existe": a migration ja valeu
        falhas = []   # erro de verdade: sintaxe, tabela que falta, etc.

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
                msg = str(e)[:400]
                if _codigo_do_erro(e) in _JA_APLICADO:
                    avisos.append(msg)
                    app.logger.warning("[migrations] %s — já aplicado: %s", name, msg)
                else:
                    falhas.append(msg)
                    app.logger.error("[migrations] %s — FALHOU: %s", name, msg)
                try:
                    conn.rollback()
                except Exception:
                    pass

        # Marcar falha como sucesso enterra o problema: foi assim que as duas
        # colunas de boleto ficaram tres meses sem existir, com o erro de
        # sintaxe guardado numa linha que dizia success=1.
        ok = 0 if falhas else 1
        resumo = '; '.join((falhas + avisos)[:3])[:800] or None
        cur.execute(
            """INSERT INTO schema_migrations (migration_name, success, error_message)
               VALUES (%s, %s, %s)
               ON DUPLICATE KEY UPDATE
                   applied_at     = NOW(),
                   success        = VALUES(success),
                   error_message  = VALUES(error_message)""",
            (name, ok, resumo),
        )
        conn.commit()

        if falhas:
            app.logger.error(
                "[migrations] %s NAO aplicada: %d erro(s). Fica pendente e tenta de novo no proximo boot.",
                name, len(falhas),
            )
        elif avisos:
            app.logger.warning(
                "[migrations] %s aplicada com %d aviso(s) (coluna/índice que já existia).",
                name, len(avisos),
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
