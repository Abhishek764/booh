# BOOH Task Board

This board is dependency-aware. A task may start only when its listed
dependencies are complete and its security requirements are understood. Status
values are `DONE`, `READY`, `BLOCKED`, or `PLANNED`.

| ID | Owner | Description | Dependencies | Files | Status | Acceptance Criteria | Security Requirements |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `TASK-001` | lead | Initialize repository engineering foundation and governance. | None | Root docs, `.agent/`, `.gitignore`, `.env.example` | `DONE` | Required structure exists; rules, context, security policy, result templates, and task board are present; foundation commit created. | No secrets, credentials, real baby data, or real CSV exports; review `SECURITY.md`. |
| `TASK-002` | backend/frontend | Scaffold FastAPI and Next.js application boundaries with health-check/test infrastructure only. | `TASK-001` | `backend/`, `frontend/`, `tests/` | `DONE` | Local backend/frontend commands and baseline tests are documented and pass; no business functionality. | Secure defaults, no browser secrets, bounded errors, dependency review. |
| `TASK-003` | backend | Define initial PostgreSQL schema, SQLAlchemy mappings, and Alembic workflow. | `TASK-001`, `TASK-002` | `backend/`, `docs/`, `tests/` | `READY` | Reviewed migration creates only approved user/event structures; rollback and isolated test database path work. | Ownership constraints, UTC timestamps, parameterized access, no sensitive fixture data. |
| `TASK-004` | backend/security | Implement Google OAuth provider abstraction, sessions, and authorization boundary. | `TASK-002`, `TASK-003` | `backend/`, `tests/`, `SECURITY.md` | `PLANNED` | Login/callback/logout and ownership tests pass; invalid state, nonce, issuer, audience, and session cases fail safely. | OAuth state/nonce, CSRF, secure cookies, IDOR prevention, secret handling. |
| `TASK-005` | data/backend | Define validated event contracts and Huckleberry CSV import service. | `TASK-003`, `TASK-004` | `backend/`, `tests/`, `docs/` | `PLANNED` | Supported CSV fixtures import deterministically; malformed, oversized, duplicate, and impossible rows are handled explicitly. | Upload limits, safe temp files, CSV formula injection defense, user isolation, privacy deletion. |
| `TASK-006` | ml/backend | Implement feature service and deterministic seven-day baseline. | `TASK-003`, `TASK-005` | `ml/`, `backend/`, `tests/` | `PLANNED` | Feature versioning, sparse-history behavior, reproducible predictions, and baseline evaluation are tested. | Only authorized user data; no cross-user pooling; uncertainty is explicit; no medical claims. |
| `TASK-007` | ml | Add TabPFN model adapter and evaluation against the baseline. | `TASK-006` | `ml/`, `tests/`, `docs/` | `PLANNED` | Adapter is isolated from persistence; offline evaluation documents when it improves the baseline and when it is unavailable. | Bounded resources, model/version provenance, safe sparse-data behavior, no training-data leakage. |
| `TASK-008` | backend | Expose prediction API through the layered service architecture. | `TASK-004`, `TASK-006`, `TASK-007` | `backend/`, `tests/`, `docs/` | `PLANNED` | `/api/v1` contracts, auth, validation, ownership, errors, and model metadata are tested and documented. | Thin routes, IDOR tests, rate/size limits, no raw private history in logs or errors. |
| `TASK-009` | frontend | Build the nighttime dashboard and accessible prediction presentation. | `TASK-008` | `frontend/`, `tests/`, `docs/` | `PLANNED` | Authenticated users see their own validated prediction and uncertainty; loading/error/empty states work. | XSS-safe rendering, no secrets, no cross-user data, no medical/guarantee language. |
| `TASK-010` | llm/security | Add Gemma summary service for short validated natural-language summaries. | `TASK-008` | `backend/`, `ml/`, `tests/`, `docs/` | `PLANNED` | Prompt minimization, injection tests, strict output validation, bounded length, and deterministic fallback pass. | Prompt injection defense, no tools/secrets, output validation, privacy-preserving logs. |
| `TASK-011` | llm/backend | Add ElevenLabs TTS provider abstraction and bounded audio flow. | `TASK-009`, `TASK-010` | `backend/`, `frontend/`, `tests/`, `docs/` | `PLANNED` | Provider failures degrade safely; audio access is authorized, bounded, and retention-controlled. | Fixed provider host, secret isolation, SSRF defense, content/privacy review. |
| `TASK-012` | security/qa | Complete cross-layer security, privacy, accessibility, and regression hardening. | `TASK-005`, `TASK-008`, `TASK-009`, `TASK-010`, `TASK-011` | `tests/`, `docs/`, `SECURITY.md` | `PLANNED` | Critical paths, dependency scans, threat model, and release checklist are complete with no blocking findings. | `CRITICAL`/`HIGH` findings block completion; verify all policy sections. |
| `TASK-013` | devops | Containerize and deploy through Docker and Render. | `TASK-012` | `Dockerfile*`, deployment docs, `docs/`, `tests/` | `PLANNED` | Reproducible build, health checks, migrations, observability, rollback, and runtime configuration are documented. | Non-root image, no baked secrets, pinned dependencies, least privilege, secure egress. |

## Task workflow

1. Read `CONTEXT.md`, `AGENTS.md`, and `SECURITY.md`.
2. Confirm dependencies and claim one task.
3. Make only the changes required for the task.
4. Run tests, lint/type checks, and a security/secrets review.
5. Update the task status, `CONTEXT.md` when durable state changes, and the
   relevant `.agent/<agent>/RESULT.md`.
6. Inspect the full diff and create one appropriately prefixed commit.
