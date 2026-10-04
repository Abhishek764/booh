# BOOH Project Context

## Purpose

BOOH is a privacy-conscious nighttime dashboard for new parents. It learns from
the user's own baby sleep, feed, and wake history to answer: “When is the next
wake-up likely, and roughly how much time do I have?” Predictions are advisory,
uncertain, and not medical advice.

## Current Phase

Phase 1 — Authenticated domain foundation. The repository foundation,
PostgreSQL/Alembic schema, Next.js application boundary, and OAuth/session
authorization are complete. The database now includes baby-owned events,
predictions, summaries, and external audio references. The next dependency-ready
milestone is the authenticated baby resource API.

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

Google OAuth is implemented behind a provider abstraction. The authorization
code flow uses PKCE, fixed HTTPS provider endpoints, signed short-lived state
cookies, server-side one-use transactions, validated issuer/audience/signature/
nonce/claims, provider-neutral `(issuer, subject)` identity persistence, opaque
server-side sessions, secure cookies, CSRF/origin checks, session rotation,
idle/absolute expiry, and logout revocation. Live Google service testing remains
pending.

## Data Import

Huckleberry CSV import is planned but not implemented. Real CSV exports and
real baby data must never enter this repository. Import design must include
strict validation, safe temporary storage, bounded resource use, and a deletion
path.

## ML

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
`GET /auth/login`, `GET /auth/callback`, `POST /auth/logout`, and authenticated
`GET /auth/me` under that prefix. Auth routes remain thin and delegate to
services, repositories, and provider abstractions. Auth responses are bounded,
non-enumerating, and marked `no-store` where identity or flow state is present.

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
- Database foundation expansion — babies, events, predictions, summaries, and
  external audio references (current local commit).
- Frontend foundation — responsive nighttime shell, accessible boundaries, and
  deterministic browser checks (current local commit).

## Engineering Decisions

- Keep domain work dependency-ordered and preserve isolated ownership by agent.
- Enforce layered backend and prediction architecture.
- Use provider/service abstractions for external systems.
- Keep the deterministic seven-day baseline explicit before TabPFN.
- Restrict Gemma to validated, short summaries.
- Use names-only environment examples and prohibit secrets in Git.
- Track work through dependency-aware IDs in `TASKS.md`.

## Known Risks

- User sleep and feed histories are sensitive household data.
- Sparse or irregular event histories can produce misleading confidence.
- OAuth/session implementation can create account-linking or IDOR risks; the
  completed boundary is covered by deterministic tests but needs live-service
  and deployment review.
- Legacy event migration uses a UTC baby profile when pre-baby events exist;
  product/API work must provide an explicit profile and timezone workflow for
  new baby records.
- CSV parsing and LLM inputs are untrusted boundaries.
- Provider availability, cost, and data handling need review before integration.
- ML and generated summaries must not be interpreted as medical guidance.
- Frontend browser state is limited to the display theme until authenticated
  domain state is introduced behind the API service boundary.

## Current TODO

- Implement the authenticated baby resource API.
- Define validated event contracts and Huckleberry import behavior.
- Implement and evaluate the deterministic baseline before TabPFN.

## Last Completed Task

Frontend foundation — implement the initial Next.js/React/TypeScript shell.

## Last Commit

Local frontend foundation completion commit; no GitHub push is required for
local progress.

## Last Security Review

Frontend foundation review: lint, typecheck, production build, dependency
audit, secret review, and 8 desktop/mobile browser checks passed. The shell
makes no API requests and renders React-escaped text only. No CRITICAL or HIGH
findings were identified.

## Next Recommended Task

`TASK-005` — implement the authenticated baby resource API using the completed
ownership schema.
