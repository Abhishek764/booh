# BOOH Project Context

## Purpose

BOOH is a privacy-conscious nighttime dashboard for new parents. It learns from
the user's own baby sleep, feed, and wake history to answer: “When is the next
wake-up likely, and roughly how much time do I have?” Predictions are advisory,
uncertain, and not medical advice.

## Current Phase

Phase 1 — Authenticated prediction pipeline. The repository foundation,
PostgreSQL/Alembic schema, Next.js application boundary, and OAuth/session
authorization are complete. Baby-owned event tracking and the bounded CSV import
API are implemented. The database includes events, predictions, summaries, and
external audio references. The independent, versioned numerical feature service
is implemented, along with the explicit seven-day baseline, local optional TabPFN
adapter, offline held-out evaluation, and safe production numerical inference.
The standalone guarded Gemma summary service is implemented and verified.
The layered authenticated prediction POST/GET API now retrieves bounded owned
history, runs numerical features/model/baseline, persists results, and integrates
guarded summaries. The next dependency-ready milestone is bounded ElevenLabs audio.

## Hacktoberfest 2026 challenge context

The immediate external goal is Hacktoberfest 2026 Challenge 1, “Build for a
Friend.” The supplied challenge announcement requires a real project built for
one real person, with open-source AI materially involved, and a DEV write-up
showing the person, demo, process, and why open innovation matters. The stated
submission deadline is October 5, 2026 at 06:59 UTC.

Honest status: BOOH is currently a foundation, not a valid submission. It has a
strong privacy and new-parent problem statement, but it does not yet have a
usable dashboard, friend test, deployed/live Gemma verification,
or submission evidence. An authenticated numerical/summary backend is implemented;
secure OAuth is valuable engineering but is not by
itself evidence of meeting this challenge.

Challenge scope decision:

- Freeze additional OAuth work while the challenge slice is considered.
- Build only a narrow end-to-end slice if a real friend is available to test it:
  authorized local event input, the explicit deterministic seven-day baseline,
  one meaningful open-weight model feature, uncertainty-aware presentation, and
  a short friend feedback loop.
- Do not claim that an open model made the prediction if it only summarizes a
  validated prediction. The current Gemma policy remains: short validated
  summaries only, with no authorization, database decisions, medical advice,
  or invented certainty.
- Do not commit real family data. Use consented local data for a demo and
  synthetic data for tests and repository artifacts.
- If no real friend can test the result in the timebox, do not pretend BOOH
  satisfies “Build for a Friend”; preserve the project for a later, stronger
  submission instead.

Before implementing this slice, start an explicit task that resolves whether
the open-weight model is a meaningful approved model component or only a
bounded summary feature. The deterministic baseline must remain the explicit
comparison and safety boundary.

## Architecture

```text
API routes
    ↓
Services
    ↓
Repositories / data access
    ↓
PostgreSQL via SQLAlchemy

Prediction API
    ↓
Feature service
    ↓
Prediction model
    ↓
Deterministic seven-day baseline
```

External providers such as Google OAuth and ElevenLabs will be accessed only
through provider/service abstractions. Routes remain thin.

## Tech Stack

- Frontend: Next.js, React, TypeScript
- Backend: FastAPI, Python
- Database: PostgreSQL
- ORM: SQLAlchemy
- Migrations: Alembic
- Authentication: Google OAuth
- ML: TabPFN plus a deterministic seven-day baseline
- LLM: Gemma for short natural-language summaries only
- TTS: ElevenLabs
- Deployment: Docker and Render
- Data import: Huckleberry CSV
- Testing: pytest plus frontend testing
- API versioning: `/api/v1`

## Repository Structure

```text
backend/       FastAPI, services, repositories, database integration
frontend/      Next.js, React, TypeScript client
ml/            Feature definitions, baseline, and model adapters
tests/         Cross-layer and integration test support
docs/          Design and operational documentation
.agent/        Agent result files and collaboration records
AGENTS.md      Project-wide engineering rules
CONTEXT.md     Persistent project memory
SECURITY.md    Security policy and review baseline
TASKS.md       Dependency-aware task board
```

## Database

