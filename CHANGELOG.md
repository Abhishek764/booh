# Changelog

All notable BOOH changes are recorded here. Entries are grouped by project
phase and task ID.

## Unreleased

- No unreleased application functionality.

## 2026-10-04 — TASK-002

- Added the versioned FastAPI application boundary and bounded health response.
- Added a minimal Next.js/React/TypeScript application shell without provider
  secrets or domain prediction behavior.
- Added deterministic backend and frontend smoke checks plus local setup
  commands.
- Pinned dependencies and verified the frontend dependency audit has no known
  vulnerabilities.

## 2026-10-04 — TASK-003

- Added the initial SQLAlchemy users/events mappings and PostgreSQL-compatible
  Alembic migration.
- Added explicit owner foreign keys, UTC-aware timestamps, allowlisted event
  values, and non-negative duration constraints.
- Added isolated SQLite upgrade/rollback tests and PostgreSQL DDL checks.

## 2026-10-04 — TASK-004

- Added the provider-isolated Google OAuth authorization-code flow with PKCE,
  state, nonce, issuer, audience, signature, and claim validation.
- Added provider-neutral identity persistence, opaque server-side sessions,
  secure cookies, CSRF/origin checks, idle/absolute expiry, and logout
  revocation.
- Added authenticated identity and authorization boundaries with owner-scoped
  repository queries and bounded non-enumerating errors.
- Added deterministic OAuth, migration, ownership, logging, and dependency
  security checks.

## 2026-10-04 — Database foundation expansion

- Added baby profiles and moved event ownership from users to babies.
- Added sleep/feed/wake event start/end fields, duration, feed amount checks,
  UTC-aware timestamps, ownership indexes, and cascade boundaries.
- Added prediction, summary, and external audio-reference tables with model
  provenance, bounded summaries, storage references, and retention timestamps.
- Added a reviewed Alembic migration that backfills legacy events into a UTC
  profile per existing user and passes isolated upgrade/check/rollback tests.

## 2026-10-04 — TASK-005

- Added authenticated baby profile CRUD under `/api/v1/babies`.
- Enforced owner predicates in every baby repository query and rejected
  client-supplied ownership fields.
- Added strict name, date, timezone, unknown-field, malformed-ID, request-size,
  and cross-user authorization coverage.

## 2026-10-04 — Secure OAuth authentication follow-up

- Added canonical Google login and callback route names under `/api/v1/auth`.
- Added exact-origin credentialed CORS, session-bound CSRF proof on `/auth/me`,
  and privacy headers on the authentication surface.
- Added explicit route security coverage for invalid state/callbacks, expired
  sessions, unauthenticated identity, open redirects, cookies, CORS, and
  cross-user access.

## 2026-10-04 — TASK-001

- Initialized the BOOH engineering foundation.
- Added architecture, security, privacy, environment, Git, and collaboration
  rules.
- Added the dependency-aware task board and persistent project context.
- Added ownership-boundary documentation and agent result templates.
