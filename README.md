# BOOH

BOOH is a privacy-conscious nighttime dashboard for new parents. It learns from
the user's own baby sleep, feed, and wake history to estimate when the next
wake-up is likely and roughly how much time remains.

## Project status

This repository is currently the engineering foundation only. Application
functionality has not been implemented. OAuth, database models, Huckleberry
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

The application has not been scaffolded yet. When environment configuration is
introduced, copy the names-only contract from `.env.example` into a local
`.env`; never commit the local file or real credentials.

## Contribution workflow

Use a task ID from `TASKS.md`, keep one logical task per commit, run relevant
tests and lint/type checks, perform a security/secrets review, update the task
result, and use one of the approved commit prefixes: `feat:`, `fix:`,
`security:`, `test:`, `refactor:`, `docs:`, or `chore:`.