PostgreSQL is the production database target, accessed through SQLAlchemy with
Alembic migrations. The schema includes provider-neutral `users` and
`user_identities`, user-owned `babies`, baby-owned `events` and `predictions`,
prediction-linked `summaries`, and summary-linked external `audio` references.
Events support sleep/feed/wake types, UTC start/end times, duration, and feed
amount where applicable. Predictions retain explicit baseline/model/feature
versions and bounded feature metadata. Audio bytes are stored outside the
database. No production data exists. Prediction persistence enforces authenticated
baby ownership at snapshot/initial commit/summary finalization/list boundaries.
Migration `0004_prediction_probability` changes four-decimal wake probability to
double precision to preserve the numerical float across POST, GET, and summaries;
rollback restores the historical lossy format. Initial numerical + local-summary
writes are atomic, provider calls happen after commit, and final summary writes
cannot assign numerical fields. Baby deletion cascades outputs. Details and
migration/retention verification are in `docs/prediction-api.md`.

## Authentication

Google OAuth is implemented behind a provider abstraction. Canonical routes are
`GET /api/v1/auth/google`, `GET /api/v1/auth/google/callback`,
`POST /api/v1/auth/logout`, and `GET /api/v1/auth/me`. The authorization-code
flow uses PKCE, fixed HTTPS provider endpoints, signed short-lived state cookies,
server-side one-use transactions, validated issuer/audience/signature/nonce/
claims, provider-neutral `(issuer, subject)` identity persistence, opaque
server-side sessions, secure cookies, exact-origin credentialed CORS,
session-bound CSRF, session rotation, idle/absolute expiry, and logout
revocation. Google client secrets and provider tokens remain server-side. Live
Google service testing remains pending.

## Data Import

`Importer` now has independent `HuckleberryImporter` and `GenericEventImporter`
adapters, exposed through authenticated, CSRF-protected
`POST /api/v1/babies/{baby_id}/imports`. The endpoint accepts raw UTF-8 CSV bodies
with allowlisted MIME types and optional validated filename metadata; it never
stores uploads on disk. The importer detects columns, parses dates with an
explicit slash-date order, uses the owned baby timezone unless overridden,
normalizes events to UTC, and reuses event policy/DST validation.

Default budgets are 2 MiB and 10,000 rows, with hard ceilings of 10 MiB and
10,000 rows. Cells, logical records, columns, errors, receiving time, and concurrent
imports are also bounded. Formula/control injection is rejected even in ignored
text. Only normalized event fields are persisted; free text is discarded and CSV
contents are never executed, logged, or sent to Gemma or another provider.

Summaries report `rows_processed`, `rows_imported`, `rows_skipped`, `rows_failed`,
`duplicates`, and bounded line-number/code `errors`, plus `errors_truncated`.
Semantic duplicates are detected within a file and against existing manual or
imported events for the same owned baby. PostgreSQL baby-row locks serialize
import transactions. File-level corruption/budget violations abort before writes;
invalid event rows are reported and valid rows commit atomically. Original bytes
are request-scoped; normalized events use the existing authorized event/baby
deletion path. Supported schemas and synthetic fixture assumptions are documented
in `docs/imports.md`. Real CSV exports and baby data must never enter the repo.

## ML

`ml.features.FeatureService` is a deterministic standard-library-only component
that consumes normalized, single-baby history plus an explicit aware `as_of`,
IANA timezone, and optional date of birth. It accepts the repository event-record
projection or the minimal offline `HistoryEvent` DTO; it does not import backend,
FastAPI, HTTP/request, repository, or model code. Callers retrieve authorized
history, and the feature layer validates every record's baby scope.

`sleep-history-v1` defines a fixed, validated 13-float vector: local hour, minutes
since feed, last completed sleep duration, mean of the latest three completed
sleeps, rolling 12/24-hour sleep, latest explicit inter-wake interval, recent
feed/sleep counts, day of life, night indicator, incomplete sleep count, and
observation span. Units/order/bounds and every feature are in `docs/features.md`.
Missing timing/age uses `-1.0` plus explicit missing-feature metadata. Empty,
first-event, and sparse histories return finite vectors with a conservative
`insufficient_history` flag rather than invented observations or confidence.

