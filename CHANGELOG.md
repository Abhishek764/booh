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

## 2026-10-04 — TASK-001

- Initialized the BOOH engineering foundation.
- Added architecture, security, privacy, environment, Git, and collaboration
  rules.
- Added the dependency-aware task board and persistent project context.
- Added ownership-boundary documentation and agent result templates.
