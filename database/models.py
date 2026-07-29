import sqlite3
from config import DB_PATH, TURSO_URL, TURSO_TOKEN


def _get_conn():
    if TURSO_URL and TURSO_TOKEN:
        try:
            import libsql_experimental as libsql
            conn = libsql.connect(str(DB_PATH), sync_url=TURSO_URL, auth_token=TURSO_TOKEN)
            conn.sync()
            return conn, True
        except ImportError:
            pass
    return sqlite3.connect(str(DB_PATH)), False


def init_db() -> None:
    conn, is_turso = _get_conn()
    with conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id           INTEGER PRIMARY KEY,
                username     TEXT,
                first_name   TEXT,
                joined_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                stage        TEXT DEFAULT 'new',
                paid_at      TIMESTAMP,
                reminded_24h INTEGER DEFAULT 0,
                reminded_72h INTEGER DEFAULT 0,
                phone        TEXT
            );

            CREATE TABLE IF NOT EXISTS payments (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id      INTEGER REFERENCES users(id),
                tribute_id   TEXT,
                amount       REAL,
                status       TEXT DEFAULT 'pending',
                created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS pending_payments (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                phone        TEXT UNIQUE,
                email        TEXT,
                order_id     TEXT,
                created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS message_log (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id      INTEGER,
                username     TEXT,
                first_name   TEXT,
                text         TEXT,
                received_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        if is_turso:
            try:
                conn.sync()
            except Exception:
                pass
        # migrations
        for col_sql in [
            "ALTER TABLE users ADD COLUMN phone TEXT",
            "ALTER TABLE users ADD COLUMN drip_started_at TIMESTAMP",
            "ALTER TABLE users ADD COLUMN drip_step INTEGER DEFAULT 0",
        ]:
            try:
                conn.execute(col_sql)
            except sqlite3.OperationalError:
                pass
