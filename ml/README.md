# Machine Learning

This directory owns versioned feature definitions, the deterministic seven-day
baseline, model adapters, and evaluation notes. Feature generation remains
separate from persistence and model inference; each call uses one authorized
baby's history.

`ml.features.FeatureService` now produces a validated, immutable numerical vector
from normalized events and explicit as-of/timezone/birth-date context. It uses
only the Python standard library, enforces single-baby scope, preserves missing
observations, bounds input size, and emits no raw-history logs.

See [`docs/features.md`](../docs/features.md) for every feature, order/version,
units, missing values, windows, incomplete sleeps, DST behavior, quality metadata,
and the input contract. Run the deterministic synthetic unit tests from the root:

```text
.venv/bin/python -m pytest ml/tests -q
```

The numerical engine now lives in `ml/prediction/`: an explicit seven-day
`BaselineModel`, optional locally fitted `TabPFNModel`, and production
`PredictionService`. It produces remaining-sleep minutes, wake probability within
60 minutes, baseline minutes, and an honest selected model version. Gemma has no
role in numerical predictions.

`ml/training.py` and `ml/evaluation.py` are offline-only: causal snapshot labels,
whole-bout chronological holdout, MAE/Brier scores, and a baseline-comparison
promotion gate. Production inference consumes evaluated fitted artifacts and
never trains or evaluates. Missing/unavailable/invalid TabPFN paths explicitly
use the baseline or fail closed; sparse baseline evidence returns no invented
prediction.

See [`docs/predictions.md`](../docs/predictions.md) for targets, baseline/fallback,
model/feature versions, optional CPU runtime, local checkpoint trust/retention,
resource limits, and measured **synthetic-only** real TabPFN evaluation.

```text
.venv/bin/python -m ml.benchmark
```

The next task is TASK-011's layered authenticated prediction API and authorized
history/artifact lifecycle integration.
