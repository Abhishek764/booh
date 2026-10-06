"""Private contracts shared by speech services and provider adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

MAX_SPEECH_TEXT_CHARS = 300
MAX_AUDIO_BYTES = 2 * 1024 * 1024
AUDIO_CONTENT_TYPE = "audio/mpeg"


class SpeechError(RuntimeError):
    """A fixed, private speech failure that is safe to map at the API edge."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True, repr=False)
class SpeechAudio:
    """Bounded provider output; bytes never appear in automatic representations."""

    content: bytes = field(repr=False)
    content_type: str = AUDIO_CONTENT_TYPE
    provider: str = "elevenlabs"
    provider_version: str = "eleven_multilingual_v2"

    def __post_init__(self) -> None:
        if (
            type(self.content) is not bytes
            or not 1 <= len(self.content) <= MAX_AUDIO_BYTES
            or self.content_type != AUDIO_CONTENT_TYPE
            or type(self.provider) is not str
            or not 1 <= len(self.provider) <= 64
            or type(self.provider_version) is not str
            or not 1 <= len(self.provider_version) <= 128
        ):
            raise SpeechError("invalid_speech_output")


class SpeechProvider(Protocol):
    """Structural provider interface kept below the speech service."""

    @property
    def provider_version(self) -> str:  # pragma: no cover - protocol-like base
        ...

    async def synthesize(self, text: str) -> SpeechAudio:  # pragma: no cover
        ...


__all__ = [
    "AUDIO_CONTENT_TYPE",
    "MAX_AUDIO_BYTES",
    "MAX_SPEECH_TEXT_CHARS",
    "SpeechAudio",
    "SpeechError",
    "SpeechProvider",
]
