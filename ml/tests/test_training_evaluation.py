from datetime import timedelta

import pytest

from ml.evaluation import evaluate_recent_history
from ml.prediction.contracts import NumericalPrediction, PredictionError
from ml.tests.prediction_support import AS_OF, BABY, synthetic_history
from ml.training import recent_chronological_split


def test_recent_baseline_evaluation_is_chronological_and_has_real_metrics():
    report = evaluate_recent_history(synthetic_history(), baby_id=BABY, as_of=AS_OF, timezone_name="UTC")
    assert report.baseline.samples == 14
    assert 0 < report.baseline.mae_minutes < 100
    assert 0 < report.baseline.brier_score < 1
    assert report.tabpfn is None
    assert report.model_status == "model_unavailable"


def test_training_and_holdout_never_share_bouts_or_future_labels():
    split = recent_chronological_split(synthetic_history(), baby_id=BABY, as_of=AS_OF, timezone_name="UTC")
    train_starts = {example.bout_start for example in split.training}
    test_starts = {example.bout_start for example in split.heldout}
    assert not train_starts & test_starts
    assert len(test_starts) == 5
    assert all(example.label_available_at <= split.training_cutoff for example in split.training)
    assert all(example.inputs.as_of >= split.training_cutoff for example in split.heldout)
    assert all(example.inputs.as_of < example.label_available_at for example in (*split.training, *split.heldout))
    assert split.payload(BABY).provenance.training_bouts >= 20


def test_current_completion_does_not_enter_its_own_feature_duration():
    from ml.features import FeatureService

    split = recent_chronological_split(synthetic_history(), baby_id=BABY, as_of=AS_OF, timezone_name="UTC")
    for example in split.heldout:
        prefix = tuple(record for record in split.history if record.start_time <= example.inputs.as_of)
        assert FeatureService().build(prefix, baby_id=BABY, as_of=example.inputs.as_of, timezone_name="UTC").values == example.inputs.features.values
        assert example.inputs.features.as_dict()["incomplete_sleep_count"] >= 1


def test_perfect_injected_candidate_verifies_promotion_without_claiming_tabpfn_accuracy():
    history = synthetic_history()
    split = recent_chronological_split(history, baby_id=BABY, as_of=AS_OF, timezone_name="UTC")
    oracle_targets = {example.inputs.as_of: example.remaining_minutes for example in split.heldout}

    class Oracle:
        def __init__(self, payload):
            self.provenance = payload.provenance

        def predict(self, inputs):
            target = oracle_targets[inputs.as_of]
            return NumericalPrediction(target, float(target <= 60))

    report = evaluate_recent_history(history, baby_id=BABY, as_of=AS_OF, timezone_name="UTC", fit_model=Oracle)
    assert report.model_status == "validated"
    assert report.tabpfn.mae_minutes == report.tabpfn.brier_score == 0.0
    assert report.approved_model is not None


def test_dependency_failure_is_not_scored_as_tabpfn_success():
    def unavailable(payload):
        raise RuntimeError("synthetic-private-training-error")

    report = evaluate_recent_history(synthetic_history(), baby_id=BABY, as_of=AS_OF, timezone_name="UTC", fit_model=unavailable)
    assert report.model_status == "model_unavailable"
    assert report.tabpfn is None
    assert "synthetic-private" not in str(report.as_dict())


def test_sparse_recent_holdout_cannot_report_fake_zero_error():
    with pytest.raises(PredictionError, match="insufficient_evaluation_data"):
        evaluate_recent_history(synthetic_history(5), baby_id=BABY, as_of=AS_OF, timezone_name="UTC")


def test_whole_sleep_groups_and_reference_times_are_preserved_in_elapsed_training():
    split = recent_chronological_split(synthetic_history(), baby_id=BABY, as_of=AS_OF, timezone_name="UTC")
    assert {example.inputs.elapsed_sleep_minutes for example in split.training} == {0, 30, 60}
    for example in split.training:
        assert example.inputs.as_of == example.bout_start + timedelta(minutes=example.inputs.elapsed_sleep_minutes)


def test_underperforming_candidate_keeps_baseline_and_closes_fitted_context():
    closed = []

    class BadModel:
        def __init__(self, payload):
            self.provenance = payload.provenance

        def predict(self, inputs):
            return NumericalPrediction(1000, 0.99)

        def close(self):
            closed.append(True)

    report = evaluate_recent_history(synthetic_history(), baby_id=BABY, as_of=AS_OF, timezone_name="UTC", fit_model=BadModel)
    assert report.model_status == "baseline_preferred"
    assert report.approved_model is None
    assert report.tabpfn.mae_minutes > report.baseline.mae_minutes
    assert closed == [True]


def test_invalid_candidate_outputs_are_not_hidden_by_scoring_baseline_in_their_place():
    closed = []

    class InvalidModel:
        def __init__(self, payload):
            self.provenance = payload.provenance

        def predict(self, inputs):
            return {"expected_sleep_minutes": float("nan"), "wake_probability_60m": 0.5}

        def close(self):
            closed.append(True)

    report = evaluate_recent_history(synthetic_history(), baby_id=BABY, as_of=AS_OF, timezone_name="UTC", fit_model=InvalidModel)
    assert report.model_status == "invalid_evaluation"
    assert report.tabpfn is None
    assert report.baseline.samples == 14
    assert closed == [True]


def test_too_few_distinct_training_bouts_prevents_fitting_even_with_many_elapsed_rows():
    fitted = []
    report = evaluate_recent_history(
        synthetic_history(20), baby_id=BABY, as_of=AS_OF, timezone_name="UTC",
        fit_model=lambda payload: fitted.append(payload),
    )
    assert report.model_status == "insufficient_training_data"
    assert fitted == []


def test_one_class_training_and_nonfinite_rows_are_rejected_before_sdk_fitting():
    from dataclasses import replace

    split = recent_chronological_split(synthetic_history(), baby_id=BABY, as_of=AS_OF, timezone_name="UTC")
    data = split.payload(BABY)
    with pytest.raises(PredictionError, match="insufficient_class_variation"):
        replace(data, remaining_minutes=(10.0,) * len(data.rows), wake_labels=(1,) * len(data.rows))
    rows = list(data.rows)
    rows[0] = (float("nan"),) + rows[0][1:]
    with pytest.raises(PredictionError, match="invalid_training_data"):
        replace(data, rows=tuple(rows))


def test_appending_later_labels_never_changes_the_existing_training_vector_values():
    from dataclasses import replace

    history = synthetic_history()
    original = recent_chronological_split(history, baby_id=BABY, as_of=AS_OF, timezone_name="UTC")
    cutoff = original.training_cutoff
    changed = tuple(
        replace(record, end_time=record.end_time + timedelta(minutes=5))
        if record.event_type == "sleep" and record.start_time >= cutoff else record
        for record in history
    )
    comparison = recent_chronological_split(changed, baby_id=BABY, as_of=AS_OF, timezone_name="UTC")
    assert original.training == comparison.training


def test_promotion_requires_nonworse_both_metrics_and_at_least_one_strict_improvement():
    from ml.prediction.contracts import EvaluationEvidence

    for mae, brier, expected in ((10, 0.1, True), (10, 0.3, False), (20, 0.1, False), (15, 0.2, False)):
        evidence = EvaluationEvidence(AS_OF - timedelta(days=1), AS_OF, 5, 14, mae, brier, 15, 0.2)
        assert evidence.improves_baseline is expected
