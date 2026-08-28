from contextlib import contextmanager
from pathlib import Path

from psycopg_pool import ConnectionPool

from app.config import get_settings

_pool: ConnectionPool | None = None


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
