from contextlib import contextmanager
from typing import Iterator

from src.config import get_setting
from src.security import sanitize_error_message


class DatabaseUnavailable(RuntimeError):
    """Raised when the database is not configured or the driver is unavailable."""


def get_database_url() -> str | None:
    value = get_setting("DATABASE_URL")
    return value.strip() if value and value.strip() else None


def has_database_config() -> bool:
    return get_database_url() is not None


def _import_psycopg():
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise DatabaseUnavailable(
            "PostgreSQL driver not installed. Install psycopg[binary] to use DATABASE_URL."
        ) from exc
    return psycopg, dict_row


@contextmanager
def get_connection(database_url: str | None = None) -> Iterator:
    url = database_url or get_database_url()
    if not url:
        raise DatabaseUnavailable("DATABASE_URL is not configured.")

    psycopg, dict_row = _import_psycopg()
    with psycopg.connect(url, row_factory=dict_row) as conn:
        yield conn


def check_database(database_url: str | None = None) -> tuple[bool, str | None]:
    url = database_url or get_database_url()
    try:
        with get_connection(url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        return True, None
    except Exception as exc:
        return False, sanitize_error_message(exc, [url])
