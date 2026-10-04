"""User-owned event queries."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import Event


class EventRepository:
    """Repository methods include the authenticated owner in their predicates."""

    @staticmethod
    def get_owned_event(
        session: Session, *, event_id: uuid.UUID, owner_id: uuid.UUID
    ) -> Event | None:
        return session.scalar(
            select(Event).where(Event.id == event_id, Event.user_id == owner_id)
        )


__all__ = ["EventRepository"]
