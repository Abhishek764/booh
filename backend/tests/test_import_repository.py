from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.database import create_database_engine, create_session_factory
from backend.app.event_values import NormalizedEvent
from backend.app.models import Baby, Base, Event, EventType, User
from backend.app.repositories.imports import SqlAlchemyImportRepository
from backend.tests.test_importers import NOW


@pytest.fixture
def repository():
    engine = create_database_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    owner, other, baby = uuid4(), uuid4(), uuid4()
    with Session(engine) as session:
        session.add_all([User(id=owner), User(id=other), Baby(id=baby, user_id=owner, timezone="UTC")])
        session.commit()
    yield SqlAlchemyImportRepository(create_session_factory(engine)), engine, owner, other, baby
    engine.dispose()


def test_import_repository_rechecks_ownership_and_detects_cross_batch_duplicates(repository):
    repo, engine, owner, other, baby = repository
    events = [NormalizedEvent(EventType.WAKE, NOW - timedelta(minutes=index), None, None, None) for index in range(201)]
    events.append(events[0])
    assert repo.get_owned_timezone(baby_id=baby, owner_id=other) is None
    assert repo.import_owned_events(baby_id=baby, owner_id=other, events=events) is None
    result = repo.import_owned_events(baby_id=baby, owner_id=owner, events=events)
    assert result.imported == 201
    assert result.duplicates == 1
    repeated = repo.import_owned_events(baby_id=baby, owner_id=owner, events=events)
    assert repeated.imported == 0
    assert repeated.duplicates == 202
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Event)) == 201


def test_database_failure_after_a_flushed_batch_rolls_back_the_whole_import(repository):
    repo, engine, owner, _, baby = repository
    events = [NormalizedEvent(EventType.WAKE, NOW - timedelta(minutes=index), None, None, None) for index in range(201)]
    writes = 0

    def fail_after_first_batch(mapper, connection, target):
        nonlocal writes
        writes += 1
        if writes > 200:
            raise SQLAlchemyError("synthetic transaction failure")

    event.listen(Event, "before_insert", fail_after_first_batch)
    try:
        with pytest.raises(SQLAlchemyError):
            repo.import_owned_events(baby_id=baby, owner_id=owner, events=events)
    finally:
        event.remove(Event, "before_insert", fail_after_first_batch)
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Event)) == 0
