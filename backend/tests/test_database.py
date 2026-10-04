from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, func, inspect, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateTable

from backend.app.database import create_database_engine, get_database_url
from backend.app.models import (
    Audio,
    Baby,
    Base,
    Event,
    EventType,
    Prediction,
    Summary,
    User,
)


NOW = datetime(2026, 1, 1, 3, 0, tzinfo=timezone.utc)


def test_database_url_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        get_database_url()


def test_database_connection_and_sqlite_foreign_keys_are_enabled() -> None:
    engine = create_database_engine("sqlite:///:memory:")

    with engine.connect() as connection:
        assert connection.scalar(select(1)) == 1
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1


def test_sqlite_engine_is_explicit_and_isolated() -> None:
    engine = create_database_engine("sqlite:///:memory:")

    assert engine.url.drivername == "sqlite"
    assert engine.echo is False


def test_orm_metadata_contains_database_foundation_tables() -> None:
    assert set(Base.metadata.tables) == {
        "users",
        "user_identities",
        "auth_sessions",
        "oauth_transactions",
        "babies",
        "events",
        "predictions",
        "summaries",
        "audio",
    }


def test_postgresql_mapping_uses_uuid_and_timezone_aware_timestamps() -> None:
    for table in (Baby.__table__, Event.__table__, Prediction.__table__):
        ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))
        assert "UUID" in ddl
        assert "TIMESTAMP WITH TIME ZONE" in ddl


def test_relationships_and_cascading_delete_cover_the_owned_graph() -> None:
    engine = create_database_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    user_id = uuid4()
    baby_id = uuid4()
    prediction_id = uuid4()
    summary_id = uuid4()

    with Session(engine) as session:
        user = User(id=user_id, email="synthetic@example.test")
        baby = Baby(id=baby_id, user_id=user_id, display_name="Synthetic profile")
        event = Event(
            id=uuid4(),
            baby_id=baby_id,
            event_type=EventType.FEED,
            start_time=NOW,
            end_time=NOW,
            duration_seconds=300,
            feed_amount_ml=Decimal("120.00"),
        )
        prediction = Prediction(
            id=prediction_id,
            baby_id=baby_id,
            prediction_timestamp=NOW,
            expected_sleep_minutes=90,
            wake_probability_within_60m=Decimal("0.7500"),
            baseline_expected_sleep_minutes=80,
            model_version="baseline-v1",
            feature_version="features-v1",
            feature_metadata={"window_days": 7},
        )
        summary = Summary(
            id=summary_id,
            prediction=prediction,
            summary_text="Synthetic advisory summary.",
            provider_version="summary-test-v1",
        )
        audio = Audio(
            summary=summary,
            provider="synthetic",
            provider_version="tts-test-v1",
            storage_key="synthetic/audio/one.ogg",
            content_type="audio/ogg",
            byte_size=1024,
            duration_ms=2200,
        )
        user.babies.append(baby)
        baby.events.append(event)
        baby.predictions.append(prediction)
        summary.audio_files.append(audio)
        session.add(user)
        session.commit()

        assert baby.user is user
        assert event.baby is baby
        assert prediction.baby is baby
        assert summary.prediction is prediction
        assert audio.summary is summary

        session.delete(user)
        session.commit()
        for model in (Baby, Event, Prediction, Summary, Audio):
            assert session.scalar(select(func.count()).select_from(model)) == 0


def _persist_baby(engine) -> UUID:
    user_id = uuid4()
    baby_id = uuid4()
    with Session(engine) as session:
        session.add_all([User(id=user_id), Baby(id=baby_id, user_id=user_id)])
        session.commit()
    return baby_id


def test_invalid_relationship_and_event_constraints_are_rejected() -> None:
    engine = create_database_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    baby_id = _persist_baby(engine)

    invalid_events = (
        Event(
            baby_id=baby_id,
            event_type=EventType.SLEEP,
            start_time=NOW,
            end_time=NOW.replace(hour=2),
        ),
        Event(
            baby_id=baby_id,
            event_type=EventType.SLEEP,
            start_time=NOW,
            duration_seconds=-1,
        ),
        Event(
            baby_id=baby_id,
            event_type=EventType.SLEEP,
            start_time=NOW,
            feed_amount_ml=Decimal("10.00"),
        ),
        Event(
            baby_id=uuid4(),
            event_type=EventType.WAKE,
            start_time=NOW,
        ),
    )
    for invalid_event in invalid_events:
        with Session(engine) as session:
            session.add(invalid_event)
            with pytest.raises(IntegrityError):
                session.commit()


def test_prediction_summary_and_audio_constraints_are_rejected() -> None:
    engine = create_database_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    baby_id = _persist_baby(engine)

    invalid_prediction = Prediction(
        baby_id=baby_id,
        prediction_timestamp=NOW,
        expected_sleep_minutes=90,
        wake_probability_within_60m=Decimal("1.5000"),
        baseline_expected_sleep_minutes=80,
        model_version="baseline-v1",
        feature_version="features-v1",
    )
    with Session(engine) as session:
        session.add(invalid_prediction)
        with pytest.raises(IntegrityError):
            session.commit()

    with Session(engine) as session:
        prediction = Prediction(
            baby_id=baby_id,
            prediction_timestamp=NOW,
            expected_sleep_minutes=90,
            wake_probability_within_60m=Decimal("0.5000"),
            baseline_expected_sleep_minutes=80,
            model_version="baseline-v1",
            feature_version="features-v1",
        )
        session.add(prediction)
        session.flush()
        session.add(
            Summary(
                prediction_id=prediction.id,
                summary_text="",
                provider_version="summary-v1",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()

    with Session(engine) as session:
        prediction = Prediction(
            baby_id=baby_id,
            prediction_timestamp=NOW,
            expected_sleep_minutes=90,
            wake_probability_within_60m=Decimal("0.5000"),
            baseline_expected_sleep_minutes=80,
            model_version="baseline-v1",
            feature_version="features-v1",
        )
        summary = Summary(
            prediction=prediction,
            summary_text="A valid synthetic summary.",
            provider_version="summary-v1",
        )
        session.add(summary)
        session.flush()
        session.add(
            Audio(
                summary_id=summary.id,
                provider="synthetic",
                provider_version="tts-v1",
                storage_key="synthetic/audio/invalid.ogg",
                content_type="audio/ogg",
                byte_size=0,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_database_indexes_cover_owner_and_prediction_queries() -> None:
    engine = create_database_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    inspector = inspect(engine)

    assert {
        index["name"] for index in inspector.get_indexes("babies")
    } == {"ix_babies_user_created_at"}
    assert {
        index["name"] for index in inspector.get_indexes("events")
    } == {"ix_events_baby_start", "ix_events_baby_type_start"}
    assert {
        index["name"] for index in inspector.get_indexes("predictions")
    } == {"ix_predictions_baby_timestamp"}
    assert {
        index["name"] for index in inspector.get_indexes("summaries")
    } == {"ix_summaries_prediction_created_at"}
    assert {
        index["name"] for index in inspector.get_indexes("audio")
    } == {"ix_audio_summary_created_at", "ix_audio_expires_at"}
