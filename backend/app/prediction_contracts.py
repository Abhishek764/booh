"""Private, immutable pipeline projections and explicit public API schemas."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ml.features import HistoryEvent
from ml.prediction.contracts import (
    BASELINE_VERSION,
    PREDICTION_FEATURE_VERSION,
    TABPFN_VERSION,
    PredictionMetadata,
    PredictionResult,
    finite_number,
    utc_time,
)

FALLBACK_REASONS = frozenset({
    "model_unavailable", "model_not_validated", "model_scope_mismatch",
    "model_from_future", "stale_model", "missing_features",
    "outside_model_support", "invalid_model_output",
})


class PredictionAPIError(RuntimeError):
    def __init__(self, code: str, status_code: int = 503) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True, slots=True, repr=False)
class PredictionContext:
    baby_id: UUID
    timezone_name: str
    date_of_birth: date | None
    history: tuple[HistoryEvent, ...]
    revision: str


@dataclass(frozen=True, slots=True, repr=False)
class PredictionRecord:
    id: UUID
    baby_id: UUID
    numerical: PredictionResult
    summary: str
    summary_used_fallback: bool


def validated_numerical(value: PredictionResult, *, as_of: datetime) -> PredictionResult:
    """Revalidate final output and retain only reviewed metadata before writes."""

    if type(value) is not PredictionResult or type(value.metadata) is not PredictionMetadata:
        raise PredictionAPIError("prediction_unavailable")
    value.__post_init__()
    metadata = value.metadata
    if (
        utc_time(metadata.as_of_utc) != utc_time(as_of)
        or metadata.feature_version != PREDICTION_FEATURE_VERSION
        or metadata.baseline_version != BASELINE_VERSION
        or type(metadata.baseline_sample_count) is not int
        or not 3 <= metadata.baseline_sample_count <= 10000
        or metadata.fallback_reason is not None and metadata.fallback_reason not in FALLBACK_REASONS
        or value.model_version not in {BASELINE_VERSION, TABPFN_VERSION}
        or (value.model_version == BASELINE_VERSION) != (metadata.fallback_reason is not None)
        or value.model_version == BASELINE_VERSION and value.expected_sleep_minutes != value.baseline_minutes
    ):
        raise PredictionAPIError("prediction_unavailable")
    finite_number(metadata.elapsed_sleep_minutes, 0, 10080, code="invalid_model_output")
    return PredictionResult(
        value.expected_sleep_minutes, float(value.wake_probability_60m), value.baseline_minutes,
        value.model_version, PredictionMetadata(
            utc_time(as_of), PREDICTION_FEATURE_VERSION, BASELINE_VERSION,
            metadata.baseline_sample_count, float(metadata.elapsed_sleep_minutes), metadata.fallback_reason,
        ),
    )


class PredictRequest(BaseModel):
    """All prediction context comes from server time and the owned baby's history."""

    model_config = ConfigDict(extra="forbid")


class PredictionListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=10000)


class PredictionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    baby_id: UUID
    prediction_timestamp: datetime
    expected_sleep_minutes: int = Field(ge=0, le=10080)
    wake_probability_60m: float = Field(ge=0, le=1, allow_inf_nan=False)
    baseline_minutes: int = Field(ge=0, le=10080)
    model_version: str = Field(max_length=128)
    feature_version: Literal["sleep-remaining-v1"]
    baseline_version: Literal["baseline-7d-v1"]
    used_baseline: bool
    summary: str = Field(min_length=1, max_length=300)
    summary_used_fallback: bool
