import json
from dataclasses import FrozenInstanceError, replace
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from ml.features import FeatureValidationError
from ml.prediction.contracts import (
    BASELINE_VERSION,
    TABPFN_VERSION,
    ApprovedModel,
    EvaluationEvidence,
    ModelProvenance,
    NumericalPrediction,
    PredictionError,
)
from ml.prediction.service import PredictionService
from ml.tests.prediction_support import AS_OF, BABY, synthetic_history


class StubModel:
    def __init__(self, *, output=None, failure=None, baby_id=BABY, trained_until=None):
        self.provenance = ModelProvenance(baby_id, trained_until or AS_OF - timedelta(days=1), 25)
        self.output = output if output is not None else NumericalPrediction(47.2, 0.68)
        self.failure = failure
        self.calls = 0

    def predict(self, inputs):
        self.calls += 1
        if self.failure is not None:
            raise self.failure
        return self.output


def approved(model, *, validation_end=AS_OF):
    return ApprovedModel(model, model.provenance, EvaluationEvidence(
        model.provenance.trained_until, validation_end, 5, 10, 10.0, 0.1, 15.0, 0.2,
    ))


def predict(service, history=None, **kwargs):
    return service.predict(
        history if history is not None else synthetic_history(), baby_id=kwargs.pop("baby_id", BABY),
        as_of=kwargs.pop("as_of", AS_OF), timezone_name="UTC", **kwargs,
    )


def test_approved_tabpfn_prediction_always_retains_the_explicit_baseline():
    model = StubModel()
    result = predict(PredictionService(tabpfn_model=approved(model)))
    assert result.as_dict() == {
        "expected_sleep_minutes": 47, "wake_probability_60m": 0.68,
        "baseline_minutes": 75, "model_version": TABPFN_VERSION,
    }
    assert result.metadata.fallback_reason is None
    assert model.calls == 1
    assert json.loads(json.dumps(result.as_dict(), allow_nan=False)) == result.as_dict()
    with pytest.raises(FrozenInstanceError):
        result.expected_sleep_minutes = 200


def test_absent_optional_model_uses_the_named_documented_baseline():
    result = predict(PredictionService())
    assert result.model_version == BASELINE_VERSION
    assert result.expected_sleep_minutes == result.baseline_minutes == 75
    assert result.wake_probability_60m == pytest.approx(1 / 3)
    assert result.metadata.fallback_reason == "model_unavailable"


def test_baseline_remaining_sleep_is_conditioned_on_current_elapsed_time():
    result = predict(PredictionService(), sleep_started_at=AS_OF - timedelta(minutes=30))
    assert result.expected_sleep_minutes == 45
    assert result.wake_probability_60m == pytest.approx(5 / 6)
    assert result.metadata.elapsed_sleep_minutes == 30


@pytest.mark.parametrize("failure", [
    RuntimeError("synthetic-private-sdk-error"), MemoryError(), TimeoutError(),
    PredictionError("invalid_model_output"), PredictionError("synthetic-private-code"),
])
def test_model_exceptions_have_safe_numerical_fallback_and_private_reason(failure):
    model = StubModel(failure=failure)
    result = predict(PredictionService(tabpfn_model=approved(model)))
    assert result.expected_sleep_minutes == result.baseline_minutes
    assert result.model_version == BASELINE_VERSION
    assert result.metadata.fallback_reason in {"model_unavailable", "invalid_model_output"}
    assert "synthetic-private" not in str(result.as_dict())


@pytest.mark.parametrize("bad", [None, {}, "LLM says 47", SimpleNamespace(expected_sleep_minutes=47, wake_probability_60m=0.68)])
def test_arbitrary_or_llm_like_model_output_cannot_change_predictions(bad):
    model = StubModel()
    model.output = bad
    result = predict(PredictionService(tabpfn_model=approved(model)))
    assert result.model_version == BASELINE_VERSION
    assert result.metadata.fallback_reason == "invalid_model_output"


