"""Offline causal example construction and fitting; never called by inference."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from uuid import UUID

from ml.features import (
    FeatureService,
    HistoryEvent,
    NormalizedEventLike,
    normalize_history,
)
from ml.prediction.baseline import completed_bouts
from ml.prediction.contracts import (
    ModelInput,
    ModelProvenance,
    PredictionError,
    TrainingPayload,
    utc_time,
)
from ml.prediction.tabpfn import TabPFNConfig, TabPFNModel, _fit_offline

MAX_BOUTS = 64
MIN_TRAINING_BOUTS = 20
ELAPSED_SNAPSHOTS = (0.0, 30.0, 60.0)


@dataclass(frozen=True, slots=True, repr=False)
class TrainingExample:
    inputs: ModelInput
    bout_start: datetime
    label_available_at: datetime
    remaining_minutes: float


@dataclass(frozen=True, slots=True, repr=False)
class ChronologicalSplit:
    history: tuple[HistoryEvent, ...]
    training: tuple[TrainingExample, ...]
    heldout: tuple[TrainingExample, ...]
    training_cutoff: datetime
    evaluated_at: datetime
    training_bouts: int
    heldout_bouts: int

    def payload(self, baby_id: UUID) -> TrainingPayload:
        if self.training_bouts < MIN_TRAINING_BOUTS:
            raise PredictionError("insufficient_training_data")
        if any(example.label_available_at > self.training_cutoff for example in self.training):
            raise PredictionError("training_leakage")
        provenance = ModelProvenance(baby_id, self.training_cutoff, self.training_bouts)
        if any(example.inputs.baby_id != baby_id for example in (*self.training, *self.heldout)):
            raise PredictionError("invalid_history_scope")
        return TrainingPayload(
            provenance, tuple(example.inputs.values for example in self.training),
            tuple(example.remaining_minutes for example in self.training),
            tuple(int(example.remaining_minutes <= 60) for example in self.training),
        )


def recent_chronological_split(
    history: Iterable[NormalizedEventLike], *, baby_id: UUID, as_of: datetime,
    timezone_name: str, date_of_birth: date | None = None, heldout_bouts: int = 5,
) -> ChronologicalSplit:
    if type(heldout_bouts) is not int or not 5 <= heldout_bouts <= 16:
        raise PredictionError("invalid_evaluation")
    records = normalize_history(history, baby_id=baby_id)
    current = utc_time(as_of)
    bouts = completed_bouts(records, baby_id=baby_id, as_of=current)[-MAX_BOUTS:]
    if len(bouts) < heldout_bouts + 3:
        raise PredictionError("insufficient_evaluation_data")
    validation_bouts = bouts[-heldout_bouts:]
    cutoff = validation_bouts[0].start_time
    train_bouts = tuple(bout for bout in bouts[:-heldout_bouts] if bout.end_time is not None and bout.end_time <= cutoff)
    service = FeatureService()

    def examples(selected: tuple[HistoryEvent, ...]) -> tuple[TrainingExample, ...]:
        result: list[TrainingExample] = []
        for bout in selected:
            if bout.end_time is None:
                continue
            for elapsed in ELAPSED_SNAPSHOTS:
                reference = bout.start_time + timedelta(minutes=elapsed)
                if reference >= bout.end_time:
                    continue
                # Only the label uses the future completion; features mask it.
                features = service.build(
                    records, baby_id=baby_id, as_of=reference, timezone_name=timezone_name,
                    date_of_birth=date_of_birth,
                )
                result.append(TrainingExample(
                    ModelInput(baby_id, features, elapsed), bout.start_time, bout.end_time,
                    (bout.end_time - reference).total_seconds() / 60.0,
                ))
        return tuple(result)

    training = tuple(example for example in examples(train_bouts) if example.inputs.suitable_for_tabpfn)
    heldout = examples(validation_bouts)
    distinct_training = len({example.bout_start for example in training})
    if any(example.inputs.as_of < cutoff for example in heldout):
        raise PredictionError("training_leakage")
    return ChronologicalSplit(records, training, heldout, cutoff, current, distinct_training, heldout_bouts)


class TabPFNTrainer:
    """Explicit offline fitting. Production services never instantiate this class."""

    def __init__(self, config: TabPFNConfig | None = None) -> None:
        self._config = config

    def fit(self, payload: TrainingPayload) -> TabPFNModel:
        return _fit_offline(payload, self._config)
