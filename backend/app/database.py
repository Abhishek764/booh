"""Database engine and session-factory construction.

This module does not create a process-global connection. Callers must provide
an explicit URL or configure ``DATABASE_URL`` so tests can use an isolated
database and production cannot silently fall back to an unsafe default.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


def get_database_url(database_url: str | None = None) -> str:
    """Return the configured database URL or fail closed."""

    configured_url = database_url or os.getenv("DATABASE_URL")
    if not configured_url:
        raise RuntimeError("DATABASE_URL must be configured before database access")
    return configured_url


def create_database_engine(database_url: str | None = None) -> Engine:
    """Create an engine with safe defaults and no SQL statement logging."""

    url = get_database_url(database_url)
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine = create_engine(
        url,
        connect_args=connect_args,
        pool_pre_ping=True,
        echo=False,
    )
    if url.startswith("sqlite"):
        event.listen(engine, "connect", _enable_sqlite_foreign_keys)
    return engine


def _enable_sqlite_foreign_keys(dbapi_connection: object, _: object) -> None:
    """Make the isolated SQLite test strategy enforce PostgreSQL-like FKs."""

    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Build an explicit, non-autocommitting session factory for an engine."""

    return sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        class_=Session,
    )


@contextmanager
def session_scope(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    """Commit on success and roll back failed transactions."""

    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
