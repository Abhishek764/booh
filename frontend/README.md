# Frontend

This directory contains the Next.js, React, and TypeScript frontend boundary.
The browser must never contain provider secrets or access PostgreSQL directly.
The current page is an accessible, mobile-first nighttime shell; dashboard
behavior is tracked in a later task.

## Structure

| Path | Responsibility |
| --- | --- |
| `app/` | Next.js routes, loading, not-found, and error boundaries |
| `components/` | Small reusable accessible UI components |
| `hooks/` | Client-only display state such as the theme preference |
| `lib/` | Pure browser-safe utilities and versioned API paths |
| `services/` | Future validated service clients; no provider access |
| `types/` | Shared frontend-only types |
| `styles/` | Design tokens and responsive global styles |

## Scaffold commands

```text
npm install
npm run dev
npm run test
npm run lint
npm run typecheck
npm run build
npx playwright install chromium
```

`npm run test` builds the production shell and runs deterministic Playwright
checks in desktop and mobile Chromium. The browser shell makes no API calls,
uses no provider credentials, and renders future content as an honest empty
state.
