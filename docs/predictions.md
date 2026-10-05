# Numerical prediction engine

## Architecture and contract

```text
Production PredictionService
    ├── FeatureService
    ├── evaluated, fitted TabPFNModel (optional)
    └── explicit BaselineModel (always computed)

Offline workflows
    ├── recent_chronological_split → TrainingPayload → TabPFNTrainer.fit
    └── evaluate_recent_history → MAE/Brier comparison → ApprovedModel
```

The production component is `ml.prediction.service.PredictionService`. It
consumes the selected baby's already authorized normalized history, not HTTP
requests or database connections. Models never query persistence. The existing
feature service remains independent and standard-library-only. The authenticated
routes and bounded owner-scoped retrieval now compose this engine through the
backend pipeline; see [prediction API](prediction-api.md).

**Target:** remaining minutes in the current sleep bout, and probability that the
bout ends within the next 60 minutes. A recorded sleep end is the numerical wake
label; a separate explicit wake record is not required to label that bout.
`sleep_started_at` supplies the current sleep's aware start time. Omit it for an
at-sleep-start forecast (elapsed = zero). It must not be in the future or more
than seven days before `as_of`. This is an advisory estimate, not medical advice
or a guarantee. An unclosed historic sleep is not a completed training label.

```python
from ml.prediction.service import PredictionService

service = PredictionService(tabpfn_model=approved_model)  # Optional artifact.
result = service.predict(
    authorized_history,
    baby_id=authorized_baby_id,
    as_of=aware_prediction_time,
    timezone_name=baby_timezone,
    date_of_birth=baby_date_of_birth,  # Optional.
    sleep_started_at=aware_current_sleep_start,  # Optional: default elapsed zero.
)
payload = result.as_dict()
```

Example **shape**, not a measured family prediction:

```json
{
  "expected_sleep_minutes": 47,
  "wake_probability_60m": 0.68,
  "baseline_minutes": 51,
  "model_version": "tabpfn-9.1.0-v2-remaining-v1"
}
```

Returned minutes use nearest-minute half-up rounding. Probabilities stay finite
within `[0, 1]`. Numerical model values are rejected for wrong types, booleans,
strings, missing fields, negative durations, more than 10,080 minutes, NaN,
Infinity, invalid probability ranges, or invalid SDK shapes/classes. No clipping
turns an invalid model result into a plausible value. `baseline_minutes` always
comes from the explicit baseline, even when TabPFN is selected.

The immutable result's internal metadata records as-of time, prediction-feature
version, baseline version/sample count, elapsed sleep, and a fixed fallback code.
Models are bound to a baby ID and training cutoff. Raw events, model internals,
provider responses, and personal identifiers are excluded from the public mapping
and automatic representation.

## Deterministic last-seven-day baseline

`BaselineModel`, version `baseline-7d-v1`, uses positive-duration, nonoverlapping,
unique sleep bouts **completed** in `(as_of - 7 elapsed days, as_of]`. Equivalent
offset/end/duration representations deduplicate. It validates all input scope
and event fields, including old/future records. Incomplete sleeps, future ends,
zero-duration sleeps, and older completed bouts provide no completion evidence.
Completed bouts that overlap other distinct completed bouts reject the history
with `overlapping_sleep_history`, rather than inflate statistical evidence.

For current elapsed sleep `e`, retain historical durations `d > e`. These are
the empirical bouts known to have survived to the current elapsed duration.

```text
remaining samples = d - e, for d > e
expected remaining minutes = arithmetic mean(remaining samples)
wake probability within 60 minutes = count(remaining <= 60) / sample count
```

Require **at least three surviving independent bouts**. Otherwise raise the fixed
`insufficient_history` error and return no manufactured prediction. No defaults
from other families, population priors, LLM guesses, or zero-valued confidence
are substituted. With small histories this empirical frequency is uncertain;
sample count is internal evidence, not a calibrated confidence claim.

This baseline ignores missing optional feed/wake/age features. It needs valid
sleep completion evidence, so it remains usable when TabPFN's feature readiness
criteria fail. A current bout beyond all comparable history yields an explicit
failure instead of incorrectly predicting zero remaining minutes.

## Training and held-out evaluation

`ml.training` and `ml.evaluation` are offline-only modules. Production inference
does not import either, build labels, call `fit`, tune, evaluate, or download
weights. Fitted artifacts are created in an explicit offline job and passed into
the service. No fitted user data is serialized to disk by this implementation.

