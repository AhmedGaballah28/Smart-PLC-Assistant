"""
SQLite database connection and lifecycle utilities.

This module configures the SQLAlchemy engine, session factory,
SQLite pragmas, and helper methods for creating/dropping schema.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import Engine, event, inspect, text
from sqlalchemy import create_engine as sa_create_engine
from sqlalchemy.orm import Session, sessionmaker

from config.settings import DATABASE_PATH
from core.db_models import Base


_ENGINE: Engine | None = None
_SESSION_FACTORY: sessionmaker[Session] | None = None


def _sqlite_url() -> str:
    db_path = Path(DATABASE_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{db_path.as_posix()}"


def get_engine(echo: bool = False) -> Engine:
    global _ENGINE

    if _ENGINE is None:
        _ENGINE = sa_create_engine(
            _sqlite_url(),
            echo=echo,
            future=True,
            connect_args={"check_same_thread": False},
        )

        @event.listens_for(_ENGINE, "connect")
        def set_sqlite_pragmas(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON;")
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.execute("PRAGMA synchronous=NORMAL;")
            cursor.close()

    return _ENGINE


def get_session_factory() -> sessionmaker[Session]:
    global _SESSION_FACTORY

    if _SESSION_FACTORY is None:
        _SESSION_FACTORY = sessionmaker(
            bind=get_engine(),
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
            future=True,
        )

    return _SESSION_FACTORY


@contextmanager
def session_scope() -> Iterator[Session]:
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_sqlite_database(drop_existing: bool = False, echo: bool = False) -> list[str]:
    """
    Create database schema using Alembic migrations.

    Args:
        drop_existing: Drop all existing tables first.
        echo: SQLAlchemy SQL logging.

    Returns:
        List of created/available table names.
    """
    engine = get_engine(echo=echo)

    if drop_existing:
        Base.metadata.drop_all(bind=engine)

    # Use Alembic to apply migrations instead of raw create_all
    from alembic.config import Config
    from alembic import command

    alembic_ini_path = Path(__file__).resolve().parent.parent / "alembic.ini"
    alembic_cfg = Config(str(alembic_ini_path))
    command.upgrade(alembic_cfg, "head")

    return get_table_names()


def get_table_names() -> list[str]:
    inspector = inspect(get_engine())
    return sorted(inspector.get_table_names())


def health_check() -> bool:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
