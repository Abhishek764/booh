# Database foundation — TASK-003

PostgreSQL is the production database target. SQLAlchemy owns the application
mappings and Alembic owns schema changes. The initial migration creates only:

- `users`: an internal UUID and UTC creation/update timestamps.
- `events`: an internal UUID, an owning `user_id`, an allowlisted event type,
  source, UTC event timestamp, optional non-negative duration, and creation
  timestamp.

No provider identity, notes, imported payload, or prediction fields are stored
in this migration. Provider identities belong to the authentication task and
event import details belong to the validated import task.

## Local commands

Set `DATABASE_URL` to a PostgreSQL URL in the local environment, then run:

```text
.venv/bin/python -m alembic -c backend/alembic.ini upgrade head
.venv/bin/python -m alembic -c backend/alembic.ini downgrade -1
```

Migration tests use a temporary SQLite database and never use production data.
Application code must construct an engine with an explicit URL; missing
`DATABASE_URL` fails closed.

## Ownership and time boundaries

Every event has a non-null foreign key to exactly one local user. Future
repositories must include that owner in every user-scoped query. Timestamps use
timezone-aware SQL types and callers must provide UTC values at the service
boundary.
