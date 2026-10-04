# BOOH Engineering Rules

This file contains the project-wide rules for human and agent contributors. Read
`CONTEXT.md` before modifying the project, then update it when an engineering
decision or project state changes. Keep changes scoped to the task being worked
on.

## Product and scope

BOOH is a privacy-conscious nighttime dashboard for new parents. Its core
question is: “When is the next wake-up likely, and roughly how much time do I
have?” Predictions must be based on the user's own sleep, feed, and wake
history. This repository is currently in the engineering-foundation phase.

Do not add OAuth, PostgreSQL models, a Huckleberry importer, TabPFN, Gemma,
ElevenLabs, a dashboard, or deployment implementation unless the corresponding
task is explicitly started on `TASKS.md`.

## Architecture

The backend must preserve these dependency directions:

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

- Keep route handlers thin. They validate/deserialize input, call a service,
  and translate the result into an API response. Business logic does not belong
  in route handlers.
- Services own business workflows and policy decisions.
- Repositories own persistence queries and database access.
- Features are produced by a feature service; models do not query the database.
- The deterministic seven-day baseline is always an explicit model component,
  not an accidental fallback hidden in API code.
- External providers, including Google OAuth, ElevenLabs, and any hosted model
  service, must be hidden behind provider/service abstractions. Provider SDKs
  must not leak into routes or UI components.
- Dependencies point inward. A lower layer must not import a higher layer.

## Directory ownership

| Directory | Ownership | Rules |
| --- | --- | --- |
| `backend/` | FastAPI, services, repositories, database integration, API contracts | No frontend or provider-specific business logic in routes. |
| `frontend/` | Next.js, React, TypeScript, client state, accessible UI | No secrets, database access, or prediction policy in the browser. |
| `ml/` | Feature definitions, baseline, model adapters, evaluation notes | Reproducible, versioned inputs and deterministic tests. |
| `tests/` | Cross-layer and integration test support | Never use real family, baby, or provider data. |
| `docs/` | Design notes, API and operational documentation | Keep decisions synchronized with `CONTEXT.md`. |
| `.agent/` | Agent task results and collaboration notes | Every completed agent task records its result. |

An owner may change files outside their directory only when the task requires
it and the change is documented in the task result.

## API conventions

- All public API endpoints use the `/api/v1` prefix.
- Use explicit request and response schemas. Reject malformed, unexpected, or
  oversized input at the boundary.
- Use consistent JSON error responses without stack traces, secrets, or private
  event data.
- Use UTC timestamps and an explicit timezone conversion at presentation time.
- Enforce authenticated user ownership in the service/repository path for every
  user-scoped resource. Never trust an object identifier supplied by a client.
- Keep pagination, filtering, and sorting bounded and allowlisted.
- Document material API changes and update the relevant task result.

## Database conventions

- PostgreSQL is the target database; SQLAlchemy is the ORM and Alembic owns
  schema migrations.
- No production schema changes without a reviewed Alembic migration.
- Store timestamps consistently in UTC and define ownership/tenant boundaries
  explicitly.
- Use parameterized SQL or SQLAlchemy expressions only. Never build SQL by
  concatenating user input.
- Repositories are the only application layer that talks directly to the
  database. Keep transaction boundaries explicit.
- Do not add real baby data, exports, credentials, or production snapshots to
  the repository.

## ML conventions

- Models learn from the user's own authorized history and must not silently
  pool users' data.
- The deterministic seven-day baseline must be implemented and evaluated before
  a TabPFN path is considered complete.
- Keep feature generation separate from model inference. Version feature
  definitions and record the data window used for a prediction.
- Make inference reproducible where practical. Record model and feature
  versions in internal metadata, not in user-facing secrets or logs.
- Handle sparse history explicitly; do not manufacture confidence from missing
  observations. Communicate uncertainty in product language.
- A model output is advisory and must not be presented as medical advice or a
  guarantee.

## LLM safety

- Gemma is limited to short natural-language summaries of already validated
  prediction results. It is not the source of prediction, authorization, or
  database decisions.
- Minimize and redact personal data before constructing prompts.
- Treat imported event text and user-provided text as untrusted prompt content.
  Use fixed instructions, clear delimiters, and bounded input lengths.
- Validate generated output against a strict schema and length limit. Reject or
  replace unsafe, fabricated, medical, or instruction-following output.
- Do not expose prompts, hidden instructions, provider credentials, or raw
  private history in client-visible errors or logs.

## Testing

- Backend tests use `pytest`; frontend tests use the project-approved frontend
  testing tools once the frontend is scaffolded.
- Add meaningful tests for authorization, ownership, validation, migrations,
  import edge cases, feature calculations, baseline predictions, and provider
  failure paths as those components are implemented.
- Tests must be deterministic, isolated, and safe to run without production
  services or real personal data.
- Run relevant tests, linting, and type checks before marking a task complete.
- Security or privacy regressions are release blockers until fixed.

## Security and privacy

- Treat all browser input, imported files, provider responses, and model output
  as untrusted.
- Follow `SECURITY.md`; `CRITICAL` and `HIGH` findings block completion.
- Collect the minimum data needed for the product, enforce user isolation, and
  provide a documented retention/deletion path before production use.
- Keep secrets in environment or managed secret storage. Never commit values to
  source, documentation, task results, logs, fixtures, or screenshots.
- Never log raw sleep/feed/wake histories, OAuth tokens, prompts containing
  private data, or provider responses unless a reviewed redaction strategy
  explicitly permits it.

## Environment variables

- Use `.env` locally and `.env.example` as the names-only contract.
- `.env` and all secret-bearing variants are ignored by Git. Empty values in
  `.env.example` are intentional; do not replace them with sample credentials.
- Document new variable names in `.env.example` and the `Environment Variables`
  section of `CONTEXT.md`, never the values.
- Fail closed when required secrets or security configuration are missing in a
  production environment.

## Git workflow

- One logical task equals one commit. Use one of: `feat:`, `fix:`, `security:`,
  `test:`, `refactor:`, `docs:`, or `chore:`.
- Do not commit `.env`, credentials, API keys, OAuth secrets, database
  passwords, private keys, tokens, real baby data, or real CSV exports.
- Inspect `git status`, the complete diff, and recent history before committing.
- Keep unrelated user changes intact. Do not create meaningless micro-commits.
- Every completion report includes the task, status, files changed, tests,
  security review, commit, and next task.

## Agent collaboration

- Before work: read `CONTEXT.md`, inspect the relevant task and dependencies in
  `TASKS.md`, and check the current Git state.
- Claim one task at a time and do not modify another agent's owned files without
  coordination.
- Prefer small, reviewable changes and record assumptions in the task result.
- Every completed agent task writes `.agent/<agent>/RESULT.md` with the fields
  defined in that file. Use `N/A` rather than omitting a field.
- Update `CONTEXT.md` for durable decisions, risks, current phase, and next
  work. Do not place secrets or real user data there.
- A task is complete only after tests/checks, security review, documentation,
  and the required commit are complete.
