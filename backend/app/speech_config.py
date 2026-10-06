"""Operator-owned configuration for bounded text-to-speech."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from backend.app.config import ConfigurationError

_ENVIRONMENTS = {"development", "test", "staging", "production", "prod"}
_VOICE_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_MODEL_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def _flag(name: str, value: str) -> bool:
    if value not in {"", "0", "1"}:
        raise ConfigurationError("invalid_tts_configuration")
    return value == "1"


@dataclass(frozen=True, slots=True, repr=False)
class ElevenLabsSettings:
    """Fixed-host provider settings; credentials are excluded from repr."""

    app_env: str = "development"
    api_key: str = field(default="", repr=False)
    voice_id: str = ""
    model: str = "eleven_multilingual_v2"
    timeout_seconds: float = 10.0
    cache_enabled: bool = False
    cache_ttl_seconds: int = 3600
    disabled: bool = False

    def __post_init__(self) -> None:
        if self.app_env not in _ENVIRONMENTS:
            raise ConfigurationError("invalid_tts_configuration")
        if type(self.disabled) is not bool:
            raise ConfigurationError("invalid_tts_configuration")
        if self.disabled:
            return
        if (
            type(self.api_key) is not str
            or not 1 <= len(self.api_key) <= 4096
            or any(not 33 <= ord(char) <= 126 for char in self.api_key)
            or _VOICE_ID.fullmatch(self.voice_id) is None
            or _MODEL_ID.fullmatch(self.model) is None
            or type(self.timeout_seconds) not in {int, float}
            or not 0.1 <= self.timeout_seconds <= 30
            or type(self.cache_enabled) is not bool
            or type(self.cache_ttl_seconds) is not int
            or not 60 <= self.cache_ttl_seconds <= 86400
        ):
            raise ConfigurationError("invalid_tts_configuration")

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        app_env: str | None = None,
    ) -> "ElevenLabsSettings":
        values = os.environ if environ is None else environ
        disabled = _flag("TTS_DISABLED", values.get("TTS_DISABLED", ""))
        selected_env = app_env or values.get("APP_ENV") or "development"
        if disabled:
            return cls(app_env=selected_env, disabled=True)
        try:
            timeout = float(values.get("TTS_TIMEOUT_SECONDS") or "10")
            cache_ttl = int(values.get("TTS_CACHE_TTL_SECONDS") or "3600")
        except (TypeError, ValueError):
            raise ConfigurationError("invalid_tts_configuration") from None
        return cls(
            app_env=selected_env,
            api_key=values.get("ELEVENLABS_API_KEY") or "",
            voice_id=values.get("ELEVENLABS_VOICE_ID") or "",
            model=values.get("ELEVENLABS_MODEL") or "eleven_multilingual_v2",
            timeout_seconds=timeout,
            cache_enabled=_flag("TTS_CACHE_ENABLED", values.get("TTS_CACHE_ENABLED", "")),
            cache_ttl_seconds=cache_ttl,
        )


@dataclass(frozen=True, slots=True, repr=False)
class AudioStorageSettings:
    """External audio root and bounded reference retention."""

    root: str
    retention_seconds: int = 86400

    def __post_init__(self) -> None:
        try:
            path = Path(self.root)
        except (TypeError, ValueError):
            raise ConfigurationError("invalid_audio_storage_configuration") from None
        if (
            type(self.root) is not str
            or not path.is_absolute()
            or len(self.root) > 4096
            or any(char in self.root for char in "\r\n\x00")
            or type(self.retention_seconds) is not int
            or not 300 <= self.retention_seconds <= 604800
        ):
            raise ConfigurationError("invalid_audio_storage_configuration")

    @classmethod
    def from_environment(
        cls, environ: Mapping[str, str] | None = None
    ) -> "AudioStorageSettings":
        values = os.environ if environ is None else environ
        try:
            retention = int(values.get("AUDIO_RETENTION_SECONDS") or "86400")
        except (TypeError, ValueError):
            raise ConfigurationError("invalid_audio_storage_configuration") from None
        return cls(values.get("AUDIO_STORAGE_ROOT") or "", retention)


__all__ = ["AudioStorageSettings", "ElevenLabsSettings"]
