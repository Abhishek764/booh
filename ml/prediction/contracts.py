"""Finite, versioned numerical contracts; no text provider can supply predictions."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from numbers import Real
from typing import Protocol
from uuid import UUID

from ml.features import (
    FEATURE_DEFINITIONS,
    FEATURE_NAMES,
    FEATURE_VERSION,
    FeatureVector,
)

PREDICTION_FEATURE_VERSION = "sleep-remaining-v1"
PREDICTION_FEATURE_NAMES = (*FEATURE_NAMES, "elapsed_sleep_minutes")
MAX_SLEEP_MINUTES = 10080.0
BASELINE_VERSION = "baseline-7d-v1"
TABPFN_VERSION = "tabpfn-9.1.0-v2-remaining-v1"


class PredictionError(ValueError):
    """Fixed, private-data-free errors for inference and offline workflows."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def finite_number(value: object, lower: float, upper: float, *, code: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise PredictionError(code)
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError):
        raise PredictionError(code) from None
    if not math.isfinite(number) or not lower <= number <= upper:
        raise PredictionError(code)
    return number


def utc_time(value: datetime) -> datetime:
    try:
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise PredictionError("invalid_context")
        return value.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        raise PredictionError("invalid_context") from None


@dataclass(frozen=True, slots=True, repr=False)
class ModelInput:
    baby_id: UUID
    features: FeatureVector
    elapsed_sleep_minutes: float = 0.0

    def __post_init__(self) -> None:
        if not isinstance(self.baby_id, UUID) or not isinstance(self.features, FeatureVector):
            raise PredictionError("invalid_model_input")
        self.features.__post_init__()
        finite_number(self.elapsed_sleep_minutes, 0.0, MAX_SLEEP_MINUTES, code="invalid_model_input")
        utc_time(self.features.metadata.as_of_utc)

    @property
    def values(self) -> tuple[float, ...]:
        return (*self.features.values, float(self.elapsed_sleep_minutes))

    @property
    def as_of(self) -> datetime:
        return self.features.metadata.as_of_utc

    @property
    def suitable_for_tabpfn(self) -> bool:
        # Birth date is optional; all other timing features must be observed.
        missing = set(self.features.metadata.missing_features) - {"day_of_life"}
        return not missing and not self.features.metadata.insufficient_history


@dataclass(frozen=True, slots=True, repr=False)
class NumericalPrediction:
    expected_sleep_minutes: float
    wake_probability_60m: float

    def __post_init__(self) -> None:
        finite_number(self.expected_sleep_minutes, 0.0, MAX_SLEEP_MINUTES, code="invalid_model_output")
        finite_number(self.wake_probability_60m, 0.0, 1.0, code="invalid_model_output")


@dataclass(frozen=True, slots=True, repr=False)
class ModelProvenance:
    baby_id: UUID
    trained_until: datetime
    training_bouts: int
    model_version: str = TABPFN_VERSION
    feature_version: str = PREDICTION_FEATURE_VERSION
    base_feature_version: str = FEATURE_VERSION

    def __post_init__(self) -> None:
        if (
            not isinstance(self.baby_id, UUID) or type(self.training_bouts) is not int
            or not 20 <= self.training_bouts <= 64
            or self.model_version != TABPFN_VERSION
            or self.feature_version != PREDICTION_FEATURE_VERSION
            or self.base_feature_version != FEATURE_VERSION
        ):
            raise PredictionError("invalid_model_provenance")
        utc_time(self.trained_until)


class FittedNumericalModel(Protocol):
    @property
    def provenance(self) -> ModelProvenance: ...

    def predict(self, inputs: ModelInput) -> NumericalPrediction: ...


