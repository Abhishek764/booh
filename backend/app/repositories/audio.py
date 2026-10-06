"""Owner-joined persistence for summaries and external audio references."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.audio_contracts import AudioRecord, AudioSource
from backend.app.database import session_scope
from backend.app.models import Audio, Baby, Prediction, Summary
from backend.app.speech_contracts import SpeechAudio
from backend.app.summary_contracts import (
    OutputValidator,
    SummaryInput,
    deterministic_summary,
)


class OwnedAudioRepository(Protocol):
    def load_source(
        self, *, owner_id: UUID, baby_id: UUID, prediction_id: UUID
    ) -> AudioSource | None: ...

    def latest_owned(
        self, *, owner_id: UUID, baby_id: UUID, prediction_id: UUID, now: datetime
    ) -> AudioRecord | None: ...

    def create_owned(
        self,
        *,
        owner_id: UUID,
        source: AudioSource,
        audio: SpeechAudio,
        storage_key: str,
        expires_at: datetime,
    ) -> AudioRecord | None: ...

    def delete_owned_latest(
        self, *, owner_id: UUID, baby_id: UUID, prediction_id: UUID, now: datetime
    ) -> AudioRecord | None: ...

    def delete_owned_record(
        self, *, owner_id: UUID, audio_id: UUID, storage_key: str
    ) -> bool: ...

    def delete_expired_record(self, *, audio_id: UUID, storage_key: str) -> bool: ...

    def expired(self, *, now: datetime, limit: int) -> list[AudioRecord]: ...


def _record(audio: Audio, *, baby_id: UUID, prediction_id: UUID) -> AudioRecord:
    return AudioRecord(
        id=audio.id,
        baby_id=baby_id,
        prediction_id=prediction_id,
        summary_id=audio.summary_id,
        provider=audio.provider,
        provider_version=audio.provider_version,
        storage_key=audio.storage_key,
        content_type=audio.content_type,
        byte_size=audio.byte_size,
        duration_ms=audio.duration_ms,
        expires_at=audio.expires_at,
        created_at=audio.created_at,
    )


def _source(session: Session, *, owner_id: UUID, baby_id: UUID, prediction_id: UUID) -> AudioSource | None:
    prediction = session.scalar(
        select(Prediction)
        .join(Baby, Prediction.baby_id == Baby.id)
        .where(
            Prediction.id == prediction_id,
            Baby.id == baby_id,
            Baby.user_id == owner_id,
        )
    )
    if prediction is None:
        return None
    summary = session.scalar(
        select(Summary)
        .where(Summary.prediction_id == prediction.id)
        .order_by(Summary.created_at.desc(), Summary.id.desc())
        .limit(1)
    )
    if summary is None:
        return None
    try:
        summary_input = SummaryInput(
            int(prediction.expected_sleep_minutes),
            float(prediction.wake_probability_within_60m),
            int(prediction.baseline_expected_sleep_minutes),
        )
    except (TypeError, ValueError):
        return None
    try:
        text = OutputValidator().validate_text(summary.summary_text, summary_input)
    except ValueError:
        # Stored text is untrusted. A validated numerical result still has a
        # safe local sentence that can be spoken without echoing tampered text.
        text = deterministic_summary(summary_input)
    return AudioSource(baby_id, prediction.id, summary.id, summary_input, text)


class SqlAlchemyAudioRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def load_source(
        self, *, owner_id: UUID, baby_id: UUID, prediction_id: UUID
    ) -> AudioSource | None:
        with session_scope(self._session_factory) as session:
            return _source(
                session,
                owner_id=owner_id,
                baby_id=baby_id,
                prediction_id=prediction_id,
            )

    def latest_owned(
        self, *, owner_id: UUID, baby_id: UUID, prediction_id: UUID, now: datetime
    ) -> AudioRecord | None:
        with session_scope(self._session_factory) as session:
            row = session.execute(
                select(Audio, Baby.id, Prediction.id)
                .join(Summary, Audio.summary_id == Summary.id)
                .join(Prediction, Summary.prediction_id == Prediction.id)
                .join(Baby, Prediction.baby_id == Baby.id)
                .where(
                    Baby.user_id == owner_id,
                    Baby.id == baby_id,
                    Prediction.id == prediction_id,
                    or_(Audio.expires_at.is_(None), Audio.expires_at > now),
                )
                .order_by(Audio.created_at.desc(), Audio.id.desc())
                .limit(1)
            ).first()
            if row is None:
                return None
            audio, selected_baby, selected_prediction = row
            return _record(audio, baby_id=selected_baby, prediction_id=selected_prediction)

    def create_owned(
        self,
        *,
        owner_id: UUID,
        source: AudioSource,
        audio: SpeechAudio,
        storage_key: str,
        expires_at: datetime,
    ) -> AudioRecord | None:
        with session_scope(self._session_factory) as session:
            current = _source(
                session,
                owner_id=owner_id,
                baby_id=source.baby_id,
                prediction_id=source.prediction_id,
            )
            if current is None or current.summary_id != source.summary_id:
                return None
            selected_summary = session.scalar(
                select(Summary)
                .join(Prediction, Summary.prediction_id == Prediction.id)
                .join(Baby, Prediction.baby_id == Baby.id)
                .where(
                    Summary.id == source.summary_id,
                    Prediction.id == source.prediction_id,
                    Baby.id == source.baby_id,
                    Baby.user_id == owner_id,
                )
                .with_for_update()
            )
            if selected_summary is None:
                return None
            record = Audio(
                id=uuid4(),
                summary_id=source.summary_id,
                provider=audio.provider,
                provider_version=audio.provider_version,
                storage_key=storage_key,
                content_type=audio.content_type,
                byte_size=len(audio.content),
                duration_ms=None,
                expires_at=expires_at,
            )
            session.add(record)
            session.flush()
            return _record(
                record, baby_id=source.baby_id, prediction_id=source.prediction_id
            )

    def delete_owned_latest(
        self, *, owner_id: UUID, baby_id: UUID, prediction_id: UUID, now: datetime
    ) -> AudioRecord | None:
        with session_scope(self._session_factory) as session:
            row = session.execute(
                select(Audio, Baby.id, Prediction.id)
                .join(Summary, Audio.summary_id == Summary.id)
                .join(Prediction, Summary.prediction_id == Prediction.id)
                .join(Baby, Prediction.baby_id == Baby.id)
                .where(
                    Baby.user_id == owner_id,
                    Baby.id == baby_id,
                    Prediction.id == prediction_id,
                    or_(Audio.expires_at.is_(None), Audio.expires_at > now),
                )
                .order_by(Audio.created_at.desc(), Audio.id.desc())
                .limit(1)
            ).first()
            if row is None:
                return None
            audio, selected_baby, selected_prediction = row
            result = _record(audio, baby_id=selected_baby, prediction_id=selected_prediction)
            session.delete(audio)
            return result

    def delete_owned_record(
        self, *, owner_id: UUID, audio_id: UUID, storage_key: str
    ) -> bool:
        with session_scope(self._session_factory) as session:
            audio = session.scalar(
                select(Audio)
                .join(Summary, Audio.summary_id == Summary.id)
                .join(Prediction, Summary.prediction_id == Prediction.id)
                .join(Baby, Prediction.baby_id == Baby.id)
                .where(
                    Audio.id == audio_id,
                    Audio.storage_key == storage_key,
                    Baby.user_id == owner_id,
                )
            )
            if audio is None:
                return False
            session.delete(audio)
            return True

    def delete_expired_record(self, *, audio_id: UUID, storage_key: str) -> bool:
        with session_scope(self._session_factory) as session:
            audio = session.scalar(
                select(Audio).where(
                    Audio.id == audio_id, Audio.storage_key == storage_key
                )
            )
            if audio is None:
                return False
            session.delete(audio)
            return True

    def expired(self, *, now: datetime, limit: int) -> list[AudioRecord]:
        if type(limit) is not int or not 1 <= limit <= 1000:
            return []
        with session_scope(self._session_factory) as session:
            rows = session.execute(
                select(Audio, Baby.id, Prediction.id)
                .join(Summary, Audio.summary_id == Summary.id)
                .join(Prediction, Summary.prediction_id == Prediction.id)
                .join(Baby, Prediction.baby_id == Baby.id)
                .where(Audio.expires_at.is_not(None), Audio.expires_at <= now)
                .order_by(Audio.expires_at.asc(), Audio.id.asc())
                .limit(limit)
            ).all()
            return [
                _record(audio, baby_id=baby_id, prediction_id=prediction_id)
                for audio, baby_id, prediction_id in rows
            ]


__all__ = ["OwnedAudioRepository", "SqlAlchemyAudioRepository"]
