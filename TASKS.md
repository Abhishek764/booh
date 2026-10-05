# BOOH Task Board

This board follows the 17-task delivery roadmap. A task may start only when
its listed dependencies are complete and its security requirements are
understood. Status values are `DONE`, `READY`, `BLOCKED`, or `PLANNED`.

| ID | Owner | Description | Dependencies | Files | Status | Acceptance Criteria | Security Requirements |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `TASK-001` | lead | Initialize repository engineering foundation and governance. | None | Root docs, `.agent/`, `.gitignore`, `.env.example` | `DONE` | Rules, context, security policy, result templates, and task board exist; foundation commit created. | No secrets, credentials, real baby data, or real CSV exports. |
| `TASK-002` | backend | Define the PostgreSQL schema, SQLAlchemy mappings, and Alembic workflow. | `TASK-001` | `backend/`, `docs/`, `tests/` | `DONE` | Reviewed migrations create user, identity, baby, event, prediction, summary, and external-audio-reference structures; rollback, legacy-event backfill, and isolated test database paths work. | Ownership constraints, UTC timestamps, cascading boundaries, parameterized access, no sensitive fixtures or audio binaries. |
| `TASK-003` | frontend | Build the Next.js/React/TypeScript frontend foundation. | `TASK-001` | `frontend/`, `tests/` | `DONE` | Local frontend commands, responsive nighttime shell, accessible boundaries, theme preference, browser checks, and secure browser boundary pass. | No browser secrets, no database access, dependency review, XSS-safe rendering. |
| `TASK-004` | backend/security | Implement the secure Google OAuth provider abstraction, sessions, and authorization boundary. | `TASK-002`, `TASK-003` | `backend/`, `tests/`, `SECURITY.md` | `DONE` | Canonical Google login/callback/logout/me routes, exact-origin CORS, session-bound CSRF, cookie flags, invalid state/callback, expiry, open-redirect, and ownership tests pass. | OAuth state/nonce, PKCE, CSRF, secure cookies, exact CORS, IDOR prevention, secret handling. |
| `TASK-005` | backend | Implement the authenticated baby resource API. | `TASK-004` | `backend/`, `tests/`, `docs/` | `DONE` | Versioned CRUD contracts, owner-scoped repository predicates, strict request validation, bounded bodies/errors, and IDOR tests pass. | IDOR prevention, authenticated ownership, input limits, no private data in errors/logs. |
| `TASK-006` | backend | Implement the validated sleep/feed/wake event API. | `TASK-005` | `backend/`, `tests/`, `docs/` | `DONE` | Versioned event contracts, UTC normalization, bounded pagination, owner-scoped nested/create/update/delete queries, CSRF-protected mutations, and validation pass. | IDOR prevention, allowlisted fields, timestamp validation, transaction safety. |
| `TASK-007` | data/backend | Implement the bounded Huckleberry CSV importer. | `TASK-006` | `backend/`, `tests/`, `docs/` | `DONE` | Supported synthetic fixtures import deterministically; malformed, oversized, duplicate, and impossible rows are handled explicitly. | Upload limits, memory-only originals, formula-injection defense, deletion path, isolation. |
| `TASK-008` | ml/backend | Implement the versioned feature service and deterministic seven-day baseline. | `TASK-006` | `ml/`, `backend/`, `tests/` | `DONE` | Feature versioning, sparse-history behavior, reproducible predictions, and baseline evaluation pass. | Authorized user data only, no cross-user pooling, explicit uncertainty, no medical claims. |
| `TASK-009` | ml | Add the isolated TabPFN adapter and evaluate it against the baseline. | `TASK-008` | `ml/`, `tests/`, `docs/` | `DONE` | Offline evaluation documents when TabPFN improves the baseline and when it is unavailable. | Bounded resources, model/version provenance, sparse-data safety, no training leakage. |
| `TASK-011` | backend | Expose the layered prediction API. | `TASK-004`, `TASK-008`, `TASK-009` | `backend/`, `tests/`, `docs/` | `READY` | `/api/v1` contracts, auth, validation, ownership, errors, and model metadata are tested and documented. | Thin routes, IDOR tests, rate/size limits, no raw private history in logs/errors. |
| `TASK-010` | llm/security | Add the standalone Gemma summary service for short validated summaries. | `TASK-009` | `backend/`, `tests/`, `docs/` | `DONE` | Prompt minimization, injection tests, strict output validation, bounded length, and deterministic fallback pass; HTTP integration follows TASK-011. | Prompt injection defense, no tools/secrets, output validation, privacy-preserving logs. |
| `TASK-012` | llm/backend | Add the ElevenLabs TTS provider abstraction and bounded audio flow. | `TASK-011` | `backend/`, `frontend/`, `tests/`, `docs/` | `PLANNED` | Provider failures degrade safely; audio access is authorized, bounded, and retention-controlled. | Fixed provider host, secret isolation, SSRF defense, content/privacy review. |
| `TASK-013` | frontend | Build the accessible nighttime dashboard and prediction presentation. | `TASK-010`, `TASK-012` | `frontend/`, `tests/`, `docs/` | `PLANNED` | Authenticated users see their own validated prediction and uncertainty; loading/error/empty states work. | XSS-safe rendering, no secrets, no cross-user data, no medical/guarantee language. |
| `TASK-014` | integration | Integrate backend, frontend, prediction, summary, and audio flows. | `TASK-013` | `backend/`, `frontend/`, `ml/`, `tests/`, `docs/` | `PLANNED` | Cross-module happy paths and failure paths pass with stable contracts and no ownership regressions. | End-to-end authorization, redacted logs, bounded calls, provider failure isolation. |
| `TASK-015` | security | Complete cross-layer security and privacy hardening. | `TASK-014` | `tests/`, `docs/`, `SECURITY.md` | `PLANNED` | Threat model, dependency scans, privacy/retention review, and release checklist complete with no blockers. | `CRITICAL`/`HIGH` findings block completion; verify all policy sections. |
| `TASK-016` | qa | Complete regression, accessibility, and release-quality verification. | `TASK-015` | `tests/`, `docs/`, `frontend/`, `backend/` | `PLANNED` | Critical paths, deterministic tests, accessibility checks, and supported runtime checks pass. | No real personal data, no secret leakage, safe error and privacy assertions. |
| `TASK-017` | devops | Containerize and deploy through Docker and Render. | `TASK-016` | `Dockerfile*`, `render.yaml`, `docs/`, `tests/` | `PLANNED` | Reproducible build, health checks, migrations, observability, rollback, and runtime configuration are documented. | Non-root image, no baked secrets, pinned dependencies, least privilege, secure egress. |

