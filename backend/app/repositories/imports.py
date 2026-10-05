"""Transactional, owner-scoped event import and database duplicate detection."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.database import session_scope
from backend.app.event_values import NormalizedEvent, event_identity
from backend.app.models import Baby, Event, EventSource


@dataclass(frozen=True, slots=True)
class ImportWriteResult:
    imported: int
    duplicates: int


class OwnedImportRepository(Protocol):
    def get_owned_timezone(self, *, baby_id: uuid.UUID, owner_id: uuid.UUID) -> str | None: ...

    def import_owned_events(
        self, *, baby_id: uuid.UUID, owner_id: uuid.UUID, events: list[NormalizedEvent]
    ) -> ImportWriteResult | None: ...


class SqlAlchemyImportRepository:
    """Lock the owned baby for imports; query only incoming timestamps in batches."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get_owned_timezone(self, *, baby_id: uuid.UUID, owner_id: uuid.UUID) -> str | None:
        with session_scope(self._session_factory) as session:
            return session.scalar(
                select(Baby.timezone).where(Baby.id == baby_id, Baby.user_id == owner_id)
            )

    def import_owned_events(
        self, *, baby_id: uuid.UUID, owner_id: uuid.UUID, events: list[NormalizedEvent]
    ) -> ImportWriteResult | None:
        if len(events) > 10000:
            raise ValueError("too many import events")
        with session_scope(self._session_factory) as session:
            baby = session.scalar(
                select(Baby.id)
                .where(Baby.id == baby_id, Baby.user_id == owner_id)
                .with_for_update()
            )
            if baby is None:
                return None
            imported = duplicates = 0
            seen: set[tuple[object, ...]] = set()
            for offset in range(0, len(events), 200):
                batch = events[offset:offset + 200]
                incoming_keys = {event_identity(event) for event in batch}
                existing = session.execute(
                    select(
                        Event.event_type, Event.start_time, Event.end_time,
                        Event.duration_seconds, Event.feed_amount_ml,
                    )
                    .join(Baby, Event.baby_id == Baby.id)
                    .where(
                        Baby.user_id == owner_id, Baby.id == baby_id,
                        Event.start_time.in_({event.start_time for event in batch}),
                    )
                    .execution_options(yield_per=200)
                )
                for row in existing:
                    key = event_identity(NormalizedEvent(*row))
                    if key in incoming_keys:
                        seen.add(key)
                for event in batch:
                    key = event_identity(event)
                    if key in seen:
                        duplicates += 1
                        continue
                    seen.add(key)
                    session.add(Event(
                        baby_id=baby_id, source=EventSource.IMPORT,
                        event_type=event.event_type, start_time=event.start_time,
                        end_time=event.end_time, duration_seconds=event.duration_seconds,
                        feed_amount_ml=event.feed_amount_ml,
                    ))
                    imported += 1
                session.flush()
            # session_scope commits all valid rows together, or rolls everything back.
            return ImportWriteResult(imported=imported, duplicates=duplicates)
