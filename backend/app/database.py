import logging
import sys
from contextlib import contextmanager
from pathlib import Path

import psycopg
from psycopg import sql as psycopg_sql
from psycopg_pool import ConnectionPool

from app.config import get_settings

logger = logging.getLogger("app.database")

_pool: ConnectionPool | None = None


def ensure_database_exists() -> None:
    """Creates `postgres_db` if it doesn't exist yet, so a fresh Postgres
    server (no manual `createdb` step, no per-OS instructions) is enough to
    run the app. Connects to the always-present `postgres` maintenance
    database — never opens the app's own pool against a database that might
    not exist. `CREATE DATABASE` cannot run inside a transaction block, so
    this uses a plain autocommit connection rather than the pool.

    Only creates the database; it does NOT start a Postgres server or
    install Postgres itself — one must already be running and reachable at
    the configured host/port. Raises `SystemExit(1)` with a plain-language
    message (instead of letting a raw psycopg.OperationalError traceback
    reach the terminal) when it can't even reach the server, since that
    stack trace gives no hint that the fix is "start Postgres" rather than
    an application bug."""
    settings = get_settings()
    try:
        conn = psycopg.connect(settings.postgres_maintenance_conninfo, autocommit=True, connect_timeout=5)
    except psycopg.OperationalError as e:
        print(
            f"FATAL: could not reach a Postgres server at "
            f"{settings.postgres_host}:{settings.postgres_port} ({e}).\n"
            "Start Postgres first, then start the backend again. This app does not start "
            "Postgres for you — only the 'control_assessment' database and its tables, "
            "once a server is reachable.",
            file=sys.stderr,
        )
        raise SystemExit(1) from e
    with conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (settings.postgres_db,))
            if cur.fetchone() is None:
                logger.info("Database %r does not exist yet — creating it.", settings.postgres_db)
                # Identifiers can't be parameterized like values; psycopg.sql
                # quotes it safely instead of an f-string, so a name with a
                # quote/space in it still can't become a SQL-injection path.
                cur.execute(psycopg_sql.SQL("CREATE DATABASE {}").format(psycopg_sql.Identifier(settings.postgres_db)))


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        settings = get_settings()
        _pool = ConnectionPool(conninfo=settings.postgres_conninfo, min_size=1, max_size=10, open=True)
    return _pool


@contextmanager
def get_conn():
    pool = get_pool()
    with pool.connection() as conn:
        yield conn


def run_migrations() -> None:
    ensure_database_exists()
    migration_path = Path(__file__).resolve().parent / "migrations" / "init.sql"
    sql = migration_path.read_text()
    with get_conn() as conn:
        conn.execute(sql)
        conn.commit()


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None
