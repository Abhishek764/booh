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
.venv/bin/python -m uvicorn backend.app.main:app --reload
```

The only public route in this phase is `GET /api/v1/health`. It returns a
bounded, explicit response contract and does not query a database or expose
runtime details. OpenAPI and interactive documentation remain disabled until
authenticated application routes exist.