Windows use elapsed UTC time; local hour, night/day (19:00–07:00), and zero-based
day of life use the supplied timezone. Input is bounded to 10,000 records and
seven-day feature eligibility, with overlapping completed sleeps retained at the
window boundary. Rolling sleep measures the union of clipped completed intervals.
Unclosed/not-yet-completed sleep has no inferred duration; future completions are
masked before duplicate handling to prevent retrospective feature leakage.
Malformed records fail with fixed private-data-free errors. The service is
stateless, has no logging/output/provider calls, and omits sensitive values from
automatic DTO/vector/metadata representations. All 93 synthetic ML tests pass.

`ml.prediction.service.PredictionService` now composes `FeatureService`, an
evaluated optional `TabPFNModel`, and explicit `BaselineModel`. It returns
remaining `expected_sleep_minutes`, `wake_probability_60m`, `baseline_minutes`,
and an honest selected `model_version`; Gemma never computes or modifies these
numbers. It consumes already authorized history, validates selected-baby scope,
and is independent of FastAPI/persistence. TASK-011 now composes this engine behind
the authenticated HTTP resource/lifecycle boundary.

`baseline-7d-v1` uses unique, positive, nonoverlapping sleep bouts completed in
the preceding seven elapsed days. For elapsed sleep e, use historical d > e:
mean(d - e) and fraction(d - e <= 60). Three surviving independent samples are
required; missing evidence fails safely with `insufficient_history`.

`ml.training` and `ml.evaluation` are offline-only. Snapshots at 0/30/60 elapsed
minutes use causal features, with completion targets kept separate. The latest
five whole bouts are held out (5–16 configurable); training labels must be known
by the first holdout start. Limit to 64 bouts/192 snapshots and 10,000 input
events; require 20 eligible training bouts and three rows of each binary class.
The prediction matrix is the original 13 features plus elapsed minutes, version
`sleep-remaining-v1`. Only missing optional age is eligible for TabPFN.

The actual local SDK uses TabPFN 9.1.0's regressor and classifier, explicit v2
default checkpoints, CPU, seed 0, and two estimators. Checkpoints are locally
operator-provisioned and SHA-256-verified; no runtime download, hosted inference,
Gemma, or provider transfer occurs. A spawned worker has a sanitized environment,
offline/socket guards, silent logs/output, 4-GiB address-space budget, bounded
fit/predict deadlines, and two-worker concurrency cap. Optional runtime pins are
in `ml/requirements-tabpfn.txt`; baseline/features work without that environment.

Promotion requires non-worse held-out MAE and Brier, with at least one strictly
better, and binds the fitted candidate to baby/training/evaluation provenance.
Inference never fits/evaluates. It rejects foreign/future/stale artifacts, missing
features, unsupported elapsed time, and malformed/NaN/infinite output. Default
fallback is explicitly labeled `baseline-7d-v1`; fail-closed mode is available.
Fitted context stays only in the worker until close. TASK-011 supplies a two-model
owner/baby-keyed registry with serialized inference/replacement, revision-bound
offline-approved installation, failed/stale/mutated-artifact close, seven-day expiry,
baby deletion and profile/event/import invalidation, owner clear, and shutdown
close. No fitting/evaluation/model upload occurs in HTTP. Deployment must coordinate
invalidation across processes and direct/account database deletion.

Real isolated CPU evaluation on the repeating synthetic 42-bout fixture (31
eligible training bouts, five held-out bouts/14 snapshots) measured baseline MAE
15.11203896451008 minutes / Brier 0.1250567942732407 versus TabPFN MAE
0.03270927133440692 / Brier 0.0000007967734940994023, reproduced twice. This
verifies synthetic integration, not real-family accuracy/calibration. Each baby's
model must pass its own held-out gate. Details, checkpoint hashes, fallback
semantics, metrics, and reproducible commands are in `docs/predictions.md`.

## LLM

`backend.app.services.summaries.SummaryService` implements standalone short
summaries of already validated numerical predictions. It projects exactly three
finite bounded numeric fields: expected remaining minutes, wake probability
within 60 minutes, and baseline minutes. Identity, history, imported text, ages,
timestamps, numerical model versions, and feature metadata never enter prompts.

`GemmaProvider` uses fixed system instructions and delimited numeric JSON through
an operator-configured OpenAI-compatible Gemma endpoint. It has no tools, database
access, or numerical authority. `OutputValidator` accepts only strict one-to-three
sentence JSON and reviewed exact source-grounded wording, bounded to 300 text
characters. It rejects fabricated values/facts, advice, guarantees, instructions,
private text, markup, Unicode/control smuggling, and malformed/oversized output.
Provider/configuration/validation failures produce deterministic local summaries
without changing the numerical result. Invalid input produces a nonnumeric
unavailable summary without calling a provider.

