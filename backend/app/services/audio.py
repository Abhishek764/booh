"""Authorized speech generation, external storage, and retention workflow."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from threading import BoundedSemaphore
from typing import Callable
from uuid import UUID, uuid4

from backend.app.audio_contracts import AudioAPIError, AudioRecord, AudioSource
from backend.app.audio_storage import AudioStorage
from backend.app.repositories.audio import OwnedAudioRepository
from backend.app.services.auth import Principal
from backend.app.services.speech import SpeechService
from backend.app.speech_contracts import (
    AUDIO_CONTENT_TYPE,
    MAX_AUDIO_BYTES,
    SpeechError,
)

AUDIO_TIMEOUT_SECONDS = 20.0
_WORK_SLOTS = BoundedSemaphore(2)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class AudioService:
    """Keep authentication, persistence, provider calls, and storage separate."""

    def __init__(
        self,
        repository: OwnedAudioRepository,
        *,
        speech: SpeechService,
        storage: AudioStorage | None,
        retention_seconds: int = 86400,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._repository = repository
        self._speech = speech
        self._storage = storage
        self._retention_seconds = retention_seconds
        self._clock = clock

    async def authorize(
        self, principal: Principal, *, baby_id: UUID, prediction_id: UUID
    ) -> AudioSource:
        try:
            async with asyncio.timeout(AUDIO_TIMEOUT_SECONDS):
                source = await asyncio.to_thread(
                    self._repository.load_source,
                    owner_id=principal.user_id,
                    baby_id=baby_id,
                    prediction_id=prediction_id,
                )
        except TimeoutError:
            raise AudioAPIError("audio_timeout", 503) from None
        except Exception:
            raise AudioAPIError("audio_unavailable", 503) from None
        if source is None or source.baby_id != baby_id or source.prediction_id != prediction_id:
            raise AudioAPIError("resource_not_found", 404)
        return source

    async def synthesize(
        self, principal: Principal, *, baby_id: UUID, prediction_id: UUID
    ) -> AudioRecord:
        if not _WORK_SLOTS.acquire(blocking=False):
            raise AudioAPIError("audio_busy", 429)
        storage_key: str | None = None
        try:
            async with asyncio.timeout(AUDIO_TIMEOUT_SECONDS):
                source = await self.authorize(
                    principal, baby_id=baby_id, prediction_id=prediction_id
                )
                if self._storage is None:
                    raise AudioAPIError("audio_unavailable", 503)
                try:
                    spoken = await self._speech.synthesize(source.text)
                except SpeechError as exc:
                    if exc.code in {"tts_busy", "tts_provider_busy"}:
                        raise AudioAPIError("audio_busy", 429) from None
                    raise AudioAPIError("audio_unavailable", 503) from None
                if spoken is None:
                    raise AudioAPIError("audio_unavailable", 503)
                storage_key = f"audio/{uuid4().hex}.mp3"
                try:
                    await asyncio.to_thread(
                        self._storage.put,
                        storage_key,
                        spoken.content,
                        spoken.content_type,
                    )
                except Exception:
                    raise AudioAPIError("audio_unavailable", 503) from None
                expires_at = _utc(self._clock()) + timedelta(seconds=self._retention_seconds)
                try:
                    record = await asyncio.to_thread(
                        self._repository.create_owned,
                        owner_id=principal.user_id,
                        source=source,
                        audio=spoken,
                        storage_key=storage_key,
                        expires_at=expires_at,
                    )
                except Exception:
                    raise AudioAPIError("audio_unavailable", 503) from None
                if record is None:
                    raise AudioAPIError("resource_not_found", 404)
                storage_key = None
                return record
        except AudioAPIError:
            raise
        except TimeoutError:
            raise AudioAPIError("audio_timeout", 503) from None
        except Exception:
            raise AudioAPIError("audio_unavailable", 503) from None
        finally:
            if storage_key is not None and self._storage is not None:
                try:
                    await asyncio.to_thread(self._storage.delete, storage_key)
                except Exception:
                    pass
            _WORK_SLOTS.release()

    async def latest(
        self, principal: Principal, *, baby_id: UUID, prediction_id: UUID
    ) -> AudioRecord:
        try:
            async with asyncio.timeout(AUDIO_TIMEOUT_SECONDS):
                record = await asyncio.to_thread(
                    self._repository.latest_owned,
                    owner_id=principal.user_id,
                    baby_id=baby_id,
                    prediction_id=prediction_id,
                    now=_utc(self._clock()),
                )
        except TimeoutError:
            raise AudioAPIError("audio_timeout", 503) from None
        except Exception:
            raise AudioAPIError("audio_unavailable", 503) from None
        if record is None:
            raise AudioAPIError("resource_not_found", 404)
        if (
            record.content_type != AUDIO_CONTENT_TYPE
            or type(record.byte_size) is not int
            or not 1 <= record.byte_size <= MAX_AUDIO_BYTES
        ):
            raise AudioAPIError("audio_unavailable", 503)
        return record

    async def content(
        self, principal: Principal, *, baby_id: UUID, prediction_id: UUID
    ) -> tuple[AudioRecord, bytes]:
        record = await self.latest(principal, baby_id=baby_id, prediction_id=prediction_id)
        if self._storage is None:
            raise AudioAPIError("audio_unavailable", 503)
        try:
            content = await asyncio.to_thread(self._storage.read, record.storage_key)
        except Exception:
            raise AudioAPIError("audio_unavailable", 503) from None
        if len(content) != record.byte_size:
            raise AudioAPIError("audio_unavailable", 503)
        return record, content

    async def delete(
        self, principal: Principal, *, baby_id: UUID, prediction_id: UUID
    ) -> None:
        record = await self.latest(principal, baby_id=baby_id, prediction_id=prediction_id)
        if self._storage is None:
            raise AudioAPIError("audio_unavailable", 503)
        try:
            await asyncio.to_thread(self._storage.delete, record.storage_key)
            deleted = await asyncio.to_thread(
                self._repository.delete_owned_record,
                owner_id=principal.user_id,
                audio_id=record.id,
                storage_key=record.storage_key,
            )
        except Exception:
            raise AudioAPIError("audio_unavailable", 503) from None
        if not deleted:
            raise AudioAPIError("resource_not_found", 404)

    def purge_expired(self, *, limit: int = 100) -> int:
        """Maintenance hook: delete external bytes before their DB references."""
        if self._storage is None:
            return 0
        now = _utc(self._clock())
        removed = 0
        for record in self._repository.expired(now=now, limit=limit):
            try:
                self._storage.delete(record.storage_key)
                if self._repository.delete_expired_record(
                    audio_id=record.id, storage_key=record.storage_key
                ):
                    removed += 1
            except Exception:
                continue
        return removed


__all__ = ["AUDIO_TIMEOUT_SECONDS", "AudioService"]
