"""Owner-scoped audio source and reference contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from backend.app.summary_contracts import SummaryInput


class AudioAPIError(RuntimeError):
    """Fixed error for the authenticated audio boundary."""

    def __init__(self, code: str, status_code: int = 503) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True, slots=True, repr=False)
class AudioSource:
    baby_id: UUID
    prediction_id: UUID
    summary_id: UUID
    summary_input: SummaryInput
    text: str


@dataclass(frozen=True, slots=True, repr=False)
class AudioRecord:
    id: UUID
    baby_id: UUID
    prediction_id: UUID
    summary_id: UUID
    provider: str
    provider_version: str
    storage_key: str = field(repr=False)
    content_type: str = "audio/mpeg"
    byte_size: int = 0
    duration_ms: int | None = None
    expires_at: datetime | None = None
    created_at: datetime | None = None


__all__ = ["AudioAPIError", "AudioRecord", "AudioSource"]
