from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateTable

from backend.app.database import create_database_engine, get_database_url
from backend.app.models import Base, Event, EventType, User


def test_database_url_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        get_database_url()


def test_sqlite_engine_is_explicit_and_isolated() -> None:
    engine = create_database_engine("sqlite:///:memory:")

    assert engine.url.drivername == "sqlite"
    assert engine.echo is False


def test_orm_metadata_contains_only_initial_approved_tables() -> None:
    assert set(Base.metadata.tables) == {"users", "events"}


def test_postgresql_mapping_uses_uuid_and_timezone_aware_timestamps() -> None:
    event_ddl = str(
        CreateTable(Event.__table__).compile(dialect=postgresql.dialect())
    )

    assert "UUID" in event_ddl
    assert "TIMESTAMP WITH TIME ZONE" in event_ddl


def test_user_events_are_owned_and_constraints_apply() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    user_id = uuid4()
    with Session(engine) as session:
        user = User(id=user_id)
        event = Event(
            user_id=user_id,
            event_type=EventType.SLEEP,
            occurred_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            duration_seconds=600,
        )
        user.events.append(event)
        session.add(user)
        session.commit()

        assert session.get(Event, event.id).user_id == user_id

        session.add(
            Event(
                user_id=user_id,
                event_type="sleep",
                occurred_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                duration_seconds=-1,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()

    inspector = inspect(engine)
    assert inspector.get_foreign_keys("events")[0]["referred_table"] == "users"