## Historical alignment

Completed claim: `TASK-010` — llm/security, explicitly user-started standalone
summary service using TASK-009's completed numerical result contract. Its service
dependency is TASK-009; authenticated HTTP/lifecycle integration remains TASK-011.
Q&A check: no blocking questions. No prediction policy or numerical changes.
Implementation and security review are verified: 180 added summary/provider tests
and all 515 backend/ML tests pass, scoped Ruff/strict mypy and dependency checks
pass. Documentation: `docs/summaries.md`. Result: `.agent/llm/RESULT.md`.
Completion: `feat: add guarded Gemma sleep summaries` — one explicitly approved
logical completion commit carrying this record and the LLM-agent result.

Completed claim: prediction-engine milestone — ml, finish TASK-008's deterministic
baseline/evaluation prerequisite, then implement TASK-009's local TabPFN adapter
and production service. User explicitly started both components; implement them
in dependency order and record one logical prediction-engine completion commit.
Q&A check: no blocking questions. Numerical results are independent of Gemma.
Baseline prerequisite verified before TASK-009 implementation: causal recent
held-out MAE/Brier workflow and 117 baseline/feature/training tests passed.
Completion: explicit baseline, local bounded TabPFN regressor/classifier,
separate offline training/evaluation, production inference with safe fallback,
and real synthetic CPU evaluation. All 335 tests pass. Result: `.agent/ml/RESULT.md`.

Completed claim: `TASK-008` feature-engineering slice — ml, independent numerical
features from normalized, single-baby history. Dependency `TASK-006` is complete.
Q&A check: no blocking questions. Result: `.agent/ml/RESULT.md`. Feature service,
definitions/docs, and 93 deterministic edge/privacy unit tests are complete.
The baseline/evaluation slice is now completed by the prediction-engine milestone
above; TASK-008 is DONE.

Completed claim: `TASK-007` — data/backend, secure Huckleberry and generic CSV
import pipeline. Dependencies `TASK-004` through `TASK-006` are complete.
Q&A check: no blocking questions. Result: `.agent/data/RESULT.md`.

Completed TASK-004 follow-up (backend): canonical Google route names,
credentialed origin allowlisting, browser-usable CSRF proof, and explicit
database-backed authentication/security tests.

Completed TASK-005 (backend): owner-scoped baby CRUD routes, strict contracts,
repository-level ownership predicates, bounded request bodies, and explicit
cross-user/validation tests.

Completed TASK-006 (backend): owner-scoped sleep/feed/wake event routes, UTC
normalization, strict values and timestamp validation, CSRF-protected mutations,
bounded pagination, and explicit cross-user/IDOR tests.

Completed TASK-007 (data/backend): bounded memory-only CSV uploads, independent
Huckleberry/generic adapters, UTC normalization, semantic baby-scoped duplicate
detection, atomic persistence, privacy-preserving summaries, and synthetic import
security tests. No schema or runtime dependency changes.

The first implementation used the original board's numbering for scaffolding
and database work. The current roadmap preserves the completed commits while
aligning the names above:

- Roadmap `TASK-002` (database) is implemented by `2779601`.
- Roadmap `TASK-003` (frontend/application boundary) is implemented by
  `3d7c696`.
- The database foundation was expanded in the current local commit with
  `0003_domain_database_foundation`.

## Hacktoberfest 2026 submission track

The current BOOH foundation is not submission-ready for the supplied Challenge
1 “Build for a Friend” prompt. Before starting challenge code, explicitly claim
a time-boxed task for the smallest end-to-end slice and confirm a real friend
can test it. The slice must include a working prediction flow, a meaningful
open-weight model feature, uncertainty-aware presentation, and honest feedback
evidence. Do not spend the timebox on more OAuth polish, do not commit real
family data, and do not describe a summary-only model as the prediction engine.

The announcement supplied for this project lists the submission deadline as
October 5, 2026 at 06:59 UTC. If a real friend is unavailable, preserve BOOH
for a later submission rather than claiming the theme was met.

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
