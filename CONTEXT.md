# BOOH Project Context

## Purpose

BOOH is a privacy-conscious nighttime dashboard for new parents. It learns from
the user's own baby sleep, feed, and wake history to answer: “When is the next
wake-up likely, and roughly how much time do I have?” Predictions are advisory,
uncertain, and not medical advice.

## Current Phase

Phase 0 — Engineering foundation and application boundaries. The repository
contains the project rules, security guidance, planning artifacts, a minimal
FastAPI boundary with a versioned health check, and a minimal Next.js frontend
shell. Domain functionality has not been implemented.

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

PostgreSQL is planned as the production database, accessed through SQLAlchemy
with Alembic migrations. No models, migrations, or production data exist yet.
Timestamps will be stored in UTC, and all user-scoped access will enforce an
authenticated ownership boundary.

## Authentication

Google OAuth is planned behind a provider abstraction. OAuth, session, CSRF,
cookie, and authorization implementation has not started.

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

The public API prefix is `/api/v1`. The scaffold exposes only
`GET /api/v1/health`; it does not query a database or expose private runtime
details. Route handlers will remain thin and delegate to services, repositories,
and the database according to the rules in `AGENTS.md`.

## Frontend

Next.js, React, and TypeScript are scaffolded with an accessible shell and no
domain client behavior. The browser must not receive provider secrets or access
the database directly.

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

## Engineering Decisions

- Keep the initial repository documentation-first and functionality-free.
- Enforce layered backend and prediction architecture.
- Use provider/service abstractions for external systems.
- Keep the deterministic seven-day baseline explicit before TabPFN.
- Restrict Gemma to validated, short summaries.
- Use names-only environment examples and prohibit secrets in Git.
- Track work through dependency-aware IDs in `TASKS.md`.

## Known Risks

- User sleep and feed histories are sensitive household data.
- Sparse or irregular event histories can produce misleading confidence.
- OAuth/session implementation can create account-linking or IDOR risks.
- CSV parsing and LLM inputs are untrusted boundaries.
- Provider availability, cost, and data handling need review before integration.
- ML and generated summaries must not be interpreted as medical guidance.

## Current TODO

- Define the initial privacy-preserving PostgreSQL schema and Alembic workflow.
- Implement authentication and authorization with security tests.
- Define validated event contracts and Huckleberry import behavior.
- Implement and evaluate the deterministic baseline before TabPFN.

## Last Completed Task

`TASK-002` — scaffold backend and frontend application boundaries with
health-check and test infrastructure.

## Last Commit

Local `TASK-002` completion commit (hash reported in the completion report); no
GitHub push is required for this task.

## Last Security Review

TASK-002 review: repository hygiene, secret exclusion, architecture boundaries,
bounded errors, dependency pins, and frontend audit completed. No CRITICAL or
HIGH findings remain in the scaffold.

## Next Recommended Task

`TASK-003` — define the initial PostgreSQL schema, SQLAlchemy mappings, and
Alembic workflow.
