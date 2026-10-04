"""Authorization services for user-owned resources."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from backend.app.models import Event
from backend.app.repositories.events import EventRepository
from backend.app.services.auth import AuthError, Principal


class AuthorizationService:
    """Apply the principal's owner boundary at the repository query."""

    def __init__(self, event_repository: EventRepository | None = None) -> None:
        self._events = event_repository or EventRepository()

    def require_event(
        self, session: Session, *, principal: Principal, event_id: uuid.UUID
    ) -> Event:
        event = self._events.get_owned_event(
            session, event_id=event_id, owner_id=principal.user_id
        )
        if event is None:
            # Do not distinguish missing objects from another user's objects.
            raise AuthError("resource_not_found", 404)
        return event


__all__ = ["AuthorizationService"]