Dataset construction:

1. Validate/bound one baby's history (10,000 events), normalize UTC, and select
   at most the latest 64 completed bouts from the last seven days.
2. Hold out the latest five whole bouts by default (configurable from 5 to 16).
   All snapshots of a bout belong to the same split. No randomized row split.
3. Set the training cutoff to the first held-out bout's start. Training labels
   must have become available no later than that cutoff.
4. Generate snapshots at 0, 30, and 60 elapsed minutes, only while each bout is
   still asleep. The feature service computes values **as of that snapshot**,
   excluding future events and masking future ends before duplicate handling.
   Only the target calculation sees the eventual end time.
5. The model matrix uses the 13 `sleep-history-v1` features plus explicit
   `elapsed_sleep_minutes`, order/version `sleep-remaining-v1`. Targets are
   remaining minutes and the binary label `remaining <= 60`.
6. Require at least 20 distinct eligible training bouts and at least three rows
   of each binary class. Filter sparse training snapshots. Reject nonfinite,
   invalid-shape, or inconsistent feature/target/label payloads before the SDK.
   Missing age is an explicit `-1` feature; other missing timing features or the
   feature service's sparse-quality flag prevent TabPFN use.

The held-out candidate stays fixed: no fitting on validation labels or automatic
refit after promotion. The baseline is recomputed causally for each held-out
snapshot; earlier held-out completions may enter later snapshots' baseline, as
they would in production. MAE and Brier are measured on the **same** snapshots
using unrounded numerical predictions:

```text
MAE = mean(abs(predicted remaining minutes - observed remaining minutes))
Brier = mean((predicted probability - observed binary wake-within-60 label)^2)
```

Evaluate TabPFN directly; never substitute a fallback baseline into its score.
Unavailable/invalid models have no TabPFN score. An empty/unusable evaluation
fails explicitly rather than reporting zero error.

Promotion requires at least five held-out bouts, non-worse MAE **and** Brier than
the baseline, with at least one strictly better metric. The evaluator returns an
`ApprovedModel` bound to the candidate, training provenance, and evaluation
evidence. A tie or worse metric leaves the baseline preferred. This small-sample
gate is a conservative engineering policy, not proof of generalization. Rejected
model workers are closed and their fitted context released.

## TabPFN runtime and availability

The adapter implements actual local `TabPFNRegressor` and `TabPFNClassifier`
inference, SDK **9.1.0**, with explicit **v2 default** checkpoint selection.
TabPFN is an optional runtime: the feature/baseline/service path works without
the SDK or PyTorch. It uses no hosted TabPFN client and sends no history to a
provider.

Optional CPU setup, from the repository root:

```text
.venv/bin/python -m pip install --index-url https://download.pytorch.org/whl/cpu torch==2.14.1
.venv/bin/python -m pip install -r ml/requirements-tabpfn.txt
```

The optional contract pins TabPFN, PyTorch, and the patched setuptools version.
Transitive dependencies must be audited in the installed runtime. CPU wheel
`2.14.1+cpu` is matched to its `2.14.1` release for the pinned-release audit.

Supply `TabPFNConfig` to the offline `TabPFNTrainer`: existing absolute local
regressor/classifier `.ckpt` paths and expected SHA-256 hashes. These are trusted
operator configuration, never upload paths or browser-selected models. Checkpoint
files must be regular, nonsymlink final paths, nonempty, and at most 512 MiB each.
Copies are hashed before SDK load in a private temporary directory. The SDK never
gets an `auto` path. Operator-provisioned checkpoints are trusted executable model
artifacts; matching a hash does not make an arbitrary user-uploaded checkpoint
safe. Models and fitted-state files are excluded from Git.

For the tested v2 defaults:

| Artifact | Upstream source | SHA-256 |
| --- | --- | --- |
| Regressor | `Prior-Labs/TabPFN-v2-reg`, `tabpfn-v2-regressor-v2_default.ckpt` | `2ab5a07d5c41dfe6db9aa7ae106fc6de898326c2765be66505a07e2868c10736` |
| Classifier | `Prior-Labs/TabPFN-v2-clf`, `tabpfn-v2-classifier-v2_default.ckpt` | `cf8c519c01eaf1613ee91239006d57b1c806ff5f23ac1aeb1315ba1015210e49` |

Weights are separately licensed by Prior Labs; BOOH supplies neither weights nor
an automatic download/license-login flow. The v2 defaults were explicitly chosen
instead of SDK `auto`, which currently selects a different model family.
Provision exact reviewed artifacts before enabling the local runtime.

