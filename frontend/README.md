# Frontend

This directory contains the Next.js, React, and TypeScript frontend boundary.
The browser must never contain provider secrets or access PostgreSQL directly.
The current page is an accessible application shell; dashboard behavior is
tracked in a later task.

## Scaffold commands

```text
npm install
npm run dev
npm run test
npm run lint
npm run typecheck
npm run build
```

The frontend currently tests the versioned API health-path contract without
making network calls or embedding secrets.