The default provider is disabled. Enabled configuration requires an explicit
approved APP_ENV; hosted use requires HTTPS and staging/production require a
credential. Public DNS/IP pinning, original-host TLS, no proxies/redirects/retries,
four service/transport slots, five-second await/four-second socket budgets, and
8-KiB response limits bound calls. System resolver stalls remain bounded by four
workers but require operator resolver deadlines. The service has no persistence,
caching, or private-data logging; summary/requested-model/outcome metadata is
internal. Hosted handling/retention review and live Gemma verification precede
production use. Contracts and verification are in `docs/summaries.md`.
The authenticated pipeline now calls summaries only after numerical/local-summary
commit. It revalidates returned text independently and persists summary-only fields;
Gemma failure returns the original numbers with grounded local text. Summary-write
failure returns 503 and preserves the committed local fallback for GET.

## TTS

ElevenLabs is planned behind a provider/service abstraction. Audio generation,
provider calls, storage, retention, and failure handling are not implemented.

## API

The public API prefix is `/api/v1`. The current routes are `GET /health`,
`GET /auth/google`, `GET /auth/google/callback`, `POST /auth/logout`,
authenticated `GET /auth/me`, and authenticated baby CRUD routes under
`/babies`, plus authenticated event collection/mutation routes under
`/babies/{baby_id}/events` and `/events/{event_id}`, plus the authenticated CSV
import route `/babies/{baby_id}/imports`, plus `POST /babies/{baby_id}/predict`
and `GET /babies/{baby_id}/predictions`. Auth, baby, event, import, and prediction routes
remain thin and delegate to services,
repositories, and provider abstractions. Baby repository queries always include
the authenticated owner predicate; baby responses do not expose `user_id`.
Requests reject unknown fields, client-supplied ownership fields, malformed IDs,
invalid dates/timezones, and oversized bodies.

Event tracking is implemented under the baby ownership boundary. The event API
supports sleep, feed, and wake records, accepts aware timestamps or unambiguous
local timestamps with a validated IANA timezone, stores normalized UTC values,
and rejects impossible relationships. Event mutations require the session-bound
CSRF proof and exact configured frontend origin. No ML or prediction behavior is
part of event tracking.

Prediction POST requires live auth, session-bound CSRF, and exact origin, and checks
ownership before consuming an empty/strict JSON `{}` body. Server UTC time and owned
baby/history define context; no client numerical/as-of/host/model overrides. Input
is bounded to 1 KiB/five-second receiving time; unknown fields fail. History queries
include owner joins, future-start exclusion, overlapping/duration-only window sleeps,
and a 10,001-row sentinel to reject histories over 10,000. Active sleep elapsed is
derived from the latest unclosed sleep without a later wake; otherwise forecast at
bout start. Insufficient/invalid history never produces manufactured numbers.

POST returns 201 with id/baby/time, expected minutes, wake probability, baseline,
versions, honest used-baseline flag, summary, and summary-fallback flag. GET returns
the same stored shape with bounded limit (1–100)/offset (0–10,000), stable descending
time/id order, and no ML/provider calls. Stored text/numbers are revalidated. Four
service and four actual-worker slots, a 45-second await budget, and ten generations
per owner per minute bound production work. Private no-store/no-referrer/nosniff
headers cover the baby surface. All errors are fixed and private-data-free.
Snapshot revision/ownership checks and coordinated PostgreSQL baby locks prevent
writing an outdated result across profile/history changes; conflicts return 409.
API contracts, persistence failures/races, lifecycle, and security review are in
`docs/prediction-api.md`.

## Frontend

Next.js, React, and TypeScript now provide a dark-first, mobile-first shell with
large nighttime typography, keyboard navigation, skip-link/error/loading/not-
found boundaries, a display-only theme preference, and reusable components.
The browser makes no API calls in the shell, receives no provider secrets, and
does not access the database or implement prediction policy. Domain dashboard
behavior remains a later task.

## Deployment

Docker and Render are planned. No container, deployment manifest, or runtime
environment has been implemented.

