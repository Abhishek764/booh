# BOOH Project Context

## Purpose

BOOH is a privacy-conscious nighttime dashboard for new parents. It learns from
the user's own baby sleep, feed, and wake history to answer: “When is the next
wake-up likely, and roughly how much time do I have?” Predictions are advisory,
uncertain, and not medical advice.

## Current Phase

Phase 1 — Authorized history and ML feature foundation. The repository foundation,
PostgreSQL/Alembic schema, Next.js application boundary, and OAuth/session
authorization are complete. Baby-owned event tracking and the bounded CSV import
API are implemented. The database includes events, predictions, summaries, and
external audio references. The independent, versioned numerical feature service
is implemented. The next dependency-ready milestone is the explicit deterministic
seven-day baseline and its sparse-history evaluation.

## Hacktoberfest 2026 challenge context

The immediate external goal is Hacktoberfest 2026 Challenge 1, “Build for a
Friend.” The supplied challenge announcement requires a real project built for
one real person, with open-source AI materially involved, and a DEV write-up
showing the person, demo, process, and why open innovation matters. The stated
submission deadline is October 5, 2026 at 06:59 UTC.

Honest status: BOOH is currently a foundation, not a valid submission. It has a
strong privacy and new-parent problem statement, but it does not yet have a
working prediction flow, open-source AI feature, usable dashboard, friend test,
or submission evidence. Secure OAuth is valuable engineering but is not by
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
database. No production data exists. All user-scoped access will enforce the
authenticated ownership path.

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

TabPFN is planned for user-history prediction after feature and data boundaries
are established. A deterministic seven-day baseline is required first and must
remain explicit, reproducible, and evaluated for sparse histories.

## LLM

Gemma is planned only for short summaries of validated predictions. It will not
make predictions, authorize access, query the database, or provide medical
advice. Prompt minimization and output validation are required.

## TTS

ElevenLabs is planned behind a provider/service abstraction. Audio generation,
provider calls, storage, retention, and failure handling are not implemented.

## API

The public API prefix is `/api/v1`. The current routes are `GET /health`,
`GET /auth/google`, `GET /auth/google/callback`, `POST /auth/logout`,
authenticated `GET /auth/me`, and authenticated baby CRUD routes under
`/babies`, plus authenticated event collection/mutation routes under
`/babies/{baby_id}/events` and `/events/{event_id}`, plus the authenticated CSV
import route `/babies/{baby_id}/imports`. Auth, baby, event, and import routes
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
  feature completion commit). The roadmap task remains open for the baseline.

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

## Known Risks

- User sleep and feed histories are sensitive household data.
- Sparse or irregular event histories can produce misleading confidence.
- Feature observation span does not establish logging completeness; the sparse
  quality heuristic is not model confidence. Incomplete sleeps contribute no
  inferred duration, and future baseline policy must preserve these distinctions.
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
- ML and generated summaries must not be interpreted as medical guidance.
- Frontend browser state is limited to the display theme until authenticated
  domain state is introduced behind the API service boundary.
- Google OAuth uses a fixed callback allowlist and never accepts browser-chosen
  redirect destinations.

## Current TODO

- Complete TASK-008's explicit deterministic baseline and sparse-history
  evaluation using the versioned feature boundary before TabPFN.
- Integrate bounded, owner-authorized history retrieval with the baseline; include
  completed sleep intervals that overlap the feature window.

## Last Completed Task

`TASK-008` feature-engineering slice — independent, versioned numerical features
from normalized history, with explicit missingness, provenance, UTC/local time
semantics, privacy/scope validation, and edge-case unit tests.

## Last Commit

`feat: add sleep prediction feature engineering` — local completion commit carrying
this context and the ML-agent result.

## Last Security Review

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
stateless calls, and a standard-library-only dependency boundary. All 244
backend/ML tests pass; targeted Ruff and strict ML mypy checks pass. This feature
adds no runtime dependency; the prior pinned dependency audit reported no known
vulnerabilities. No CRITICAL or HIGH findings were identified.

## Next Recommended Task

`TASK-008` baseline slice — implement and evaluate the explicit deterministic
seven-day baseline using the completed authorized event/import and feature
boundaries. Keep sparse-history policy explicit before TabPFN.
