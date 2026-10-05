"""Production numerical inference. No fitting/evaluation/LLM dependencies."""

from collections.abc import Iterable
from datetime import date, datetime, timedelta
from uuid import UUID

from ml.features import FeatureService, NormalizedEventLike, normalize_history
from ml.prediction.baseline import BaselineModel
from ml.prediction.contracts import (
    BASELINE_VERSION,
    MAX_SLEEP_MINUTES,
    PREDICTION_FEATURE_VERSION,
    ApprovedModel,
    ModelInput,
    NumericalPrediction,
    PredictionError,
    PredictionMetadata,
    PredictionResult,
    finite_number,
    rounded_minutes,
    utc_time,
)


class PredictionService:
    """FeatureService + approved TabPFNModel + explicit BaselineModel."""

    def __init__(
        self, *, feature_service: FeatureService | None = None,
        baseline_model: BaselineModel | None = None, tabpfn_model: ApprovedModel | None = None,
        allow_baseline_fallback: bool = True,
    ) -> None:
        if type(allow_baseline_fallback) is not bool:
            raise PredictionError("invalid_model_configuration")
        self._features = feature_service or FeatureService()
        self._baseline = baseline_model or BaselineModel()
        self._model = tabpfn_model
        self._allow_fallback = allow_baseline_fallback

    def predict(
        self, history: Iterable[NormalizedEventLike], *, baby_id: UUID,
        as_of: datetime, timezone_name: str, date_of_birth: date | None = None,
        sleep_started_at: datetime | None = None,
    ) -> PredictionResult:
        current = utc_time(as_of)
        start = current if sleep_started_at is None else utc_time(sleep_started_at)
        elapsed = finite_number(
            (current - start).total_seconds() / 60.0, 0.0, MAX_SLEEP_MINUTES,
            code="invalid_context",
        )
        records = normalize_history(history, baby_id=baby_id)
        features = self._features.build(
            records, baby_id=baby_id, as_of=current, timezone_name=timezone_name,
            date_of_birth=date_of_birth,
        )
        inputs = ModelInput(baby_id, features, elapsed)
        baseline = self._baseline.predict(
            records, baby_id=baby_id, as_of=current, elapsed_sleep_minutes=elapsed,
        )
        selected = baseline.prediction
        version = BASELINE_VERSION
        reason: str | None = None
        try:
            if self._model is None:
                raise PredictionError("model_unavailable")
            if not isinstance(self._model, ApprovedModel):
                raise PredictionError("model_not_validated")
            self._model.__post_init__()
            provenance = self._model.provenance
            if provenance.baby_id != baby_id:
                raise PredictionError("model_scope_mismatch")
            if self._model.evidence.validation_end > current or provenance.trained_until > current:
                raise PredictionError("model_from_future")
            if current - utc_time(provenance.trained_until) > timedelta(days=7):
                raise PredictionError("stale_model")
            if not inputs.suitable_for_tabpfn:
                raise PredictionError("missing_features")
            if elapsed > 60.0:
                raise PredictionError("outside_model_support")
            output = self._model.model.predict(inputs)
            if not isinstance(output, NumericalPrediction):
                raise PredictionError("invalid_model_output")
            output.__post_init__()
            selected = output
            version = provenance.model_version
        except PredictionError as exc:
            allowed = {
                "model_unavailable", "model_not_validated", "model_scope_mismatch",
                "model_from_future", "stale_model", "missing_features",
                "outside_model_support", "invalid_model_output",
            }
            reason = exc.code if exc.code in allowed else "invalid_model_output"
        except Exception:
            reason = "model_unavailable"
        if reason is not None and not self._allow_fallback:
            raise PredictionError(reason) from None
        return PredictionResult(
            expected_sleep_minutes=rounded_minutes(selected.expected_sleep_minutes),
            wake_probability_60m=float(selected.wake_probability_60m),
            baseline_minutes=rounded_minutes(baseline.prediction.expected_sleep_minutes),
            model_version=version,
            metadata=PredictionMetadata(
                current, PREDICTION_FEATURE_VERSION, BASELINE_VERSION,
                baseline.sample_count, elapsed, reason,
            ),
        )