@dataclass(frozen=True, slots=True, repr=False)
class TrainingPayload:
    """Offline-only primitive numerical context for the local SDK worker."""

    provenance: ModelProvenance
    rows: tuple[tuple[float, ...], ...]
    remaining_minutes: tuple[float, ...]
    wake_labels: tuple[int, ...]

    def __post_init__(self) -> None:
        self.provenance.__post_init__()
        if (
            not isinstance(self.rows, tuple) or not 20 <= len(self.rows) <= 192
            or not isinstance(self.remaining_minutes, tuple) or not isinstance(self.wake_labels, tuple)
            or len(self.rows) != len(self.remaining_minutes) or len(self.rows) != len(self.wake_labels)
        ):
            raise PredictionError("invalid_training_data")
        for row, target, label in zip(self.rows, self.remaining_minutes, self.wake_labels, strict=True):
            if not isinstance(row, tuple) or len(row) != len(PREDICTION_FEATURE_NAMES):
                raise PredictionError("invalid_training_data")
            for definition, value in zip(FEATURE_DEFINITIONS, row[:-1], strict=True):
                if type(value) is not float:
                    raise PredictionError("invalid_training_data")
                if value == -1.0 and definition.missing_allowed:
                    continue
                finite_number(value, definition.minimum, definition.maximum, code="invalid_training_data")
                if definition.integer and not value.is_integer():
                    raise PredictionError("invalid_training_data")
            finite_number(row[-1], 0.0, MAX_SLEEP_MINUTES, code="invalid_training_data")
            actual = finite_number(target, 0.0, MAX_SLEEP_MINUTES, code="invalid_training_data")
            if actual <= 0 or type(label) is not int or label != int(actual <= 60):
                raise PredictionError("invalid_training_data")
        if min(self.wake_labels.count(0), self.wake_labels.count(1)) < 3:
            raise PredictionError("insufficient_class_variation")


@dataclass(frozen=True, slots=True, repr=False)
class EvaluationEvidence:
    validation_start: datetime
    validation_end: datetime
    heldout_bouts: int
    samples: int
    mae_minutes: float
    brier_score: float
    baseline_mae_minutes: float
    baseline_brier_score: float

    def __post_init__(self) -> None:
        if utc_time(self.validation_start) >= utc_time(self.validation_end):
            raise PredictionError("invalid_evaluation")
        if (
            type(self.heldout_bouts) is not int or not 5 <= self.heldout_bouts <= 16
            or type(self.samples) is not int or not self.heldout_bouts <= self.samples <= self.heldout_bouts * 3
        ):
            raise PredictionError("invalid_evaluation")
        for value in (self.mae_minutes, self.baseline_mae_minutes):
            finite_number(value, 0.0, MAX_SLEEP_MINUTES, code="invalid_evaluation")
        for value in (self.brier_score, self.baseline_brier_score):
            finite_number(value, 0.0, 1.0, code="invalid_evaluation")

    @property
    def improves_baseline(self) -> bool:
        return (
            self.mae_minutes <= self.baseline_mae_minutes
            and self.brier_score <= self.baseline_brier_score
            and (self.mae_minutes < self.baseline_mae_minutes or self.brier_score < self.baseline_brier_score)
        )


@dataclass(frozen=True, slots=True, repr=False)
class ApprovedModel:
    """Offline evaluation-bound candidate; only this artifact reaches inference."""

    model: FittedNumericalModel
    provenance: ModelProvenance
    evidence: EvaluationEvidence

    def __post_init__(self) -> None:
        self.provenance.__post_init__()
        self.evidence.__post_init__()
        if (
            self.model.provenance != self.provenance
            or utc_time(self.provenance.trained_until) > utc_time(self.evidence.validation_start)
            or not self.evidence.improves_baseline
        ):
            raise PredictionError("model_not_validated")


@dataclass(frozen=True, slots=True, repr=False)
class PredictionMetadata:
    as_of_utc: datetime
    feature_version: str
    baseline_version: str
    baseline_sample_count: int
    elapsed_sleep_minutes: float
    fallback_reason: str | None


@dataclass(frozen=True, slots=True, repr=False)
class PredictionResult:
    expected_sleep_minutes: int
    wake_probability_60m: float
    baseline_minutes: int
    model_version: str
    metadata: PredictionMetadata

    def __post_init__(self) -> None:
        if (
            type(self.expected_sleep_minutes) is not int
            or type(self.baseline_minutes) is not int
            or not isinstance(self.model_version, str)
            or not re.fullmatch(r"[a-z0-9][a-z0-9._:-]{0,100}", self.model_version)
        ):
            raise PredictionError("invalid_model_output")
        minutes = finite_number(self.expected_sleep_minutes, 0.0, MAX_SLEEP_MINUTES, code="invalid_model_output")
        NumericalPrediction(minutes, self.wake_probability_60m)
        finite_number(self.baseline_minutes, 0.0, MAX_SLEEP_MINUTES, code="invalid_model_output")

    def as_dict(self) -> dict[str, int | float | str]:
        return {
            "expected_sleep_minutes": self.expected_sleep_minutes,
            "wake_probability_60m": self.wake_probability_60m,
            "baseline_minutes": self.baseline_minutes,
            "model_version": self.model_version,
        }


def rounded_minutes(value: float) -> int:
    return int(math.floor(finite_number(value, 0.0, MAX_SLEEP_MINUTES, code="invalid_model_output") + 0.5))
