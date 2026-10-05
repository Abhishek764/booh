# Authenticated prediction pipeline (TASK-011)

## Endpoints

### `POST /api/v1/babies/{baby_id}/predict`

Requires a live server session, the session-bound `X-CSRF-Token`, CSRF cookie,
and exact configured `Origin`. Ownership is checked before consuming the body.
Accept an empty body or `{}` with `Content-Type: application/json`. All prediction
context is server-owned: current UTC time, baby timezone/optional birth date,
authorized events, evaluated model, and baseline. Unknown body/query fields,
including numerical values, IDs, `as_of`, model/URL selections, and notes, are
rejected. Body size is 1,024 actual bytes, independent of Content-Length; receiving
time is five seconds. Supplied bodies must be strict UTF-8 JSON objects without
duplicate keys/nonfinite constants. There is no fitting/model-upload endpoint.

Success: `201`, numerical prediction and summary in one explicit response.
Synthetic example for completed durations 45/75/90 minutes with no installed model:

```json
{
  "id": "00000000-0000-0000-0000-000000000001",
  "baby_id": "00000000-0000-0000-0000-000000000002",
  "prediction_timestamp": "2026-01-01T00:00:00Z",
  "expected_sleep_minutes": 70,
  "wake_probability_60m": 0.3333333333333333,
  "baseline_minutes": 70,
  "model_version": "baseline-7d-v1",
  "feature_version": "sleep-remaining-v1",
  "baseline_version": "baseline-7d-v1",
  "used_baseline": true,
  "summary": "About 70 minutes of sleep may remain. Timing can vary.",
  "summary_used_fallback": false
}
```

`summary_used_fallback: false` in this example means a validated synthetic Gemma
choice. Disabled/unavailable Gemma produces the deterministic three-sentence
summary and `true`. Neither summary outcome changes any numerical field.

### `GET /api/v1/babies/{baby_id}/predictions`

Requires a live session and owned baby. Returns `200` and a JSON array of the same
response objects. An owned baby with no predictions returns `[]`; missing and
foreign babies have identical `404` errors. Allowlisted query fields:

- `limit`: default 20, range 1–100.
- `offset`: default 0, range 0–10,000.

Order is descending `(prediction_timestamp, id)` for deterministic pagination.
No arbitrary filtering/sorting or client ownership fields. GET never calls ML or
Gemma; stored numerical results and summary text are revalidated. Unsafe stored
summary text is replaced locally with the grounded fallback. Invalid stored
numerical/provenance data fails with a private fixed error.

Successes/errors use `Cache-Control: no-store`, `Referrer-Policy: no-referrer`, and
`X-Content-Type-Options: nosniff` on the baby resource surface. Query strings are
bounded to 8 KiB before parsing. Exact-origin CORS and secure session rules remain
the existing authentication boundary. Internal feature metadata, sample counts,
fallback exception details, model worker state, provider versions/reasons, and
user IDs are excluded from public responses.

## Layering and history

```text
Session authentication and POST CSRF/origin validation
    ↓
Owned baby check → bounded owner-joined UTC event snapshot
    ↓
FeatureService → approved TabPFN + explicit seven-day baseline
    ↓
Final numerical/provenance validation
    ↓
Owner/revision-checked prediction + local summary transaction
    ↓
Minimized Gemma → strict OutputValidator → validated summary/fallback
    ↓
Owner-checked summary-only transaction → response
```

Routes deserialize/validate, call `PredictionPipelineService`, and serialize the
explicit schema. Repositories alone use SQLAlchemy/database sessions. Numerical
inference remains `ml.prediction.service.PredictionService`; features and models
never query the database or receive requests. Its valid baseline is computed
before selecting TabPFN so every successful result has an explicit baseline
comparison and safe fallback.

The snapshot query joins the authenticated baby owner in every event lookup and
fetches at most 10,001 rows, rejecting rather than silently truncating a history
over 10,000 events. It excludes future starts and includes starts within seven
days plus sleeps started before the window whose completion can overlap it.
Duration-only sleep records are retained for feature normalization, bounded by
the existing seven-day event-duration contract and a 14-day earliest start.
Projection includes only baby scope, event type, start/end, and duration: names,
free text, source/export payloads, and feed quantities are not needed by ML.

The most recent sleep is used as active context when it is unclosed/not-yet-ended
and no later explicit wake ended it. Otherwise elapsed is zero (at-sleep-start
forecast). The engine masks future completions and requires three independent
surviving completed bouts for its conditional baseline. Insufficient or overlapping
history never produces a numerical guess. See `docs/predictions.md` for targets,
feature readiness, model support, and evaluation policy.

## Persistence, numerical integrity, and races

The initial short transaction rechecks ownership and locks the baby row, reloads
the same as-of history, and compares a private SHA-256 snapshot revision. Baby
profile/event mutations and CSV imports use the same PostgreSQL baby lock. A
changed snapshot returns `409 history_changed` before creating any prediction or
calling Gemma; the client may retry. No DB lock is held during inference/provider
work. Snapshot digests, raw events, and feature arrays are not persisted.

Prediction and deterministic summary commit atomically first. Commit/insert failure
rolls both back and no Gemma call occurs. Gemma then receives an independent copy
of exactly expected minutes, probability, and baseline minutes. The orchestration
revalidates returned prose even when an injected summary service is used, against
an independent source. Summary persistence has a method with no numerical update
parameters, rechecks the owner via the baby/prediction joins, and verifies text
again. The returned numerical fields must equal the committed source.

Gemma failure is a successful prediction with deterministic local summary. If
summary persistence itself fails, POST returns a fixed `503` and the already
committed prediction/local summary remain available through GET. Similarly, a
disconnect/timeout after commit can leave that record; POST is not idempotent.
If the baby is deleted during generation, the final ownership check returns `404`
and database cascades remove prediction/summary rows. Cancellation before inference
completes prevents a subsequent numerical write; an already-running DB commit
cannot be forcibly rolled back by cancelling its coroutine.

