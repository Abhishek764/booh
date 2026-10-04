from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.models import Base, Event, EventType, User
from backend.app.repositories.events import EventRepository
from backend.app.services.auth import AuthError, Principal
from backend.app.services.authorization import AuthorizationService


def test_owned_repository_query_prevents_horizontal_access() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    owner_id = uuid4()
    other_id = uuid4()
    event_id = uuid4()
    with Session(engine) as session:
        session.add_all([User(id=owner_id), User(id=other_id)])
        session.add(
            Event(
                id=event_id,
                user_id=owner_id,
                event_type=EventType.SLEEP,
                occurred_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
        )
        session.commit()
        repository = EventRepository()
        assert repository.get_owned_event(
            session, event_id=event_id, owner_id=owner_id
        ) is not None
        assert repository.get_owned_event(
            session, event_id=event_id, owner_id=other_id
        ) is None
        with pytest.raises(AuthError, match="resource_not_found"):
            AuthorizationService().require_event(
                session,
                principal=Principal(
                    user_id=other_id,
                    session_id=uuid4(),
                    email="other@example.test",
                    token_hash="token",
                    csrf_hash="csrf",
                ),
                event_id=event_id,
            )
