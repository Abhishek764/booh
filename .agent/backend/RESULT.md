# Backend Agent Result

TASK: TASK-011 — authenticated prediction API pipeline
STATUS: DONE
Q&A CHECK: No blocking questions. TASK-004/008/009/010 are complete; the user
explicitly requested both endpoints, all specified failure tests, full security
review, and the completion commit.
FILES CHANGED:
- backend/app/prediction_contracts.py; backend/app/routes/predictions.py — private
  immutable projections, explicit bounded API schemas, POST/GET deserialization.
- backend/app/repositories/predictions.py — owner-joined bounded history snapshots,
  revision/lock checks, atomic prediction/local-summary persistence, summary-only
  finalization, bounded latest-summary list and stored-output validation.
- backend/app/services/predictions.py; backend/app/services/prediction_models.py —
  authenticated numerical/service orchestration, rate/worker/cancellation budgets,
  defensive summary grounding, owner/baby/revision-bound offline-approved model
  lifecycle with replacement/invalidation/deletion/TTL/owner-clear/shutdown close.
- backend/app/dependencies.py; backend/app/main.py; backend/app/middleware.py —
  authenticated lazy wiring, frozen Gemma environment, safe error handlers/routes,
  lifespan close, private baby-surface response headers/query bounds.
- backend/app/repositories/babies.py; backend/app/repositories/events.py;
  backend/app/services/babies.py; backend/app/services/events.py;
  backend/app/services/imports.py — coordinated baby mutation locks and owned
  model invalidation after profile/history/import/delete commits.
- backend/app/models.py;
  backend/alembic/versions/0004_prediction_probability_precision.py — reviewed
  Numeric→double precision migration preserving numerical floats; guarded SQLite
  batch rebuild and explicit PostgreSQL upgrade/downgrade casts.
- backend/app/summary_contracts.py — exact plain-text revalidation for orchestration
  and stored summaries without splitting decimal probability sentences.
- backend/tests/test_prediction_routes.py; backend/tests/test_prediction_security.py;
  backend/tests/test_prediction_migration.py — 89 added synthetic auth/pipeline/
  model/summary/persistence/race/privacy/lifecycle/migration cases.
- docs/prediction-api.md; docs/predictions.md; docs/summaries.md; docs/database.md;
  docs/README.md; backend/README.md; CONTEXT.md; SECURITY.md; TASKS.md;
  .agent/backend/RESULT.md — API/operational/retention/security documentation and
  durable task/project/result tracking.
API CHANGES: POST /api/v1/babies/{baby_id}/predict (201) accepts empty/JSON {} after
live session/CSRF/origin/ownership. GET /api/v1/babies/{baby_id}/predictions (200)
returns bounded stable paginated stored results. Both return numerical prediction,
source versions/used-baseline flag, validated summary/summary-fallback flag, and
resource IDs/UTC timestamp. Numerical, model, history and ownership input fields
are server-owned. Fixed private errors; no-store/no-referrer/nosniff headers.
DATABASE CHANGES: Migration 0004_prediction_probability changes historical
Numeric(5,4) probability to Float(53)/PostgreSQL double precision, preserving
the validated Python float. Existing rows cast without inventing lost precision;
downgrade is lossy. No new table/dependency. Initial prediction/local summary
transaction and authorized summary-only finalization use existing cascade schema.
TESTS:
- `.venv/bin/python -m pytest -q` — 604 passed (89 added), one existing
  Starlette/AnyIO test-client deprecation warning.
- Scoped `.venv/bin/python -m ruff check --isolated --select E4,E7,E9,F,I` on all
  19 changed Python files — passed.
- `.venv/bin/python -m mypy --strict --follow-imports=silent
  backend/app/prediction_contracts.py backend/app/repositories/predictions.py
  backend/app/services/predictions.py backend/app/services/prediction_models.py
  backend/app/routes/predictions.py backend/app/summary_contracts.py` — passed.
- Alembic migration tests: isolated upgrade/schema check/data/child preservation/
  downgrade; fail-closed SQLite FK batch guard; PostgreSQL explicit precision and
  cast DDL — passed.
- `.venv/bin/python -m pip check` — no broken requirements.
- `.venv/bin/python -m pip_audit --progress-spinner off` — no known indexed-package
  vulnerabilities; CPU-specific Torch wheel is unindexed.
- `.venv/bin/python -m pip_audit -r ml/requirements-tabpfn.txt --disable-pip
  --no-deps --progress-spinner off` — no known pinned-release vulnerabilities,
  including matching base Torch release.
SECURITY: Full session/CSRF/CORS/IDOR, bounded request/history/query, SQL/locking/
transaction, feature/model/baseline, immutable numerical/summary, stored output/XSS,
provider/config/SSRF/privacy, migration/rollback/cascade, lifecycle/deletion/race,
cancellation/rate/capacity, secrets and dependency review completed. No CRITICAL/HIGH
feature findings remain. All data paths are owner joined/rechecked; unknown client
scope/number/model/as-of/prompt overrides are rejected. No fitting/evaluation or
provider access precedes authorized history. Defensive copies/grounded reviewed
prose and summary-only repository parameters keep all numbers unchanged by Gemma.
Initial persistence failure rolls back and skips Gemma; final summary-write failure
retains committed safe text and returns fixed 503. Numerical precision is exact.
Models remain local, approved, owner/baby/revision-bound and capacity/TTL controlled;
invalidated/replaced/deleted/shutdown workers close. No raw logs/prompts/responses,
new dependencies, credentials, real baby data, or private history arrays introduced.
COMMIT: feat: add prediction API pipeline (commit containing this result)
KNOWN ISSUES: Live PostgreSQL lock/migration and live Gemma/retention verification
remain operational work. Registry/rate limits and invalidation callbacks are
process-local: multi-process/direct account deletion needs coordinated worker
erasure before retaining real family context (devops/security, TASK-015/TASK-017).
Python cannot forcibly cancel DB operations/commit; four actual-worker slots bound
outstanding work and deployment must set DB/resolver timeouts and cluster-wide
egress/rates (devops, TASK-017). A timeout/disconnect after commit can retain a safe
record; POST is not idempotent. CPU wheel audit uses matching base release. Existing
repository-wide lint debt remains qa/TASK-016. No account-deletion endpoint exists;
registry supplies clear_owner for its future coordinator.
NEXT DEPENDENCY: TASK-012 — bounded authorized ElevenLabs audio flow.

ASSUMPTIONS: Server current UTC/baby timezone/optional age and authorized events
define prediction context. Use latest unclosed sleep unless a later wake ended it;
otherwise elapsed zero. Existing engine always computes explicit baseline before
TabPFN selection. Offline-only trained/evaluated candidates install through trusted
Python integration with retained snapshot revision; disabled/missing model uses
honestly labeled baseline. No new fitting/model upload/secret configuration needed.
Cross-directory changes are required for API/persistence/schema/tests/docs/security/
governance and existing history/profile mutation lifecycle hooks. No frontend or ML
implementation files were changed. Previous backend completion: TASK-006, d81a98c.
