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

The next TASK-008 slice is the explicit deterministic seven-day baseline and its
evaluation; the completed feature layer provides its independent input boundary.
