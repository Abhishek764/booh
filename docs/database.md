# BOOH database foundation

PostgreSQL is the production database target. SQLAlchemy owns the application
mappings and Alembic owns schema changes. The current schema contains:

- `users`: an internal UUID, email, and UTC creation/update timestamps.
- `user_identities`: provider-neutral issuer/subject identities used by the
  authentication boundary.
- `babies`: a user-owned profile with optional display name/date of birth and a
  required IANA timezone string.
- `events`: a baby-owned sleep, feed, or wake event with UTC start/end times,
  optional duration, and feed amount in milliliters where applicable.
- `predictions`: baby-owned advisory outputs with expected sleep, full double-
  precision 60-minute wake probability, explicit baseline/model/feature versions, and bounded feature
  metadata.
- `summaries`: bounded natural-language summaries linked to validated
  predictions and their provider version.
- `audio`: an external storage reference for generated audio. PostgreSQL stores
  the provider, storage key, content type, size, duration, and expiry—not audio
  binary content.

Events intentionally do not store free-form metadata in this foundation. Model
metadata is retained only on predictions because feature/model provenance is
needed for reproducible evaluation. Raw provider payloads, prompts, private
event histories, and generated audio bytes are not persisted here.

## Local commands

Set `DATABASE_URL` to a PostgreSQL URL in the local environment, then run:

```text
.venv/bin/python -m alembic -c backend/alembic.ini upgrade head
.venv/bin/python -m alembic -c backend/alembic.ini downgrade -1
```

Migration tests use temporary SQLite databases and never use production data.
Application tests enforce foreign keys. Alembic's SQLite batch parent rebuilds
use isolated connections with foreign keys off and verify child preservation;
TASK-011 fails closed if such a rebuild is attempted with foreign keys on to
prevent child cascade deletion. The initial domain migration preserves pre-baby
events by creating one synthetic UTC profile per existing user with events, then assigning those
events to that profile without copying event content into logs or fixtures.
Application code must construct an engine with an explicit URL; missing
`DATABASE_URL` fails closed. Production schema changes require a reviewed
Alembic migration.

## Ownership and time boundaries

Every baby has a non-null foreign key to exactly one user. Events and
predictions are owned through the baby, summaries through predictions, and
audio through summaries. Future repositories must join these ownership paths
in every user-scoped query. Timestamps use timezone-aware SQL types and callers
must provide UTC values at the service boundary.

TASK-011's `0004_prediction_probability` migration changes four-decimal Numeric
wake probability to `FLOAT(53)`/PostgreSQL double precision, preserving the exact
validated Python float during API persistence/summary generation. Upgrade casts
existing values without inventing lost precision; downgrade is lossy. PostgreSQL
DDL casts are reviewed/tested, SQLite upgrade/rollback/schema parity and child
preservation pass, and live PostgreSQL verification remains operational work.
