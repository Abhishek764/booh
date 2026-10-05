"""Bounded owner-scoped snapshots and two short prediction/summary transactions."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import datetime, timedelta, timezone
from typing import Protocol, cast
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.database import session_scope
from backend.app.models import Baby, Event, Prediction, Summary
from backend.app.prediction_contracts import (
    PredictionAPIError,
    PredictionContext,
    PredictionRecord,
    validated_numerical,
)
from backend.app.summary_contracts import (
    SUMMARY_VERSION,
    OutputValidator,
    SummaryInput,
    SummaryResult,
    deterministic_summary,
)
from ml.features import LOOKBACK, MAX_HISTORY_EVENTS, HistoryEvent
from ml.prediction.contracts import PredictionMetadata, PredictionResult


class OwnedPredictionRepository(Protocol):
    def owns_baby(self, *, owner_id: UUID, baby_id: UUID) -> bool: ...

    def load_context(self, *, owner_id: UUID, baby_id: UUID, as_of: datetime) -> PredictionContext | None: ...

    def locked_context(self, *, owner_id: UUID, baby_id: UUID, as_of: datetime) -> AbstractContextManager[PredictionContext | None]: ...

    def create_owned(self, *, owner_id: UUID, context: PredictionContext, numerical: PredictionResult) -> PredictionRecord | None: ...

    def finish_summary(self, *, owner_id: UUID, prediction_id: UUID, summary: SummaryResult) -> PredictionRecord | None: ...

    def list_owned(self, *, owner_id: UUID, baby_id: UUID, limit: int, offset: int) -> list[PredictionRecord] | None: ...


def _utc(value: datetime) -> datetime:
    # SQLite's isolated test driver strips tzinfo; persisted columns are UTC.
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _input(numerical: PredictionResult) -> SummaryInput:
    return SummaryInput(numerical.expected_sleep_minutes, numerical.wake_probability_60m, numerical.baseline_minutes)


def _record(prediction: Prediction, summary: Summary | None) -> PredictionRecord:
    metadata = prediction.feature_metadata or {}
    as_of = _utc(prediction.prediction_timestamp)
    numerical = validated_numerical(PredictionResult(
        prediction.expected_sleep_minutes, float(prediction.wake_probability_within_60m),
        prediction.baseline_expected_sleep_minutes, prediction.model_version,
        PredictionMetadata(
            as_of, prediction.feature_version, cast(str, metadata["baseline_version"]),
            cast(int, metadata["baseline_sample_count"]), cast(float, metadata["elapsed_sleep_minutes"]),
            cast(str | None, metadata["fallback_reason"]),
        ),
    ), as_of=as_of)
    text = deterministic_summary(_input(numerical))
    fallback = True
    if summary is not None:
        try:
            text = OutputValidator().validate_text(summary.summary_text, _input(numerical))
            fallback = metadata.get("summary_used_fallback") is not False
        except ValueError:
            pass  # Stored text is also untrusted. Never render unchecked historical prose.
    return PredictionRecord(prediction.id, prediction.baby_id, numerical, text, fallback)


class SqlAlchemyPredictionRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def owns_baby(self, *, owner_id: UUID, baby_id: UUID) -> bool:
        with session_scope(self._session_factory) as session:
            return session.scalar(select(Baby.id).where(Baby.id == baby_id, Baby.user_id == owner_id)) is not None

    def _context(self, session: Session, *, owner_id: UUID, baby_id: UUID, as_of: datetime, lock: bool = False) -> PredictionContext | None:
        query = select(Baby).where(Baby.id == baby_id, Baby.user_id == owner_id)
        baby = session.scalar(query.with_for_update() if lock else query)
        if baby is None:
            return None
        cutoff = as_of - LOOKBACK
        events = session.scalars(
            select(Event).join(Baby, Event.baby_id == Baby.id)
            .where(
                Baby.id == baby_id, Baby.user_id == owner_id, Event.start_time <= as_of,
                or_(
                    Event.start_time >= cutoff,
                    and_(Event.event_type == "sleep", Event.start_time >= cutoff - LOOKBACK,
                         or_(Event.end_time > cutoff, and_(Event.end_time.is_(None), Event.duration_seconds.is_not(None)))),
                ),
            )
            .order_by(Event.start_time.asc(), Event.id.asc()).limit(MAX_HISTORY_EVENTS + 1)
        ).all()
        if len(events) > MAX_HISTORY_EVENTS:
            raise PredictionAPIError("history_too_large", 413)
        history = tuple(HistoryEvent(
            event.baby_id, str(event.event_type), _utc(event.start_time),
            None if event.end_time is None else _utc(event.end_time), event.duration_seconds,
        ) for event in events)
        digest = hashlib.sha256()
        digest.update(json.dumps([baby.timezone, str(baby.date_of_birth)], separators=(",", ":")).encode())
        for event in events:
            digest.update(json.dumps([
                str(event.id), str(event.event_type), _utc(event.start_time).isoformat(),
                None if event.end_time is None else _utc(event.end_time).isoformat(), event.duration_seconds,
            ], separators=(",", ":")).encode())
        return PredictionContext(baby_id, baby.timezone, baby.date_of_birth, history, digest.hexdigest())

    def load_context(self, *, owner_id: UUID, baby_id: UUID, as_of: datetime) -> PredictionContext | None:
        with session_scope(self._session_factory) as session:
            return self._context(session, owner_id=owner_id, baby_id=baby_id, as_of=as_of)

    @contextmanager
    def locked_context(self, *, owner_id: UUID, baby_id: UUID, as_of: datetime) -> Iterator[PredictionContext | None]:
        # Artifact installation and authorized deletion share the baby row lock.
        # No fitting/evaluation/provider work is permitted inside this lease.
        with session_scope(self._session_factory) as session:
            yield self._context(session, owner_id=owner_id, baby_id=baby_id, as_of=as_of, lock=True)

    def create_owned(self, *, owner_id: UUID, context: PredictionContext, numerical: PredictionResult) -> PredictionRecord | None:
        numerical = validated_numerical(numerical, as_of=numerical.metadata.as_of_utc)
        with session_scope(self._session_factory) as session:
            current = self._context(session, owner_id=owner_id, baby_id=context.baby_id, as_of=numerical.metadata.as_of_utc, lock=True)
            if current is None:
                return None
            if current.revision != context.revision:
                raise PredictionAPIError("history_changed", 409)
            metadata = numerical.metadata
            prediction = Prediction(
                baby_id=context.baby_id, prediction_timestamp=metadata.as_of_utc,
                expected_sleep_minutes=numerical.expected_sleep_minutes,
                wake_probability_within_60m=numerical.wake_probability_60m,
                baseline_expected_sleep_minutes=numerical.baseline_minutes,
                model_version=numerical.model_version, feature_version=metadata.feature_version,
                feature_metadata={
                    "baseline_version": metadata.baseline_version, "baseline_sample_count": metadata.baseline_sample_count,
                    "elapsed_sleep_minutes": metadata.elapsed_sleep_minutes, "fallback_reason": metadata.fallback_reason,
                    "window_start_utc": (metadata.as_of_utc - timedelta(days=7)).isoformat(),
                    "summary_used_fallback": True, "summary_reason": "summary_pending", "summary_version": SUMMARY_VERSION,
                },
            )
            summary = Summary(prediction=prediction, summary_text=deterministic_summary(_input(numerical)), provider_version=SUMMARY_VERSION)
            session.add(summary)
            session.flush()
            record = _record(prediction, summary)
        return record  # Transaction, including commit, finishes before Gemma is called.

    def finish_summary(self, *, owner_id: UUID, prediction_id: UUID, summary: SummaryResult) -> PredictionRecord | None:
        with session_scope(self._session_factory) as session:
            owner = session.scalar(select(Baby.id).join(Prediction, Prediction.baby_id == Baby.id)
                                   .where(Prediction.id == prediction_id, Baby.user_id == owner_id)
                                   .with_for_update(of=Baby))
            if owner is None:
                return None
            prediction = session.scalar(select(Prediction).join(Baby, Prediction.baby_id == Baby.id)
                                        .where(Prediction.id == prediction_id, Baby.user_id == owner_id).with_for_update(of=Prediction))
            if prediction is None:
                return None
            existing = session.scalar(select(Summary).join(Prediction).join(Baby)
                                      .where(Summary.prediction_id == prediction_id, Baby.user_id == owner_id)
                                      .order_by(Summary.created_at.desc(), Summary.id.desc()).limit(1))
            record = _record(prediction, existing)
            text = OutputValidator().validate_text(summary.text, _input(record.numerical))
            if existing is None:
                existing = Summary(prediction=prediction, summary_text=text, provider_version=SUMMARY_VERSION)
                session.add(existing)
            else:
                existing.summary_text = text
            # Only summary fields and reviewed outcome metadata are writable here.
            metadata = dict(prediction.feature_metadata or {})
            metadata["summary_used_fallback"] = summary.used_fallback
            metadata["summary_reason"] = summary.reason
            metadata["summary_version"] = SUMMARY_VERSION
            metadata["summary_provider_model"] = summary.provider_model
            prediction.feature_metadata = metadata
            session.flush()
            result = _record(prediction, existing)
        return result

    def list_owned(self, *, owner_id: UUID, baby_id: UUID, limit: int, offset: int) -> list[PredictionRecord] | None:
        if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or not 0 <= offset <= 10000:
            raise PredictionAPIError("invalid_request", 422)
        with session_scope(self._session_factory) as session:
            if session.scalar(select(Baby.id).where(Baby.id == baby_id, Baby.user_id == owner_id)) is None:
                return None
            # Correlated bounded latest-summary join avoids unbounded ORM relationships/N+1.
            latest = (select(Summary.id).where(Summary.prediction_id == Prediction.id)
                      .order_by(Summary.created_at.desc(), Summary.id.desc()).limit(1).correlate(Prediction).scalar_subquery())
            rows = session.execute(select(Prediction, Summary).join(Baby, Prediction.baby_id == Baby.id)
                                   .outerjoin(Summary, Summary.id == latest)
                                   .where(Baby.id == baby_id, Baby.user_id == owner_id)
                                   .order_by(Prediction.prediction_timestamp.desc(), Prediction.id.desc())
                                   .limit(limit).offset(offset)).all()
            return [_record(prediction, summary) for prediction, summary in rows]
