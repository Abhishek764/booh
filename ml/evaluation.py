"""Offline numerical metrics. Production inference never imports this module."""

import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from ml.features import NormalizedEventLike
from ml.prediction.baseline import BaselineModel
from ml.prediction.contracts import (
    MAX_SLEEP_MINUTES,
    ApprovedModel,
    EvaluationEvidence,
    FittedNumericalModel,
    NumericalPrediction,
    PredictionError,
    TrainingPayload,
    finite_number,
)
from ml.training import recent_chronological_split


@dataclass(frozen=True, slots=True)
class EvaluationMetrics:
    samples: int
    mae_minutes: float
    brier_score: float

    def __post_init__(self) -> None:
        if type(self.samples) is not int or not 1 <= self.samples <= 192:
            raise PredictionError("invalid_evaluation")
        finite_number(self.mae_minutes, 0.0, MAX_SLEEP_MINUTES, code="invalid_evaluation")
        finite_number(self.brier_score, 0.0, 1.0, code="invalid_evaluation")


def evaluate_predictions(
    predictions: Iterable[NumericalPrediction], remaining_minutes: Iterable[float]
) -> EvaluationMetrics:
    errors: list[float] = []
    briers: list[float] = []
    try:
        for prediction, target in zip(predictions, remaining_minutes, strict=True):
            if len(errors) >= 192 or not isinstance(prediction, NumericalPrediction):
                raise PredictionError("invalid_evaluation")
            prediction.__post_init__()
            actual = finite_number(target, 0.0, MAX_SLEEP_MINUTES, code="invalid_evaluation")
            errors.append(abs(prediction.expected_sleep_minutes - actual))
            briers.append((prediction.wake_probability_60m - int(actual <= 60.0)) ** 2)
    except (TypeError, ValueError):
        raise PredictionError("invalid_evaluation") from None
    if not errors:
        raise PredictionError("insufficient_evaluation_data")
    return EvaluationMetrics(len(errors), math.fsum(errors) / len(errors), math.fsum(briers) / len(briers))


@dataclass(frozen=True, slots=True, repr=False)
class EvaluationReport:
    baseline: EvaluationMetrics
    tabpfn: EvaluationMetrics | None
    training_bouts: int
    heldout_bouts: int
    model_status: str
    approved_model: ApprovedModel | None = None

    def as_dict(self) -> dict[str, object]:
        def metrics(value: EvaluationMetrics | None) -> dict[str, int | float] | None:
            return None if value is None else {
                "samples": value.samples, "mae_minutes": value.mae_minutes,
                "brier_score": value.brier_score,
            }
        return {
            "baseline": metrics(self.baseline), "tabpfn": metrics(self.tabpfn),
            "training_bouts": self.training_bouts, "heldout_bouts": self.heldout_bouts,
            "model_status": self.model_status,
        }


def evaluate_recent_history(
    history: Iterable[NormalizedEventLike], *, baby_id: UUID, as_of: datetime,
    timezone_name: str, date_of_birth: date | None = None, heldout_bouts: int = 5,
    fit_model: Callable[[TrainingPayload], FittedNumericalModel] | None = None,
) -> EvaluationReport:
    split = recent_chronological_split(
        history, baby_id=baby_id, as_of=as_of, timezone_name=timezone_name,
        date_of_birth=date_of_birth, heldout_bouts=heldout_bouts,
    )
    baseline = BaselineModel()
    baseline_predictions = tuple(
        baseline.predict(
            split.history, baby_id=baby_id, as_of=example.inputs.as_of,
            elapsed_sleep_minutes=example.inputs.elapsed_sleep_minutes,
        ).prediction for example in split.heldout
    )
    targets = tuple(example.remaining_minutes for example in split.heldout)
    baseline_metrics = evaluate_predictions(baseline_predictions, targets)
    candidate: FittedNumericalModel | None = None
    approved: ApprovedModel | None = None
    if fit_model is None:
        return EvaluationReport(baseline_metrics, None, split.training_bouts, split.heldout_bouts, "model_unavailable")
    try:
        payload = split.payload(baby_id)
        if not all(example.inputs.suitable_for_tabpfn for example in split.heldout):
            raise PredictionError("missing_features")
        candidate = fit_model(payload)
        if candidate.provenance != payload.provenance:
            raise PredictionError("invalid_model_provenance")
        outputs = tuple(candidate.predict(example.inputs) for example in split.heldout)
        model_metrics = evaluate_predictions(outputs, targets)
        evidence = EvaluationEvidence(
            split.training_cutoff, split.evaluated_at, split.heldout_bouts, len(split.heldout),
            model_metrics.mae_minutes, model_metrics.brier_score,
            baseline_metrics.mae_minutes, baseline_metrics.brier_score,
        )
        if evidence.improves_baseline:
            approved = ApprovedModel(candidate, payload.provenance, evidence)
            return EvaluationReport(baseline_metrics, model_metrics, split.training_bouts, split.heldout_bouts, "validated", approved)
        return EvaluationReport(baseline_metrics, model_metrics, split.training_bouts, split.heldout_bouts, "baseline_preferred")
    except PredictionError as exc:
        safe_codes = {"insufficient_training_data", "insufficient_class_variation", "missing_features", "model_unavailable", "invalid_model_output", "invalid_evaluation", "invalid_model_provenance"}
        code = exc.code if exc.code in safe_codes else "model_unavailable"
        return EvaluationReport(baseline_metrics, None, split.training_bouts, split.heldout_bouts, code)
    except Exception:
        return EvaluationReport(baseline_metrics, None, split.training_bouts, split.heldout_bouts, "model_unavailable")
    finally:
        if candidate is not None and approved is None:
            try:
                close = getattr(candidate, "close", None)
                if callable(close):
                    close()
            except Exception:
                pass
