# BOOH

BOOH is a privacy-conscious nighttime dashboard for new parents. It learns from
the user's own baby sleep, feed, and wake history to estimate when the next
wake-up is likely and roughly how much time remains.

## Project status

This repository currently contains the engineering foundation and application
boundaries. The backend exposes only a versioned health check and the frontend
contains a minimal accessible shell. OAuth, database models, Huckleberry
import, TabPFN, Gemma, ElevenLabs, the dashboard, and deployment are tracked as
future tasks in [`TASKS.md`](TASKS.md).

## Intended stack

- **Frontend:** Next.js, React, TypeScript
- **Backend:** FastAPI, Python
- **Database:** PostgreSQL with SQLAlchemy and Alembic
- **Authentication:** Google OAuth
- **ML:** TabPFN and a deterministic seven-day baseline
- **LLM:** Gemma for short summaries only
- **TTS:** ElevenLabs
- **Deployment:** Docker and Render
- **Import:** Huckleberry CSV
- **Testing:** pytest and frontend testing
- **API:** `/api/v1`

## Architecture

```text
API routes
    ↓
Services
    ↓
Repositories / data access
    ↓
Database

Prediction API
    ↓
Feature service
    ↓
Prediction model
    ↓
Baseline
```

Routes stay thin, business logic belongs in services, persistence belongs in
repositories, and external providers are hidden behind provider/service
abstractions.

## Repository guide

| Path | Purpose |
| --- | --- |
| `backend/` | FastAPI and backend ownership boundary |
| `frontend/` | Next.js, React, and TypeScript ownership boundary |
| `ml/` | Feature, baseline, and model ownership boundary |
| `tests/` | Cross-layer testing ownership boundary |
| `docs/` | Design and operational documentation |
| `.agent/` | Agent result files and collaboration records |
| `AGENTS.md` | Required engineering rules |
| `CONTEXT.md` | Persistent project memory; read before changes |
| `SECURITY.md` | Security policy and severity definitions |
| `TASKS.md` | Dependency-aware task board |

## Engineering rules

Read [`AGENTS.md`](AGENTS.md) before contributing. Read [`CONTEXT.md`](CONTEXT.md)
before modifying the project. Security and privacy requirements are defined in
[`SECURITY.md`](SECURITY.md); `CRITICAL` and `HIGH` findings block completion.

## Local setup

The backend requires Python 3.12 or newer and the frontend requires Node.js
20.9 or newer. When environment configuration is introduced, copy the
names-only contract from `.env.example` into a local `.env`; never commit the
local file or real credentials.

### Backend

```text
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements-dev.txt
.venv/bin/python -m pytest
.venv/bin/python -m uvicorn backend.app.main:app --reload
```

The health check is available at `GET /api/v1/health`. API documentation is
disabled during the scaffold phase until authenticated, domain-specific routes
are introduced.

### Frontend

```text
cd frontend
npm install
npm run dev
npm run test
npm run lint
npm run typecheck
npm run build
```

The frontend does not contain provider credentials, database access, or
prediction policy.

## Contribution workflow

Use a task ID from `TASKS.md`, keep one logical task per commit, run relevant
tests and lint/type checks, perform a security/secrets review, update the task
result, and use one of the approved commit prefixes: `feat:`, `fix:`,
`security:`, `test:`, `refactor:`, `docs:`, or `chore:`.
