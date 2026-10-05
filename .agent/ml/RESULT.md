# ML Agent Result

TASK: Prediction engine — TASK-008 baseline prerequisite, then TASK-009
STATUS: DONE
FILES CHANGED:
- ml/prediction/__init__.py; ml/prediction/contracts.py;
  ml/prediction/baseline.py; ml/prediction/tabpfn.py; ml/prediction/service.py —
  explicit seven-day conditional baseline, immutable numerical/provenance
  contracts, isolated local TabPFN runtime, and production PredictionService.
- ml/training.py; ml/evaluation.py; ml/benchmark.py — offline causal snapshot
  labels, chronological whole-bout holdout, MAE/Brier comparison/promotion,
  and reproducible synthetic-only real CPU benchmark.
- ml/features.py — share bounded scope-checked UTC history projection while
  preserving the existing sleep-history-v1 output contract.
- ml/requirements-tabpfn.txt — optional pinned TabPFN 9.1.0, Torch 2.14.1,
  patched setuptools 83.0.0 runtime; core baseline requires no ML dependencies.
- ml/tests/prediction_support.py; ml/tests/test_baseline.py;
  ml/tests/test_training_evaluation.py; ml/tests/test_prediction_service.py;
  ml/tests/test_tabpfn.py; ml/tests/test_prediction_privacy.py;
  ml/tests/test_feature_privacy.py — synthetic numerical/causal/privacy/runtime
  coverage and preservation of the standard-library-only feature boundary.
- docs/predictions.md; ml/README.md; CONTEXT.md; SECURITY.md; TASKS.md;
  .gitignore; .agent/ml/RESULT.md — complete targets, baseline/model selection,
  offline/runtime/trust/retention documentation, synthetic measured results,
  project/task state, model-artifact Git exclusions, and this result.
API CHANGES: N/A for HTTP. Python PredictionService.predict consumes authorized
normalized history and explicit baby/as-of/timezone/optional birth/current-sleep
context. Returns expected_sleep_minutes, wake_probability_60m, baseline_minutes,
and selected model_version, with private internal provenance/fallback metadata.
DATABASE CHANGES: N/A
TESTS:
- `.venv/bin/python -m pytest -q` — 335 passed, including 184 ML tests
  (91 additional tests for this engine milestone).
- `.venv/bin/python -m ruff check --isolated --select E4,E7,E9,F,I ml` — passed.
- `.venv/bin/python -m mypy --strict --follow-imports=silent ml/features.py
  ml/prediction ml/training.py ml/evaluation.py ml/benchmark.py` — nine files passed.
- `.venv/bin/python -m compileall -q ml`; `git diff --check` — passed.
- `.venv/bin/python -m pip check` — no broken requirements.
- `.venv/bin/python -m pip_audit` — no known indexed-runtime vulnerabilities;
  CPU-specific Torch wheel is not indexed by pip-audit.
- `.venv/bin/python -m pip_audit -r ml/requirements-tabpfn.txt --disable-pip
  --no-deps` — no known vulnerabilities in pinned TabPFN/Torch/setuptools releases.
- `.venv/bin/python -m ml.benchmark --regressor-checkpoint
  /tmp/omnirush/booh-regressor.ckpt --classifier-checkpoint
  /tmp/omnirush/booh-classifier.ckpt` — actual local CPU runtime reproduced twice:
  31 eligible training bouts, five heldout bouts, 14 heldout snapshots;
  baseline MAE 15.11203896451008 / Brier 0.1250567942732407;
  TabPFN MAE 0.03270927133440692 / Brier 0.0000007967734940994023;
  promotion status validated. Official v2 default hashes verified; checkpoint
  binaries stayed outside the workspace and were not committed.
SECURITY: No CRITICAL/HIGH findings remain. User/baby scope is validated in history,
model provenance, training payloads, evaluation, and inference. Limits bound
events, bouts, snapshots, live SDK workers, address space, and fit/predict time.
Checkpoints are trusted operator-only local regular files with verified hashes;
never uploads/auto downloads. SDK worker has sanitized environment/offline/socket
guards and suppressed logs/output; it receives numerical matrices and minimal
training provenance. Rejected
candidates/timeouts release context and temporary checkpoint copies. Production
never trains/evaluates, calls Gemma/providers, or logs raw histories. Model results
are revalidated for types/shapes/ranges/NaN/Infinity; invalid results use explicitly
identified baseline or fail closed. Baseline requires three surviving bouts;
no evidence means no fabricated numeric result. Optional installation exposed
setuptools 78.1.0 vulnerabilities; pin/update to 83.0.0 removed the findings.
COMMIT: feat: add TabPFN prediction engine (commit containing this result)
KNOWN ISSUES: Synthetic repeating-pattern accuracy is not real-family evaluation.
CPU wheel audit uses the matching base Torch release; deployers still review the
actual distribution. SDK execution is Linux/local CPU; OS-level egress/capacity
and per-baby worker deletion/replacement must integrate in TASK-011/deployment.
NEXT DEPENDENCY: TASK-011 — layered authenticated prediction API, owner-scoped
bounded history retrieval, and evaluated-artifact lifecycle.

Q&A check: no blocking questions. Dependencies were implemented in order: the
TASK-008 baseline/evaluation prerequisite passed 117 tests before TASK-009 started.
One logical prediction-engine commit combines the user-started engine components.
Cross-directory edits are required for docs, security policy, artifact hygiene,
and durable task/project tracking; no real family data or secrets were used.

ASSUMPTIONS: Predict remaining sleep and wake-within-60 from completed sleep ends.
At-bout-start forecasting uses elapsed zero; current sleep context is explicit.
Conditional baseline uses d > elapsed with three surviving independent samples.
TabPFN adds elapsed minutes to sleep-history-v1, snapshots 0/30/60, and requires
20 eligible training bouts plus binary-class variation. Hold out whole recent
bouts and require both metrics nonworse with one strictly better before promotion.
No refit on heldout labels. The fixed local v2 runtime is optional; each baby's
candidate must pass its own evaluation or the explicit baseline remains selected.

Previous completion: `a56e491` — independent feature-engineering slice.