## Security

`SECURITY.md` is the governing policy. `CRITICAL` and `HIGH` security findings
block completion. The initial foundation review covers repository hygiene,
secret exclusion, ownership rules, and documentation boundaries.

## Privacy

BOOH must collect and retain the minimum data needed for a user's predictions.
User histories must remain isolated, logs must be redacted, and real family or
baby data must not be used in development fixtures, tests, examples, commits,
or agent result files.

## Environment Variables

Names only; values must never be stored here:

- `APP_ENV`
- `LOG_LEVEL`
- `API_V1_PREFIX`
- `DATABASE_URL`
- `SECRET_KEY`
- `FRONTEND_ORIGIN`
- `SESSION_COOKIE_NAME`
- `SESSION_COOKIE_SECURE`
- `SESSION_COOKIE_SAMESITE`
- `GOOGLE_OAUTH_CLIENT_ID`
- `GOOGLE_OAUTH_CLIENT_SECRET`
- `GOOGLE_OAUTH_REDIRECT_URI`
- `GOOGLE_OAUTH_ISSUER`
- `ELEVENLABS_API_KEY`
- `ELEVENLABS_VOICE_ID`
- `GEMMA_PROVIDER`
- `GEMMA_BASE_URL`
- `GEMMA_MODEL`
- `GEMMA_API_KEY`
- `MAX_UPLOAD_BYTES`
- `MAX_IMPORT_ROWS`

## Completed Tasks

- `TASK-001` — repository engineering foundation (`a335d75`).
- Roadmap `TASK-002` — PostgreSQL schema and Alembic workflow (`2779601`).
- Roadmap `TASK-003` — application boundary and frontend scaffold (`3d7c696`).
- Roadmap `TASK-004` — Google OAuth, sessions, and authorization boundary
  (local completion commit for this milestone).
- Secure Google OAuth follow-up — canonical routes, exact-origin CORS, and
  explicit callback/session security tests (current local commits).
- Database foundation expansion — babies, events, predictions, summaries, and
  external audio references (current local commit).
- Frontend foundation — responsive nighttime shell, accessible boundaries, and
  deterministic browser checks (current local commit).
- `TASK-005` — authenticated baby management API with owner-scoped CRUD and
  strict request validation (current local commit).
- `TASK-006` — authenticated event tracking with UTC normalization, bounded
  validation, and cross-user authorization tests (current local commit).
- `TASK-007` — secure Huckleberry/generic CSV import, owner-scoped deduplication,
  transactional persistence, bounded summaries, and synthetic security tests
  (local importer completion commit).
- `TASK-008` feature-engineering slice — independent, versioned numerical feature
  service with validated vectors and deterministic edge/privacy tests (local
  feature completion commit `a56e491`).
- `TASK-008` baseline/evaluation completion and `TASK-009` — explicit seven-day
  baseline, real local TabPFN, causal whole-bout heldout MAE/Brier evaluation,
  and production numerical service with safe fallback (local engine commit).
- `TASK-010` — standalone guarded Gemma summary provider/service, minimized numeric
  prompts, strict grounded output validation, deterministic fallback, and synthetic
  provider/privacy/security coverage (local summary completion commit).
- `TASK-011` — authenticated owner-scoped prediction POST/GET pipeline, exact
  numerical persistence, guarded summary integration, bounded approved-model
  lifecycle, probability migration, and privacy/failure/security tests (local
  prediction API completion commit).

## Engineering Decisions

- Keep domain work dependency-ordered and preserve isolated ownership by agent.
- Enforce layered backend and prediction architecture.
- Use provider/service abstractions for external systems.
- Keep the deterministic seven-day baseline explicit before TabPFN.
- Restrict Gemma to validated, short summaries.
- Use names-only environment examples and prohibit secrets in Git.
- Track work through dependency-aware IDs in `TASKS.md`.
- Enforce baby ownership in repository predicates rather than filtering after
  loading resources.
- Normalize event timestamps to UTC only after validating the supplied timezone;
  reject ambiguous or nonexistent local times.
- Receive CSV as a bounded raw body rather than multipart or disk-backed uploads;
  retain only typed events, never original files or imported free text.
- Keep provider adapters separate from upload orchestration and repositories;
  share persistence-independent normalized values across event tracking/import.
