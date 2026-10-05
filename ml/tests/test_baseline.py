from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest

from ml.evaluation import evaluate_predictions
from ml.features import HistoryEvent
from ml.prediction.baseline import BaselineModel
from ml.prediction.contracts import (
    BASELINE_VERSION,
    NumericalPrediction,
    PredictionError,
)

BABY = UUID(int=1)
NOW = datetime(2026, 1, 8, tzinfo=timezone.utc)


def sleeps(durations, *, reference=NOW):
    return tuple(
        HistoryEvent(BABY, "sleep", reference - timedelta(hours=12 * (index + 1)), duration_seconds=int(minutes * 60))
        for index, minutes in enumerate(durations)
    )


def test_baseline_is_last_seven_days_empirical_mean_and_60_minute_probability():
    result = BaselineModel().predict(sleeps([30, 60, 90]), baby_id=BABY, as_of=NOW)
    assert result.prediction.expected_sleep_minutes == 60.0
    assert result.prediction.wake_probability_60m == pytest.approx(2 / 3)
    assert result.sample_count == 3
    assert result.model_version == BASELINE_VERSION


def test_elapsed_sleep_conditions_on_surviving_bouts_before_subtracting_elapsed():
    result = BaselineModel().predict(sleeps([30, 60, 90, 120]), baby_id=BABY, as_of=NOW, elapsed_sleep_minutes=30)
    assert result.prediction.expected_sleep_minutes == 60.0
    assert result.prediction.wake_probability_60m == pytest.approx(2 / 3)
    assert result.sample_count == 3


@pytest.mark.parametrize("durations,elapsed", [([], 0), ([30], 0), ([30, 60], 0), ([30, 60, 90], 60), ([30, 60, 90], 100)])
def test_sparse_or_exhausted_survival_history_has_no_manufactured_prediction(durations, elapsed):
    with pytest.raises(PredictionError, match="insufficient_history"):
        BaselineModel().predict(sleeps(durations), baby_id=BABY, as_of=NOW, elapsed_sleep_minutes=elapsed)


def test_old_incomplete_zero_and_future_bouts_do_not_change_the_baseline():
    history = sleeps([30, 60, 90])
    extra = (
        HistoryEvent(BABY, "sleep", NOW - timedelta(days=8), NOW - timedelta(days=7)),
        HistoryEvent(BABY, "sleep", NOW - timedelta(minutes=5)),
        HistoryEvent(BABY, "sleep", NOW, NOW),
        HistoryEvent(BABY, "sleep", NOW - timedelta(minutes=2), NOW + timedelta(minutes=50)),
    )
    assert BaselineModel().predict(history + extra, baby_id=BABY, as_of=NOW) == BaselineModel().predict(history, baby_id=BABY, as_of=NOW)


def test_duplicates_do_not_create_evidence_and_scope_is_checked_even_for_old_data():
    with pytest.raises(PredictionError, match="insufficient_history"):
        BaselineModel().predict(sleeps([30]) * 5, baby_id=BABY, as_of=NOW)
    from ml.features import FeatureValidationError

    with pytest.raises(FeatureValidationError, match="invalid_history_scope"):
        BaselineModel().predict(sleeps([30, 60, 90]) + (HistoryEvent(uuid4(), "wake", NOW - timedelta(days=8)),), baby_id=BABY, as_of=NOW)


def test_overlapping_completed_labels_are_rejected():
    history = sleeps([30, 60, 90])
    with pytest.raises(PredictionError, match="overlapping_sleep_history"):
        BaselineModel().predict(history + (HistoryEvent(BABY, "sleep", history[0].start_time, history[0].end_time or history[0].start_time + timedelta(hours=1)),), baby_id=BABY, as_of=NOW)


def test_mae_and_brier_score_are_independent_known_numerical_metrics():
    metrics = evaluate_predictions([NumericalPrediction(50, 0.8), NumericalPrediction(70, 0.2)], [40, 100])
    assert metrics.samples == 2
    assert metrics.mae_minutes == 20.0
    assert metrics.brier_score == pytest.approx(0.04)


@pytest.mark.parametrize("targets", [[], [40], [float("nan"), 100], [float("inf"), 100], [-1, 100], [True, 100]])
def test_metric_inputs_must_be_aligned_finite_and_bounded(targets):
    with pytest.raises(PredictionError):
        evaluate_predictions([NumericalPrediction(50, 0.8), NumericalPrediction(70, 0.2)], targets)
