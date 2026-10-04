from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy.orm import Session

from backend.app.database import create_database_engine, create_session_factory
from backend.app.models import Baby, Base, Event, EventType, User
from backend.app.repositories.events import SqlAlchemyEventRepository


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_event_repository_includes_baby_owner_in_every_operation() -> None:
    engine = create_database_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    owner_id = uuid4()
    other_id = uuid4()
    baby_id = uuid4()
    event_id = uuid4()
    with Session(engine) as session:
        session.add_all(
            [
                User(id=owner_id, email="owner@example.test"),
                User(id=other_id, email="other@example.test"),
                Baby(id=baby_id, user_id=owner_id, timezone="UTC"),
                Event(
                    id=event_id,
                    baby_id=baby_id,
                    event_type=EventType.FEED,
                    start_time=NOW,
                    feed_amount_ml=Decimal("120.00"),
                ),
            ]
        )
        session.commit()

    repository = SqlAlchemyEventRepository(create_session_factory(engine))
    assert repository.list_owned_for_baby(
        baby_id=baby_id, owner_id=owner_id, limit=10, offset=0
    ) is not None
    assert repository.list_owned_for_baby(
        baby_id=baby_id, owner_id=other_id, limit=10, offset=0
    ) is None
    assert repository.get_owned_event(event_id=event_id, owner_id=other_id) is None
    assert repository.update_owned_event(
        event_id=event_id,
        owner_id=other_id,
        changes={"feed_amount_ml": Decimal("999.00")},
    ) is None
    assert repository.delete_owned_event(event_id=event_id, owner_id=other_id) is False

    owned = repository.get_owned_event(event_id=event_id, owner_id=owner_id)
    assert owned is not None
    assert owned.feed_amount_ml == Decimal("120.00")
    updated = repository.update_owned_event(
        event_id=event_id,
        owner_id=owner_id,
        changes={"feed_amount_ml": Decimal("150.00")},
    )
    assert updated is not None
    assert updated.feed_amount_ml == Decimal("150.00")
