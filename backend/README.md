# Backend

This directory is reserved for the FastAPI backend. The planned layering is:

```text
API routes → services → repositories/data access → PostgreSQL
```

Keep routes thin and put business logic in services. Google OAuth, ElevenLabs,
and other external integrations must be accessed through provider/service
abstractions. No backend application functionality has been implemented yet.