- Reject unknown/ambiguous columns and require explicit locale date order. Use
  semantic, baby-scoped duplicate identity independent of event source.
- Keep ML features request-free and standard-library-only, with structural input
  records, explicit as-of context, scope checks, and no persistence/provider work.
- Version feature order, units, windows, validation bounds, and missingness.
  Treat observed zeros as lower bounds, not proof of complete history.
- Exclude incomplete/future-completed sleeps from durations and mask future ends
  before deduplication; merge completed intervals for rolling elapsed sleep.
- Keep numerical prediction completely separate from LLM summaries, and offline
  fitting/evaluation completely separate from production inference.
- Promote a selected baby's fitted TabPFN only after chronological evaluation
  beats/equalizes both baseline metrics and strictly improves at least one.
- Use explicit local v2 checkpoints and verified hashes; no automatic model
  downloads/hosted-family-data transfer. Identify baseline fallback honestly.
- Keep Gemma as a standalone optional summary provider after numerical validation.
  Project only three numeric fields; reject unknown/text inputs before provider
  use. Use a reviewed closed output grammar and exact source grounding instead
  of relying on a medical/injection keyword blacklist.
- Use deterministic local summaries when generation is disabled/unavailable or
  output is rejected, without altering numerical predictions. Keep host/model
  selection operator-owned and provider versions/outcomes in internal metadata.
- Persist immutable numerical results and deterministic local summary together
  before provider calls, then update only validated summary text/internal outcomes.
  Recheck ownership and snapshot revision; preserve fallback records if final
  summary persistence fails. Preserve model probability with double precision.
- Keep prediction context server-owned and model fitting offline. Require current
  owner/baby/revision/evaluation bindings for installed models; invalidate on
  profile/history changes, deletion, expiry, failure, and application shutdown.

## Known Risks

- User sleep and feed histories are sensitive household data.
- Sparse or irregular event histories can produce misleading confidence.
- Feature observation span does not establish logging completeness; the sparse
  quality heuristic is not model confidence. Incomplete sleeps contribute no
  inferred duration, and baseline/model consumers must preserve these distinctions.
- Synthetic TabPFN benchmark success is not evidence of real-family performance.
  Small held-out samples and empirical baseline frequencies remain uncertain.
- Checkpoints are trusted operator artifacts, not uploads. Fitted context remains
  in memory; TASK-011 implements process-local ownership/replacement/deletion/expiry.
  Multi-process invalidation, direct/admin account deletion, and OS-level egress/
  capacity require devops/security coordination (TASK-015/TASK-017) before family use.
- OAuth/session implementation can create account-linking or IDOR risks; the
  completed boundary is covered by deterministic tests but needs live-service
  and deployment review.
- Legacy event migration uses a UTC baby profile when pre-baby events exist;
  product/API work must provide an explicit profile and timezone workflow for
  new baby records.
- CSV parsing and LLM inputs are untrusted boundaries.
- CSV compatibility is verified with synthetic allowlisted schemas. Additional
  provider export/locale variants need reviewed aliases and regression fixtures;
  PostgreSQL concurrent-import locking needs later live-service verification.
- Per-process import budgets are implemented; deployment-wide rate limits and
  backup retention remain deployment/security work.
- Provider availability, cost, and data handling need review before integration.
- Live Gemma/weights verification and hosted retention review are pending. Python
  cannot forcibly interrupt system DNS; resolver stalls can occupy four transport
  slots until resolution returns (devops, TASK-017). The service await still falls
  back within five seconds. Deployment-wide egress/rate limits remain TASK-017.
- Repository-wide Ruff reports 22 pre-existing lint findings in older backend
  files; TASK-010's six new files pass scoped checks (qa, TASK-016).
- Prediction database/worker operations have four actual-worker slots and finite
  coroutine budgets, but Python cannot forcibly cancel a DB commit/statement.
  Deployment must configure DB connect/statement/lock deadlines and cluster-wide
  rate/invalidation controls (devops, TASK-017). A timed-out POST after commit can
  retain its safe fallback record; POST is not idempotent. PostgreSQL live-lock/
  migration behavior needs operational verification beyond synthetic/DDL tests.
- ML and generated summaries must not be interpreted as medical guidance.
- Frontend browser state is limited to the display theme until authenticated
  domain state is introduced behind the API service boundary.
