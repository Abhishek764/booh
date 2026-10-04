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
The API exposes the versioned health route and authenticated OAuth/session
routes; OpenAPI and interactive documentation remain disabled.
