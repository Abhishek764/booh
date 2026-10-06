"""Bounded speech orchestration with disabled mode and optional short-lived cache."""

from __future__ import annotations

import asyncio
import hashlib
import time
from collections import OrderedDict
from dataclasses import dataclass
from threading import BoundedSemaphore, Lock

from backend.app.speech_config import ElevenLabsSettings
from backend.app.speech_contracts import (
    MAX_SPEECH_TEXT_CHARS,
    SpeechAudio,
    SpeechError,
    SpeechProvider,
)


@dataclass(frozen=True, slots=True)
class _CacheEntry:
    expires_at: float
    audio: SpeechAudio


class SpeechService:
    """Owns TTS policy; provider details remain behind an injected adapter."""

    def __init__(
        self,
        provider: SpeechProvider | None = None,
        *,
        settings: ElevenLabsSettings | None = None,
        disabled_reason: str = "tts_disabled",
    ) -> None:
        self._provider = provider
        self._settings = settings
        self._disabled_reason = disabled_reason
        self._slots = BoundedSemaphore(2)
        self._cache: OrderedDict[str, _CacheEntry] = OrderedDict()
        self._cache_lock = Lock()

    @property
    def disabled(self) -> bool:
        return self._provider is None

    def _cache_key(self, text: str) -> str:
        version = self._provider.provider_version if self._provider is not None else "disabled"
        return hashlib.sha256(f"{version}\0{text}".encode("utf-8")).hexdigest()

    def _cached(self, key: str, now: float) -> SpeechAudio | None:
        with self._cache_lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            if entry.expires_at <= now:
                del self._cache[key]
                return None
            self._cache.move_to_end(key)
            return entry.audio

    def _store(self, key: str, audio: SpeechAudio, now: float) -> None:
        if self._settings is None or not self._settings.cache_enabled:
            return
        with self._cache_lock:
            self._cache[key] = _CacheEntry(
                now + self._settings.cache_ttl_seconds, audio
            )
            self._cache.move_to_end(key)
            while len(self._cache) > 128:
                self._cache.popitem(last=False)

    async def synthesize(self, text: str) -> SpeechAudio | None:
        """Return audio, or ``None`` when TTS is deliberately disabled."""
        if (
            type(text) is not str
            or not 1 <= len(text) <= MAX_SPEECH_TEXT_CHARS
            or not text.isascii()
            or any(ord(char) < 32 and char not in "\t" for char in text)
        ):
            raise SpeechError("invalid_speech_input")
        if self._provider is None:
            return None
        if not self._slots.acquire(blocking=False):
            raise SpeechError("tts_busy")
        try:
            key = self._cache_key(text)
            now = time.monotonic()
            if self._settings is not None and self._settings.cache_enabled:
                cached = self._cached(key, now)
                if cached is not None:
                    return cached
            timeout = self._settings.timeout_seconds if self._settings is not None else 10.0
            try:
                async with asyncio.timeout(timeout):
                    audio = await self._provider.synthesize(text)
            except TimeoutError:
                raise SpeechError("tts_timeout") from None
            except SpeechError:
                raise
            except Exception:
                raise SpeechError("tts_unavailable") from None
            if not isinstance(audio, SpeechAudio):
                raise SpeechError("invalid_speech_output")
            self._store(key, audio, time.monotonic())
            return audio
        finally:
            self._slots.release()


def build_speech_service(
    environ: dict[str, str] | None = None, *, app_env: str | None = None
) -> SpeechService:
    """Build disabled mode without requiring a key, voice, or network."""
    from backend.app.providers.elevenlabs import ElevenLabsProvider

    settings = ElevenLabsSettings.from_environment(environ, app_env=app_env)
    if settings.disabled:
        return SpeechService(settings=settings)
    return SpeechService(ElevenLabsProvider(settings), settings=settings)


__all__ = ["SpeechService", "build_speech_service"]
