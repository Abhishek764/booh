"""Owner-scoped persistence queries for baby events."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.database import session_scope
from backend.app.models import Baby, Event, EventSource, EventType


@dataclass(frozen=True, slots=True)
class EventRecord:
    """Persistence-independent event data returned to the service layer."""

    id: uuid.UUID
    baby_id: uuid.UUID
    event_type: EventType
    source: EventSource
    start_time: datetime
    end_time: datetime | None
    duration_seconds: int | None
    feed_amount_ml: Decimal | None
    created_at: datetime
    updated_at: datetime


class OwnedEventRepository(Protocol):
    """Persistence contract that requires the authenticated owner."""

    def list_owned_for_baby(
        self,
        *,
        baby_id: uuid.UUID,
        owner_id: uuid.UUID,
        limit: int,
        offset: int,
    ) -> list[EventRecord] | None: ...

    def create_owned_for_baby(
        self,
        *,
        baby_id: uuid.UUID,
        owner_id: uuid.UUID,
        event_type: EventType,
        start_time: datetime,
        end_time: datetime | None,
        duration_seconds: int | None,
        feed_amount_ml: Decimal | None,
    ) -> EventRecord | None: ...

    def get_owned_event(
        self, *, event_id: uuid.UUID, owner_id: uuid.UUID
    ) -> EventRecord | None: ...

    def update_owned_event(
        self,
        *,
        event_id: uuid.UUID,
        owner_id: uuid.UUID,
        changes: dict[str, object],
    ) -> EventRecord | None: ...

    def delete_owned_event(self, *, event_id: uuid.UUID, owner_id: uuid.UUID) -> bool: ...


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _record(event: Event) -> EventRecord:
    return EventRecord(
        id=event.id,
        baby_id=event.baby_id,
        event_type=EventType(event.event_type),
        source=EventSource(event.source),
        start_time=_utc(event.start_time),
        end_time=None if event.end_time is None else _utc(event.end_time),
        duration_seconds=event.duration_seconds,
        feed_amount_ml=event.feed_amount_ml,
        created_at=_utc(event.created_at),
        updated_at=_utc(event.updated_at),
    )


class EventRepository:
    """Repository methods include the authenticated owner in their predicates."""

    @staticmethod
    def get_owned_event(
        session: Session, *, event_id: uuid.UUID, owner_id: uuid.UUID
    ) -> Event | None:
        return session.scalar(
            select(Event)
            .join(Baby, Event.baby_id == Baby.id)
            .where(Event.id == event_id, Baby.user_id == owner_id)
        )


_UPDATABLE_FIELDS = frozenset(
    {"event_type", "start_time", "end_time", "duration_seconds", "feed_amount_ml"}
)


class SqlAlchemyEventRepository:
    """SQLAlchemy implementation with baby-owner predicates in every query."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def list_owned_for_baby(
        self,
        *,
        baby_id: uuid.UUID,
        owner_id: uuid.UUID,
        limit: int,
        offset: int,
    ) -> list[EventRecord] | None:
        with session_scope(self._session_factory) as session:
            baby_exists = session.scalar(
                select(Baby.id).where(Baby.id == baby_id, Baby.user_id == owner_id)
            )
            if baby_exists is None:
                return None
            events = session.scalars(
                select(Event)
                .where(Event.baby_id == baby_id)
                .order_by(Event.start_time.desc(), Event.id.desc())
                .offset(offset)
                .limit(limit)
            ).all()
            return [_record(event) for event in events]

    def create_owned_for_baby(
        self,
        *,
        baby_id: uuid.UUID,
        owner_id: uuid.UUID,
        event_type: EventType,
        start_time: datetime,
        end_time: datetime | None,
        duration_seconds: int | None,
        feed_amount_ml: Decimal | None,
    ) -> EventRecord | None:
        with session_scope(self._session_factory) as session:
            baby_exists = session.scalar(
                select(Baby.id).where(Baby.id == baby_id, Baby.user_id == owner_id).with_for_update()
            )
            if baby_exists is None:
                return None
            event = Event(
                baby_id=baby_id,
                event_type=event_type,
                source=EventSource.MANUAL,
                start_time=start_time,
                end_time=end_time,
                duration_seconds=duration_seconds,
                feed_amount_ml=feed_amount_ml,
            )
            session.add(event)
            session.flush()
            session.refresh(event)
            return _record(event)

    def get_owned_event(
        self, *, event_id: uuid.UUID, owner_id: uuid.UUID
    ) -> EventRecord | None:
        with session_scope(self._session_factory) as session:
            event = session.scalar(
                select(Event)
                .join(Baby, Event.baby_id == Baby.id)
                .where(Event.id == event_id, Baby.user_id == owner_id)
            )
            return None if event is None else _record(event)

    def update_owned_event(
        self,
        *,
        event_id: uuid.UUID,
        owner_id: uuid.UUID,
        changes: dict[str, object],
    ) -> EventRecord | None:
        with session_scope(self._session_factory) as session:
            # Every history mutation takes the same baby lock as prediction writes.
            session.scalar(select(Baby.id).join(Event, Event.baby_id == Baby.id)
                           .where(Event.id == event_id, Baby.user_id == owner_id).with_for_update(of=Baby))
            event = session.scalar(
                select(Event)
                .join(Baby, Event.baby_id == Baby.id)
                .where(Event.id == event_id, Baby.user_id == owner_id)
            )
            if event is None:
                return None
            for field, value in changes.items():
                if field not in _UPDATABLE_FIELDS:
                    raise ValueError("unsupported event field")
                setattr(event, field, value)
            session.flush()
            session.refresh(event)
            return _record(event)

    def delete_owned_event(self, *, event_id: uuid.UUID, owner_id: uuid.UUID) -> bool:
        with session_scope(self._session_factory) as session:
            session.scalar(select(Baby.id).join(Event, Event.baby_id == Baby.id)
                           .where(Event.id == event_id, Baby.user_id == owner_id).with_for_update(of=Baby))
            event = session.scalar(
                select(Event)
                .join(Baby, Event.baby_id == Baby.id)
                .where(Event.id == event_id, Baby.user_id == owner_id)
            )
            if event is None:
                return False
            session.delete(event)
            return True


__all__ = ["EventRecord", "EventRepository", "OwnedEventRepository", "SqlAlchemyEventRepository"]
