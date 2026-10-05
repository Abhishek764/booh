"""Offline, reproducible synthetic benchmark; never imports production services."""

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

from ml.evaluation import evaluate_recent_history
from ml.features import HistoryEvent
from ml.prediction.contracts import PredictionError
from ml.prediction.tabpfn import TabPFNConfig
from ml.training import TabPFNTrainer

REGRESSOR_SHA256 = "2ab5a07d5c41dfe6db9aa7ae106fc6de898326c2765be66505a07e2868c10736"
CLASSIFIER_SHA256 = "cf8c519c01eaf1613ee91239006d57b1c806ff5f23ac1aeb1315ba1015210e49"


def main() -> None:
    parser = argparse.ArgumentParser(description="BOOH synthetic-only offline model benchmark")
    parser.add_argument("--regressor-checkpoint", type=Path)
    parser.add_argument("--classifier-checkpoint", type=Path)
    args = parser.parse_args()
    baby = UUID(int=1)
    reference = datetime(2026, 1, 8, tzinfo=timezone.utc)
    history: list[HistoryEvent] = []
    for index in range(42):
        start = reference - timedelta(hours=4 * (42 - index))
        end = start + timedelta(minutes=(45, 75, 90, 110, 50, 80)[index % 6])
        history.extend((
            HistoryEvent(baby, "feed", start - timedelta(minutes=10)),
            HistoryEvent(baby, "sleep", start, end), HistoryEvent(baby, "wake", end),
        ))
    config = None
    configuration_status: str | None = None
    if args.regressor_checkpoint is not None or args.classifier_checkpoint is not None:
        try:
            config = TabPFNConfig(
                args.regressor_checkpoint, args.classifier_checkpoint,
                REGRESSOR_SHA256, CLASSIFIER_SHA256,
            )
        except PredictionError:
            configuration_status = "model_unavailable"
    report = evaluate_recent_history(
        history, baby_id=baby, as_of=reference, timezone_name="UTC",
        fit_model=TabPFNTrainer(config).fit,
    )
    result = report.as_dict()
    if configuration_status:
        result["model_status"] = configuration_status
    print(json.dumps(result, indent=2, allow_nan=False))
    if report.approved_model is not None:
        close = getattr(report.approved_model.model, "close", None)
        if callable(close):
            close()


if __name__ == "__main__":
    main()