Migration `0004_prediction_probability` changes wake probability from four-decimal
Numeric to PostgreSQL `FLOAT(53)` (double precision), preserving the validated
Python float across POST, persisted GET, and summary grounding. Existing rows are
cast without inventing lost precision. Downgrade restores the historical lossy
four-decimal representation. Apply Alembic `upgrade head` before using this API;
application code never silently migrates production. SQLite batch tests preserve
children; foreign-key-enabled SQLite parent rebuilds fail closed with a fixed
error to avoid cascade deletion. PostgreSQL uses an in-place explicit type cast.

## Optional model lifecycle

The application owns one memory-only `PredictionModelRegistry`, with at most two
owner/baby-keyed evaluated models. Default is baseline until a trusted offline
job installs an `ApprovedModel`. No runtime fit/download/evaluation is done by
POST. The trusted offline caller obtains `training_context(principal, baby_id=…)`
and retains its revision while fitting/evaluating with the existing ML workflow.
It then calls `install_evaluated_model(..., candidate=approved_model,
history_revision=snapshot.revision)`. Installation checks current ownership,
revision, baby, evaluated evidence, times, versions, and capacity under a baby-row
lock. Rejected candidates are closed, including foreign or stale-history installs.
This Python integration is not exposed to the browser.

Inference leases serialize with replacement/close; the installed local adapter
already has bounded worker predict deadlines. Failed/invalid/stale artifacts are
evicted and closed; feature/support ineligibility uses baseline without destroying
an otherwise approved model. Snapshot changes also invalidate on the next use.
Baby profile changes, event create/update/delete, and imports invalidate immediately
after commit in that application process. Baby deletion closes its worker and
cascades stored outputs. Models expire seven days after the training cutoff;
cancelled timers cannot close a replacement. Application lifespan closes all
models on shutdown. `clear_owner(owner_id)` is available for an account-deletion
coordinator; this project has no account-deletion endpoint yet.

This registry/callback model is process-local. A multi-process deployment must
coordinate invalidation/deletion across processes before retaining real family
model context; direct/admin database deletion also needs the lifecycle hook.
Owner/revision checks prevent foreign/stale inference, but do not instantly erase
idle context held by another process. This operational lifecycle belongs to
devops/security in TASK-015/TASK-017.

## Budgets and fixed failure responses

There are four in-flight pipeline/list slots per service and four actual synchronous
DB/inference workers per process; worker capacity remains occupied until work
finishes even if the caller cancels. Each owner may request ten generations per
60 seconds; the rolling limiter retains at most 1,024 active owner entries.
Foreign IDs do not allocate limiter entries. The pipeline await budget is 45
seconds. Gemma retains its five-second service/four-second socket budgets and
four transport workers. Rate/capacity configuration is not browser-controlled.

System/database calls cannot be forcibly interrupted by Python's await timeout.
Four workers bound outstanding operations; DB connect/statement/lock deadlines,
resolver deadlines, deployment-wide rates/egress, and process-wide invalidation
must be configured by the deployment owner. These are documented operational
requirements rather than an HTTP path that silently starts fitting or pools data.

| Status | Fixed codes / meaning |
| --- | --- |
| 401 | `authentication_required` — no live server session |
| 403 | Existing CSRF/origin failures |
| 404 | `resource_not_found` — missing/foreign/deleted baby |
| 400/408/413/415/422 | Invalid/oversized/slow/unsupported/unknown request input |
| 413 | `history_too_large` — bounded history exceeded |
| 422 | `insufficient_history` or `invalid_history` — no safe numerical estimate |
| 409 | `history_changed` — history/profile changed during numerical work |
| 429 | `prediction_busy` or `prediction_rate_limited` |
| 503 | `prediction_unavailable`, `prediction_timeout`, or `service_unavailable` |

Errors use `{"error":{"code":"…","message":"…"}}`, never raw exceptions,
SQL/connection strings, histories, model outputs, secrets, or provider bodies.

## Security review and verification

Review covered session/CSRF/CORS, horizontal resource isolation, query/body budgets,
SQL/query/transaction boundaries, inference/evaluation separation, model numerical
types/ranges/NaN/Infinity/booleans, baseline evidence, immutable projection and
summary grounding, stored-output validation/XSS, DNS/SSRF/provider configuration,
private logging/errors, migration/rollback, cascades, model replacement/expiry,
deletion races, cancellation, worker/rate limits, and dependencies. No new runtime
dependency or credential/real-data fixture was introduced. No CRITICAL/HIGH
findings remain in this feature review. Operational items above have devops/security
owners and TASK-015/TASK-017 targets before multi-process production family use.

- **604 tests passed**, including **89 added** pipeline/security/migration tests.
- Scoped Ruff on all 19 changed Python files and strict mypy on the six new/core
  prediction/summary implementation files passed.
- Migration upgrade/schema parity/child preservation/downgrade tests passed, plus
  PostgreSQL precision/cast DDL checks. Live PostgreSQL lock/service testing is pending.
- `pip check`, installed indexed-package audit, and pinned ML-release audit passed.
  The CPU-specific Torch wheel is unindexed; its matching base release was checked.
- One existing Starlette/AnyIO test-client deprecation warning remains. Known
  repository-wide lint debt is tracked separately in CONTEXT.md.

Provider tests use synthetic Gemma stubs/local HTTP and evaluated model stubs. The
existing engine milestone separately verified actual local TabPFN CPU inference.
Live Gemma/retention and deployed database/worker behavior still need operational
verification. Neither synthetic accuracy nor summary wording is a medical claim.
