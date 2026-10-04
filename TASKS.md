# BOOH Task Board

This board follows the 17-task delivery roadmap. A task may start only when
its listed dependencies are complete and its security requirements are
understood. Status values are `DONE`, `READY`, `BLOCKED`, or `PLANNED`.

| ID | Owner | Description | Dependencies | Files | Status | Acceptance Criteria | Security Requirements |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `TASK-001` | lead | Initialize repository engineering foundation and governance. | None | Root docs, `.agent/`, `.gitignore`, `.env.example` | `DONE` | Rules, context, security policy, result templates, and task board exist; foundation commit created. | No secrets, credentials, real baby data, or real CSV exports. |
| `TASK-002` | backend | Define the PostgreSQL schema, SQLAlchemy mappings, and Alembic workflow. | `TASK-001` | `backend/`, `docs/`, `tests/` | `DONE` | Reviewed migrations create user, identity, baby, event, prediction, summary, and external-audio-reference structures; rollback, legacy-event backfill, and isolated test database paths work. | Ownership constraints, UTC timestamps, cascading boundaries, parameterized access, no sensitive fixtures or audio binaries. |
| `TASK-003` | frontend | Scaffold the Next.js/React/TypeScript application boundary. | `TASK-001` | `frontend/`, `tests/` | `DONE` | Local frontend commands, health-path contract, baseline checks, and secure browser boundary pass. | No browser secrets, no database access, dependency review, XSS-safe rendering. |
| `TASK-004` | backend/security | Implement the Google OAuth provider abstraction, sessions, and authorization boundary. | `TASK-002`, `TASK-003` | `backend/`, `tests/`, `SECURITY.md` | `DONE` | Login/callback/logout and ownership tests pass; invalid state, nonce, issuer, audience, and session cases fail safely. | OAuth state/nonce, CSRF, secure cookies, IDOR prevention, secret handling. |
| `TASK-005` | backend | Implement the authenticated baby resource API. | `TASK-004` | `backend/`, `tests/`, `docs/` | `READY` | Versioned CRUD contracts, ownership enforcement, validation, and bounded errors pass. | IDOR prevention, authenticated ownership, input limits, no private data in errors/logs. |
| `TASK-006` | backend | Implement the validated sleep/feed/wake event API. | `TASK-005` | `backend/`, `tests/`, `docs/` | `PLANNED` | Versioned event contracts, UTC normalization, filtering bounds, ownership, and validation pass. | IDOR prevention, allowlisted fields, timestamp validation, transaction safety. |
| `TASK-007` | data/backend | Implement the bounded Huckleberry CSV importer. | `TASK-006` | `backend/`, `tests/`, `docs/` | `PLANNED` | Supported synthetic fixtures import deterministically; malformed, oversized, duplicate, and impossible rows are handled explicitly. | Upload limits, safe temporary files, formula-injection defense, deletion path, isolation. |
| `TASK-008` | ml/backend | Implement the versioned feature service and deterministic seven-day baseline. | `TASK-006` | `ml/`, `backend/`, `tests/` | `PLANNED` | Feature versioning, sparse-history behavior, reproducible predictions, and baseline evaluation pass. | Authorized user data only, no cross-user pooling, explicit uncertainty, no medical claims. |
| `TASK-009` | ml | Add the isolated TabPFN adapter and evaluate it against the baseline. | `TASK-008` | `ml/`, `tests/`, `docs/` | `PLANNED` | Offline evaluation documents when TabPFN improves the baseline and when it is unavailable. | Bounded resources, model/version provenance, sparse-data safety, no training leakage. |
| `TASK-011` | backend | Expose the layered prediction API. | `TASK-004`, `TASK-008`, `TASK-009` | `backend/`, `tests/`, `docs/` | `PLANNED` | `/api/v1` contracts, auth, validation, ownership, errors, and model metadata are tested and documented. | Thin routes, IDOR tests, rate/size limits, no raw private history in logs/errors. |
| `TASK-010` | llm/security | Add the Gemma summary service for short validated summaries. | `TASK-011` | `backend/`, `ml/`, `tests/`, `docs/` | `PLANNED` | Prompt minimization, injection tests, strict output validation, bounded length, and deterministic fallback pass. | Prompt injection defense, no tools/secrets, output validation, privacy-preserving logs. |
| `TASK-012` | llm/backend | Add the ElevenLabs TTS provider abstraction and bounded audio flow. | `TASK-011` | `backend/`, `frontend/`, `tests/`, `docs/` | `PLANNED` | Provider failures degrade safely; audio access is authorized, bounded, and retention-controlled. | Fixed provider host, secret isolation, SSRF defense, content/privacy review. |
| `TASK-013` | frontend | Build the accessible nighttime dashboard and prediction presentation. | `TASK-010`, `TASK-012` | `frontend/`, `tests/`, `docs/` | `PLANNED` | Authenticated users see their own validated prediction and uncertainty; loading/error/empty states work. | XSS-safe rendering, no secrets, no cross-user data, no medical/guarantee language. |
| `TASK-014` | integration | Integrate backend, frontend, prediction, summary, and audio flows. | `TASK-013` | `backend/`, `frontend/`, `ml/`, `tests/`, `docs/` | `PLANNED` | Cross-module happy paths and failure paths pass with stable contracts and no ownership regressions. | End-to-end authorization, redacted logs, bounded calls, provider failure isolation. |
| `TASK-015` | security | Complete cross-layer security and privacy hardening. | `TASK-014` | `tests/`, `docs/`, `SECURITY.md` | `PLANNED` | Threat model, dependency scans, privacy/retention review, and release checklist complete with no blockers. | `CRITICAL`/`HIGH` findings block completion; verify all policy sections. |
| `TASK-016` | qa | Complete regression, accessibility, and release-quality verification. | `TASK-015` | `tests/`, `docs/`, `frontend/`, `backend/` | `PLANNED` | Critical paths, deterministic tests, accessibility checks, and supported runtime checks pass. | No real personal data, no secret leakage, safe error and privacy assertions. |
| `TASK-017` | devops | Containerize and deploy through Docker and Render. | `TASK-016` | `Dockerfile*`, `render.yaml`, `docs/`, `tests/` | `PLANNED` | Reproducible build, health checks, migrations, observability, rollback, and runtime configuration are documented. | Non-root image, no baked secrets, pinned dependencies, least privilege, secure egress. |

## Historical alignment

The first implementation used the original board's numbering for scaffolding
and database work. The current roadmap preserves the completed commits while
aligning the names above:

- Roadmap `TASK-002` (database) is implemented by `2779601`.
- Roadmap `TASK-003` (frontend/application boundary) is implemented by
  `3d7c696`.
- The database foundation was expanded in the current local commit with
  `0003_domain_database_foundation`.

## Task workflow

1. Read `CONTEXT.md`, `AGENTS.md`, and `SECURITY.md`.
2. Perform the Q&A check and record `Q&A check: no blocking questions.` when
   there are no blockers.
3. Confirm dependencies, claim one task, and isolate ownership.
4. Decompose, implement, test, security-review, and inspect the complete diff.
5. Retry a failing task at most three times; stop and report a blocker after the
   third unsuccessful fix iteration.
6. Update the task result, `CONTEXT.md`, and task status only after checks pass.
7. Create one appropriately prefixed commit per logical task and integrate it.
