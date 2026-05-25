"""SQLCipher3 database engine and session management.

Exports:
    sync_engine — module-level engine created from env vars (for Alembic)
    init_db(key, path) — called from lifespan to set up the app engine
    get_db() — FastAPI dependency that yields a synchronous Session
"""
import os
from typing import Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

# ---------------------------------------------------------------------------
# Declarative base for all ORM models
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# PRAGMAs applied after every new connection (including Alembic's)
# ---------------------------------------------------------------------------

def _apply_pragmas(dbapi_conn, _connection_record):
    """Configure SQLCipher and SQLite PRAGMAs on every new connection."""
    key = os.environ.get("FINANCEHUB_DB_KEY", "")
    if key:
        dbapi_conn.execute(f"PRAGMA key='{key}'")
    dbapi_conn.execute("PRAGMA journal_mode=WAL")
    dbapi_conn.execute("PRAGMA foreign_keys=ON")
    dbapi_conn.execute("PRAGMA synchronous=NORMAL")
    dbapi_conn.execute("PRAGMA cipher_page_size=4096")
    dbapi_conn.execute("PRAGMA kdf_iter=256000")


def _make_engine(db_path: str):
    """Create a SQLAlchemy engine for the given SQLCipher3 database path."""
    url = f"sqlite+pysqlcipher3:///:/{db_path}?timeout=30"
    engine = create_engine(url, connect_args={"check_same_thread": False})
    event.listen(engine, "connect", _apply_pragmas)
    return engine


# ---------------------------------------------------------------------------
# Module-level engine — consumed by Alembic env.py at import time.
# Reads from environment variables so Alembic can use it without lifespan.
# ---------------------------------------------------------------------------

_DB_KEY = os.environ.get("FINANCEHUB_DB_KEY", "")
_DB_PATH = os.environ.get("FINANCEHUB_DB_PATH", "/data/financehub.db")

sync_engine = _make_engine(_DB_PATH)

# ---------------------------------------------------------------------------
# App-level engine — replaced by init_db() during lifespan startup
# ---------------------------------------------------------------------------

_app_engine = None
_SessionLocal: sessionmaker | None = None


def init_db(key: str, path: str) -> None:
    """Initialise the application database engine.

    Called once during FastAPI lifespan after secrets are loaded.
    Sets FINANCEHUB_DB_KEY in the environment so _apply_pragmas can read it,
    then replaces the module-level sync_engine with a fresh engine targeting
    the correct path.
    """
    global _app_engine, _SessionLocal, sync_engine, _DB_KEY, _DB_PATH

    os.environ["FINANCEHUB_DB_KEY"] = key
    _DB_KEY = key
    _DB_PATH = path

    _app_engine = _make_engine(path)
    sync_engine = _app_engine  # keep Alembic's reference up-to-date
    _SessionLocal = sessionmaker(bind=_app_engine, autocommit=False, autoflush=False)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency — yields a synchronous SQLAlchemy Session."""
    if _SessionLocal is None:
        raise RuntimeError("Database not initialised — init_db() must be called from lifespan")
    db = _SessionLocal()
    try:
        yield db
    finally:
        db.close()
