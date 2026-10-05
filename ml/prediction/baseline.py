"""Explicit deterministic seven-day conditional-remaining-sleep baseline."""

import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from ml.features import HistoryEvent, NormalizedEventLike, normalize_history
from ml.prediction.contracts import (
    BASELINE_VERSION,
    MAX_SLEEP_MINUTES,
    NumericalPrediction,
    PredictionError,
    finite_number,
    utc_time,
)

MIN_BASELINE_BOUTS = 3


def completed_bouts(
    history: Iterable[NormalizedEventLike], *, baby_id: UUID, as_of: datetime
) -> tuple[HistoryEvent, ...]:
    current = utc_time(as_of)
    try:
        cutoff = current - timedelta(days=7)
    except OverflowError:
        raise PredictionError("invalid_context") from None
    unique = {
        (event.start_time, event.end_time): event
        for event in normalize_history(history, baby_id=baby_id)
        if event.event_type == "sleep" and event.end_time is not None
        and cutoff < event.end_time <= current and event.start_time < event.end_time
    }
    bouts = sorted(unique.values(), key=lambda event: (event.start_time, event.end_time or event.start_time))
    for previous, current_bout in zip(bouts, bouts[1:]):
        if previous.end_time is not None and current_bout.start_time < previous.end_time:
            raise PredictionError("overlapping_sleep_history")
    return tuple(bouts)


@dataclass(frozen=True, slots=True, repr=False)
class BaselineEstimate:
    prediction: NumericalPrediction
    sample_count: int
    model_version: str = BASELINE_VERSION


class BaselineModel:
    def predict(
        self, history: Iterable[NormalizedEventLike], *, baby_id: UUID,
        as_of: datetime, elapsed_sleep_minutes: float = 0.0,
    ) -> BaselineEstimate:
        elapsed = finite_number(elapsed_sleep_minutes, 0.0, MAX_SLEEP_MINUTES, code="invalid_context")
        remaining = [
            (event.end_time - event.start_time).total_seconds() / 60.0 - elapsed
            for event in completed_bouts(history, baby_id=baby_id, as_of=as_of)
            if event.end_time is not None
            and (event.end_time - event.start_time).total_seconds() / 60.0 > elapsed
        ]
        if len(remaining) < MIN_BASELINE_BOUTS:
            raise PredictionError("insufficient_history")
        return BaselineEstimate(
            prediction=NumericalPrediction(
                math.fsum(remaining) / len(remaining),
                sum(minutes <= 60.0 for minutes in remaining) / len(remaining),
            ),
            sample_count=len(remaining),
        )