The worker uses a spawned process with a cleared environment, private working
directory, offline Hub/telemetry settings, blocked Python IPv4/IPv6 socket
creation, suppressed stdout/stderr/logging, one CPU thread, fixed seed 0, two
estimators, and deterministic Torch operations. These controls isolate the trusted
SDK; deployment network isolation remains an operating-system control. No GPU
or hosted-provider fallback is silently enabled. Limits: two live workers per
process, 4 GiB address-space budget per worker, 120-second fit deadline (maximum
180), and 10-second prediction deadline (maximum 30). A timeout/crash terminates
the worker, deletes temporary checkpoint copies, and returns worker capacity.
Call `TabPFNModel.close()` on approved models when replacing/deleting them.
Fit state remains in process memory until closure. TASK-011 now provides bounded
owner/baby registry leases, revision-bound offline installation, mutation/deletion
invalidation, seven-day expiry, replacement close, and application shutdown close.
Deployment must coordinate multi-process invalidation/account deletion; see
`docs/prediction-api.md`.

## Production selection and fallback policy

The service always computes a valid baseline first. TabPFN is used only when its
artifact passed the held-out gate, matches the selected baby and feature/model
versions, is not trained/evaluated in the future, is no older than seven days
from the training cutoff, has suitable observed features, and current elapsed
sleep is within `[0, 60]` (the offline snapshot support).

Default `allow_baseline_fallback=True` returns the explicit baseline for:
`model_unavailable`, `model_not_validated`, `model_scope_mismatch`,
`model_from_future`, `stale_model`, `missing_features`, `outside_model_support`,
and `invalid_model_output`. Its `model_version` is **`baseline-7d-v1`**, never a
TabPFN label. The fixed fallback reason is available in internal metadata.

`allow_baseline_fallback=False` fails with that safe fixed reason. In either mode,
malformed/mixed-owner history, invalid context, overlapping labels, or inadequate
baseline evidence fails without a numerical result. There is no numerical LLM
fallback.

## Reproducible synthetic evaluation

Run the synthetic-only CLI without checkpoints to evaluate the baseline and
report model availability:

```text
.venv/bin/python -m ml.benchmark
```

With separately provisioned local reviewed v2 defaults:

```text
.venv/bin/python -m ml.benchmark --regressor-checkpoint /absolute/path/regressor.ckpt --classifier-checkpoint /absolute/path/classifier.ckpt
```

The CLI prints only aggregate synthetic metrics/status and closes its fitted
worker. It has no private-data import/export mode. The fixture has 42 synthetic
bouts every four hours with durations repeating `(45, 75, 90, 110, 50, 80)` and
feed/wake markers. Thirty-one bouts pass training feature readiness; five recent
bouts yield 14 held-out snapshots.

Measured twice with the real isolated CPU runtime and the hashes above:

| Model | MAE (remaining minutes) | Brier score | Held-out snapshots |
| --- | ---: | ---: | ---: |
| Deterministic seven-day baseline | 15.11203896451008 | 0.1250567942732407 | 14 |
| Actual local TabPFN regressor + classifier | 0.03270927133440692 | 0.0000007967734940994023 | 14 |

TabPFN passed both metrics on this deliberately simple repeating pattern. This
verifies integration, isolation, causal splitting, and scoring; it does **not**
establish accuracy, calibration, medical suitability, or superiority on real
families' histories. Each baby's real authorized model context must pass its own
held-out evaluation or the service retains the baseline.

## Numerical/LLM privacy boundary

Gemma is absent from all model, training, evaluation, and production numerical
dependencies. No prompt, LLM response, note, generated explanation, or text
provider output is accepted as a prediction. The immutable numerical contract
is produced first; a later summary layer may describe it without mutation.

Only selected-baby numerical feature/target arrays and minimal training provenance
enter the local SDK worker; raw event records and imported free text do not.
Raw histories and provider/model errors are never logged or echoed. Artifact,
history, feature, and prediction representations omit personal values. Tests
cover finite/range checks, sparse/missing data, causal splits/labels, distinct
groups, both metrics and promotion/rejection, SDK API/classes/shapes, unavailable
dependencies, local path/hash validation, socket guards, worker capacity/timeout
cleanup, scope/staleness, fail-closed/fallback, silence/privacy, immutability,
and the absence of LLM/training/evaluation dependencies in production inference.
