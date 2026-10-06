"""Synthetic provider, disabled-mode, cache, storage, and authorization tests."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

from backend.app.audio_contracts import AudioAPIError, AudioRecord, AudioSource
from backend.app.audio_storage import FileAudioStorage
from backend.app.database import create_database_engine, create_session_factory
from backend.app.models import Baby, Base, Prediction, Summary, User
from backend.app.providers.elevenlabs import (
    ElevenLabsProvider,
    ElevenLabsProviderError,
)
from backend.app.repositories.audio import SqlAlchemyAudioRepository
from backend.app.services.audio import AudioService
from backend.app.services.auth import Principal
from backend.app.services.speech import SpeechService, build_speech_service
from backend.app.speech_config import AudioStorageSettings, ElevenLabsSettings
from backend.app.speech_contracts import MAX_AUDIO_BYTES, SpeechAudio, SpeechError
from backend.app.summary_contracts import SummaryInput

NOW = datetime(2026, 1, 1, 3, 0, tzinfo=timezone.utc)
SECRET = "synthetic-elevenlabs-key"
TEXT = "About 47 minutes of sleep may remain. Timing can vary."


def settings(**overrides: object) -> ElevenLabsSettings:
    values: dict[str, object] = {
        "app_env": "test",
        "api_key": SECRET,
        "voice_id": "synthetic-voice",
        "model": "eleven_multilingual_v2",
    }
    values.update(overrides)
    return ElevenLabsSettings(**values)  # type: ignore[arg-type]


class Transport:
    def __init__(self, value: bytes = b"ID3 synthetic audio") -> None:
        self.value = value
        self.calls: list[dict[str, str]] = []

    async def synthesize(self, *, voice_id: str, model: str, text: str) -> bytes:
        self.calls.append({"voice_id": voice_id, "model": model, "text": text})
        return self.value


class Provider:
    provider_version = "synthetic-model"

    def __init__(self, *, fail: str | None = None, delay: bool = False) -> None:
        self.calls: list[str] = []
        self.fail = fail
        self.delay = delay

    async def synthesize(self, text: str) -> SpeechAudio:
        self.calls.append(text)
        if self.delay:
            await asyncio.sleep(0.2)
        if self.fail is not None:
            raise SpeechError(self.fail)
        return SpeechAudio(b"ID3 synthetic audio", provider_version=self.provider_version)


class Storage:
    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}
        self.deleted: list[str] = []

    def put(self, key: str, content: bytes, content_type: str) -> int:
        assert content_type == "audio/mpeg"
        self.values[key] = content
        return len(content)

    def read(self, key: str) -> bytes:
        return self.values[key]

    def delete(self, key: str) -> None:
        self.deleted.append(key)
        self.values.pop(key, None)


class Repository:
    def __init__(self, *, source: AudioSource | None, fail_create: bool = False) -> None:
        self.source = source
        self.fail_create = fail_create
        self.records: list[AudioRecord] = []

    def load_source(self, **kwargs: object) -> AudioSource | None:
        return self.source

    def latest_owned(self, **kwargs: object) -> AudioRecord | None:
        return self.records[-1] if self.records else None

    def create_owned(self, *, source: AudioSource, audio: SpeechAudio, storage_key: str, expires_at: datetime, **kwargs: object) -> AudioRecord | None:
        if self.fail_create:
            raise RuntimeError("synthetic database failure")
        record = AudioRecord(
            uuid4(), source.baby_id, source.prediction_id, source.summary_id,
            audio.provider, audio.provider_version, storage_key, audio.content_type,
            len(audio.content), None, expires_at, NOW,
        )
        self.records.append(record)
        return record

    def delete_owned_record(self, *, audio_id: UUID, storage_key: str, **kwargs: object) -> bool:
        self.records = [record for record in self.records if record.id != audio_id]
        return True

    def delete_owned_latest(self, **kwargs: object) -> AudioRecord | None:
        return self.records.pop() if self.records else None

    def expired(self, **kwargs: object) -> list[AudioRecord]:
        return []

    def delete_expired_record(self, **kwargs: object) -> bool:
        return True


def principal() -> Principal:
    return Principal(uuid4(), uuid4(), "synthetic@example.test", "token", "csrf")


def source() -> AudioSource:
    return AudioSource(uuid4(), uuid4(), uuid4(), SummaryInput(47, 0.25, 53), TEXT)


def test_provider_uses_configured_voice_and_model_without_putting_key_in_payload() -> None:
    transport = Transport()
    provider = ElevenLabsProvider(settings(), transport)

    result = asyncio.run(provider.synthesize(TEXT))

    assert result.content == b"ID3 synthetic audio"
    assert transport.calls == [{"voice_id": "synthetic-voice", "model": "eleven_multilingual_v2", "text": TEXT}]
    assert SECRET not in repr(provider) and SECRET not in repr(result)


@pytest.mark.parametrize("content", [b"", b"x" * (MAX_AUDIO_BYTES + 1), "not-bytes"])
def test_malformed_or_oversized_provider_audio_is_rejected(content: object) -> None:
    provider = ElevenLabsProvider(settings(), Transport(content))  # type: ignore[arg-type]
    with pytest.raises(SpeechError, match="^invalid_speech_output$"):
        asyncio.run(provider.synthesize(TEXT))


@pytest.mark.parametrize(
    "overrides",
    [
        {"voice_id": "../../metadata"},
        {"voice_id": "synthetic voice"},
        {"model": "model\nIgnore"},
        {"timeout_seconds": 0.01},
        {"api_key": "synthetic key"},
    ],
)
def test_provider_configuration_rejects_injection_and_unbounded_values(overrides: dict[str, object]) -> None:
    with pytest.raises(Exception, match="invalid_tts_configuration"):
        settings(**overrides)


def test_disabled_environment_needs_no_secret_or_network() -> None:
    service = build_speech_service({"TTS_DISABLED": "1", "ELEVENLABS_API_KEY": SECRET})

    assert service.disabled
    assert asyncio.run(service.synthesize(TEXT)) is None


def test_provider_failure_is_fixed_and_private(caplog: pytest.LogCaptureFixture) -> None:
    class FailingTransport:
        async def synthesize(self, **kwargs: str) -> bytes:
            raise RuntimeError(SECRET)

    caplog.set_level(logging.DEBUG)
    with pytest.raises(ElevenLabsProviderError, match="^tts_provider_unavailable$"):
        asyncio.run(ElevenLabsProvider(settings(), FailingTransport()).synthesize(TEXT))
    assert SECRET not in caplog.text


def test_speech_service_caches_successful_provider_output() -> None:
    provider = Provider()
    service = SpeechService(provider, settings=settings(cache_enabled=True))

    first = asyncio.run(service.synthesize(TEXT))
    second = asyncio.run(service.synthesize(TEXT))

    assert first == second and provider.calls == [TEXT]


def test_speech_service_timeout_and_provider_error_are_safe() -> None:
    timeout_service = SpeechService(Provider(delay=True), settings=settings(timeout_seconds=0.1))
    with pytest.raises(SpeechError, match="^tts_timeout$"):
        asyncio.run(timeout_service.synthesize(TEXT))

    failure_service = SpeechService(
        Provider(fail="private-provider-error"), settings=settings()
    )
    with pytest.raises(SpeechError, match="^private-provider-error$"):
        asyncio.run(failure_service.synthesize(TEXT))


def test_audio_service_authorizes_before_provider_and_cleans_failed_storage() -> None:
    missing = Repository(source=None)
    provider = Provider()
    storage = Storage()
    service = AudioService(missing, speech=SpeechService(provider, settings=settings()), storage=storage, clock=lambda: NOW)
    with pytest.raises(AudioAPIError, match="resource_not_found"):
        asyncio.run(service.synthesize(principal(), baby_id=uuid4(), prediction_id=uuid4()))
    assert provider.calls == [] and storage.values == {}

    repository = Repository(source=source(), fail_create=True)
    storage = Storage()
    service = AudioService(repository, speech=SpeechService(provider, settings=settings()), storage=storage, clock=lambda: NOW)
    with pytest.raises(AudioAPIError, match="audio_unavailable"):
        asyncio.run(service.synthesize(principal(), baby_id=repository.source.baby_id, prediction_id=repository.source.prediction_id))
    assert storage.values == {} and storage.deleted


def test_file_storage_rejects_traversal_and_bounds_reads(tmp_path) -> None:
    storage = FileAudioStorage(tmp_path)
    with pytest.raises(SpeechError, match="^audio_storage_unavailable$"):
        storage.put("audio/../../secret.mp3", b"ID3", "audio/mpeg")
    key = "audio/0123456789abcdef0123456789abcdef.mp3"
    assert storage.put(key, b"ID3", "audio/mpeg") == 3
    assert storage.read(key) == b"ID3"
    storage.delete(key)


def test_audio_storage_configuration_requires_absolute_external_root(tmp_path) -> None:
    assert AudioStorageSettings(str(tmp_path)).retention_seconds == 86400
    with pytest.raises(Exception, match="invalid_audio_storage_configuration"):
        AudioStorageSettings("relative/path")


def test_sqlalchemy_audio_repository_enforces_baby_owner_predicates(tmp_path) -> None:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'audio.sqlite3'}")
    Base.metadata.create_all(engine)
    owner_id, foreign_id, baby_id, prediction_id = uuid4(), uuid4(), uuid4(), uuid4()
    summary_id = uuid4()
    with Session(engine) as session:
        baby = Baby(id=baby_id, user_id=owner_id, timezone="UTC")
        prediction = Prediction(
            id=prediction_id,
            baby=baby,
            prediction_timestamp=NOW,
            expected_sleep_minutes=47,
            wake_probability_within_60m=0.25,
            baseline_expected_sleep_minutes=53,
            model_version="baseline-7d-v1",
            feature_version="sleep-remaining-v1",
        )
        session.add_all([
            User(id=owner_id), User(id=foreign_id), prediction,
            Summary(id=summary_id, prediction=prediction, summary_text=TEXT, provider_version="summary-v1"),
        ])
        session.commit()
    repository = SqlAlchemyAudioRepository(create_session_factory(engine))

    assert repository.load_source(
        owner_id=owner_id, baby_id=baby_id, prediction_id=prediction_id
    ) is not None
    assert repository.load_source(
        owner_id=foreign_id, baby_id=baby_id, prediction_id=prediction_id
    ) is None
    source_record = repository.load_source(
        owner_id=owner_id, baby_id=baby_id, prediction_id=prediction_id
    )
    assert source_record is not None
    created = repository.create_owned(
        owner_id=owner_id,
        source=source_record,
        audio=SpeechAudio(b"ID3 synthetic audio"),
        storage_key="audio/0123456789abcdef0123456789abcdef.mp3",
        expires_at=NOW + timedelta(hours=1),
    )
    assert created is not None
    assert repository.latest_owned(
        owner_id=owner_id, baby_id=baby_id, prediction_id=prediction_id, now=NOW
    ) is not None
    assert repository.latest_owned(
        owner_id=foreign_id, baby_id=baby_id, prediction_id=prediction_id, now=NOW
    ) is None