@pytest.mark.parametrize("minutes,probability", [
    (float("nan"), 0.5), (float("inf"), 0.5), (-float("inf"), 0.5),
    (-1, 0.5), (10081, 0.5), (True, 0.5), ("47", 0.5), (10**1000, 0.5),
    (47, float("nan")), (47, float("inf")), (47, -0.1), (47, 1.1), (47, True),
])
def test_nan_infinity_ranges_and_types_are_rejected_at_model_and_service_boundaries(minutes, probability):
    with pytest.raises(PredictionError, match="invalid_model_output"):
        NumericalPrediction(minutes, probability)
    # Defend against a plugin bypassing a frozen DTO's constructor.
    forged = object.__new__(NumericalPrediction)
    object.__setattr__(forged, "expected_sleep_minutes", minutes)
    object.__setattr__(forged, "wake_probability_60m", probability)
    result = predict(PredictionService(tabpfn_model=approved(StubModel(output=forged))))
    assert result.model_version == BASELINE_VERSION
    assert result.metadata.fallback_reason == "invalid_model_output"


def test_missing_features_or_quality_bypass_tabpfn_and_use_observed_baseline():
    model = StubModel()
    history = tuple(record for record in synthetic_history() if record.event_type == "sleep")
    result = predict(PredictionService(tabpfn_model=approved(model)), history)
    assert result.metadata.fallback_reason == "missing_features"
    assert model.calls == 0


def test_missing_birthdate_is_allowed_and_does_not_fabricate_an_age():
    model = StubModel()
    result = predict(PredictionService(tabpfn_model=approved(model)))
    assert result.model_version == TABPFN_VERSION


def test_foreign_model_is_never_called_or_used_for_other_babies():
    model = StubModel(baby_id=uuid4())
    result = predict(PredictionService(tabpfn_model=approved(model)))
    assert model.calls == 0
    assert result.metadata.fallback_reason == "model_scope_mismatch"


def test_future_validation_and_stale_contexts_are_not_used_in_inference():
    model = StubModel()
    result = predict(PredictionService(tabpfn_model=approved(model, validation_end=AS_OF + timedelta(hours=1))))
    assert result.metadata.fallback_reason == "model_from_future"
    stale = StubModel(trained_until=AS_OF - timedelta(days=8))
    result = predict(PredictionService(tabpfn_model=approved(stale)))
    assert result.metadata.fallback_reason == "stale_model"
    assert model.calls == stale.calls == 0


def test_elapsed_outside_trained_snapshot_support_uses_conditional_baseline():
    model = StubModel()
    result = predict(PredictionService(tabpfn_model=approved(model)), sleep_started_at=AS_OF - timedelta(minutes=65))
    assert result.metadata.fallback_reason == "outside_model_support"
    assert model.calls == 0


def test_no_baseline_evidence_fails_safely_even_with_an_approved_model():
    model = StubModel()
    with pytest.raises(PredictionError, match="insufficient_history"):
        predict(PredictionService(tabpfn_model=approved(model)), [])
    assert model.calls == 0


def test_fallback_can_be_disabled_for_fail_closed_operation():
    with pytest.raises(PredictionError, match="model_unavailable"):
        predict(PredictionService(allow_baseline_fallback=False))


def test_unvalidated_artifact_or_changed_provenance_cannot_run():
    model = StubModel()
    result = predict(PredictionService(tabpfn_model=model))
    assert result.metadata.fallback_reason == "model_not_validated"
    artifact = approved(model)
    model.provenance = replace(model.provenance, baby_id=uuid4())
    result = predict(PredictionService(tabpfn_model=artifact))
    assert result.metadata.fallback_reason == "model_not_validated"
    assert model.calls == 0


def test_mixed_scope_and_malformed_history_fail_before_model_inference():
    model = StubModel()
    from ml.features import HistoryEvent

    with pytest.raises(FeatureValidationError, match="invalid_history_scope"):
        predict(PredictionService(tabpfn_model=approved(model)), synthetic_history() + (HistoryEvent(uuid4(), "wake", AS_OF),))
    assert model.calls == 0


@pytest.mark.parametrize("start", [AS_OF + timedelta(minutes=1), AS_OF.replace(tzinfo=None), "not-a-date"])
def test_invalid_current_sleep_context_is_rejected(start):
    with pytest.raises(PredictionError, match="invalid_context"):
        predict(PredictionService(), sleep_started_at=start)