- Google OAuth uses a fixed callback allowlist and never accepts browser-chosen
  redirect destinations.

## Current TODO

- Implement TASK-012's fixed-provider, bounded authorized ElevenLabs audio flow.
- Verify live Gemma/hosted retention, PostgreSQL locking/migration, and trusted
  offline model installation in the operational environment.
- Coordinate multi-process model invalidation/deletion, DB/resolver deadlines,
  cluster-wide rates/egress, and account-deletion hooks before production family use.

## Last Completed Task

TASK-011 — authenticated prediction API with owner-scoped history, numerical
model/baseline validation, persistence, guarded summaries, and model lifecycle.

## Last Commit

`feat: add prediction API pipeline` — local completion commit carrying
this context and the backend-agent result.

## Last Security Review

TASK-011 complete boundary review: session/CSRF/origin, cross-user/foreign/deleted
babies, ownership before body/history/ML and repeated writes, bounded strict input/
queries/history, UTC overlaps/active context, parameterized SQL, locking/revision
conflicts, atomic rollback, immutable source values, validated model output/baseline
fallback, malicious/failing Gemma and stored text, private errors/logs/headers,
offline-only evaluated-artifact installation, evidence/revision/capacity/replacement/
expiry/deletion/shutdown, cancellation/timeouts, migration child preservation/
precision/rollback/PostgreSQL DDL, and dependencies. All 604 backend/ML tests pass
(89 added); scoped Ruff on 19 changed Python files, strict six-file mypy, dependency
consistency and indexed-runtime/pinned-release audits pass. No CRITICAL/HIGH feature
findings remain. Documented deployment items above have devops/security owners and
TASK-015/TASK-017 targets. CPU-specific Torch wheel is unindexed; base release checked.

TASK-010 standalone summary review: minimized three-scalar prompts, closed grounded
output grammar, injection/advice/exfiltration/Unicode rejection, exact probability
formatting, immutable independent copies, silent errors/representations, safe
fallback, missing configuration, provider timeout/concurrency/cancellation,
DNS/IP/TLS pinning, no proxy/redirect/retry use, actual response byte limits, and
trickled-header shutdown. All 180 added tests and all 515 backend/ML tests pass.
Scoped Ruff and strict mypy pass; dependency consistency and indexed-runtime/
pinned-release audits pass. The CPU-specific Torch wheel is unindexed by
pip-audit; its matching pinned base release was checked. No new dependencies,
migrations, or CRITICAL/HIGH feature findings. Live Gemma and authenticated
integration remain the next applicable provider/API work.

Secure OAuth and baby authorization review: backend tests cover canonical route
checks, invalid state/callbacks, expired sessions, unauthenticated requests,
cookies, CSRF, exact-origin CORS, open redirects, provider validation, baby
owner isolation, malformed IDs, strict request fields, invalid dates/timezones,
bounded bodies, event ownership/list pagination, event type and timestamp
validation, duration/feed rules, CSRF-protected mutations, upload streaming/row/
cell/record/column budgets, filename traversal, MIME/encoding, formula/control
injection, malicious imported text, safe errors/logs, timeout/concurrency,
cross-user import isolation, semantic duplicates, transaction rollback, dependency
checks, and secret review. Feature review additionally covers fixed single-baby
scope, bounded iterables, finite/range-validated output, explicit sparse-history
metadata, future-label exclusion, silent/private errors and representations,
stateless calls, and a standard-library-only feature boundary. Prediction review
covers causal labels/whole-bout holdout, local hash-verified checkpoint loading,
bounded SDK workers, selection/isolation/staleness, finite numerical output,
explicit baseline/fail-closed behavior, and exclusion of Gemma/fitting/evaluation
from inference. All 335 backend/ML tests pass; Ruff, strict ML mypy, compilation,
and installed dependency consistency checks pass. Dependency review fixed the
optional runtime's setuptools vulnerability by pinning 83.0.0. Installed-runtime
and pinned ML-release audits report no known vulnerabilities (pip-audit cannot
index the CPU-specific Torch wheel; its matching base release was checked).
No CRITICAL or HIGH findings remain.

## Next Recommended Task

`TASK-012` — bounded authorized ElevenLabs audio provider flow, with fixed-host
security, provider failure isolation, external storage references, and retention.
