# Backend

This directory contains the FastAPI backend boundary. The planned layering is:

```text
API routes → services → repositories/data access → PostgreSQL
```

Keep routes thin and put business logic in services. Google OAuth, ElevenLabs,
and other external integrations must be accessed through provider/service
abstractions.

## Scaffold commands

From the repository root:

```text
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements-dev.txt
.venv/bin/python -m pytest
.venv/bin/python -m backend.app.server
```

The supported server entrypoint disables Uvicorn access logging because its
default request-line formatter would expose OAuth callback query parameters.
The canonical authentication routes are:

- `GET /api/v1/auth/google`
- `GET /api/v1/auth/google/callback`
- `POST /api/v1/auth/logout`
- `GET /api/v1/auth/me`

The authenticated baby profile routes are:

- `GET /api/v1/babies`
- `POST /api/v1/babies`
- `GET /api/v1/babies/{baby_id}`
- `PATCH /api/v1/babies/{baby_id}`
- `DELETE /api/v1/babies/{baby_id}`

The authenticated event routes are:

- `GET /api/v1/babies/{baby_id}/events`
- `POST /api/v1/babies/{baby_id}/events`
- `PATCH /api/v1/events/{event_id}`
- `DELETE /api/v1/events/{event_id}`

The configured `FRONTEND_ORIGIN` is the only credentialed CORS origin. The
server keeps the session cookie HttpOnly and returns only a session-bound CSRF
proof from `/auth/me`. Baby queries always include the authenticated session
owner in the repository predicate; request bodies reject `user_id`, unknown
fields, malformed IDs, invalid dates, invalid IANA timezones, and oversized
payloads. Event mutations require the same session-bound CSRF proof and exact
frontend origin; timestamps are normalized to UTC and ambiguous local times
are rejected. OpenAPI and interactive documentation remain disabled.
