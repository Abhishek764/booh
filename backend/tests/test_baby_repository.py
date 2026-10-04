from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import uuid4

from sqlalchemy.orm import Session

from backend.app.database import create_database_engine, create_session_factory
from backend.app.models import Baby, Base, User
from backend.app.repositories.babies import SqlAlchemyBabyRepository


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_baby_repository_includes_owner_in_every_operation() -> None:
    engine = create_database_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    owner_id = uuid4()
    other_id = uuid4()
    baby_id = uuid4()
    with Session(engine) as session:
        session.add_all(
            [
                User(id=owner_id, email="owner@example.test"),
                User(id=other_id, email="other@example.test"),
                Baby(
                    id=baby_id,
                    user_id=owner_id,
                    display_name="Synthetic baby",
                    date_of_birth=date(2025, 1, 2),
                    timezone="UTC",
                    created_at=NOW,
                    updated_at=NOW,
                ),
            ]
        )
        session.commit()

    repository = SqlAlchemyBabyRepository(create_session_factory(engine))
    assert [baby.id for baby in repository.list_owned(owner_id=owner_id)] == [baby_id]
    assert repository.list_owned(owner_id=other_id) == []
    assert repository.get_owned(baby_id=baby_id, owner_id=other_id) is None
    assert repository.update_owned(
        baby_id=baby_id, owner_id=other_id, changes={"display_name": "Attacker"}
    ) is None
    assert repository.delete_owned(baby_id=baby_id, owner_id=other_id) is False

    owner_baby = repository.get_owned(baby_id=baby_id, owner_id=owner_id)
    assert owner_baby is not None
    assert owner_baby.display_name == "Synthetic baby"
    updated = repository.update_owned(
        baby_id=baby_id, owner_id=owner_id, changes={"display_name": "Updated"}
    )
    assert updated is not None
    assert updated.display_name == "Updated"
    assert repository.delete_owned(baby_id=baby_id, owner_id=owner_id) is True
    assert repository.get_owned(baby_id=baby_id, owner_id=owner_id) is None
