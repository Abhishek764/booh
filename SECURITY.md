# BOOH Security Policy

BOOH handles sensitive household routines and must be designed as a privacy
product from the start. This policy defines the baseline controls for design,
implementation, review, and release. It applies to the API, frontend, data
pipeline, ML, LLM, provider integrations, local development, and deployment.

## Severity

| Severity | Meaning | Completion impact |
| --- | --- | --- |
| `CRITICAL` | A credible path to account takeover, broad data exposure, destructive data loss, secret compromise, or remote code execution. | Blocks completion and release immediately. |
| `HIGH` | A material path to unauthorized user data access, authentication bypass, persistent injection, significant privacy loss, or unsafe AI behavior. | Blocks completion until fixed or formally risk-accepted by the security owner. |
| `MEDIUM` | A meaningful weakness with limited scope or requiring additional conditions to exploit. | Must be tracked with an owner and target. |
| `LOW` | Defense-in-depth, hardening, or minor information disclosure issue. | Track and address according to risk. |

`CRITICAL` and `HIGH` issues always block task completion. Do not suppress a
finding because a feature is early or behind a development flag.

## Authentication

- Use Google OAuth through a backend provider abstraction; do not implement
  provider protocol details in route handlers or the frontend.
- The canonical browser endpoints are `GET /api/v1/auth/google`,
  `GET /api/v1/auth/google/callback`, `POST /api/v1/auth/logout`, and
  `GET /api/v1/auth/me`. The server owns the authorization code exchange,
  provider tokens, identity validation, and session creation.
- Validate issuer, audience, redirect URI, nonce, token signature, expiry, and
  required claims. Do not accept an identity supplied only by the browser.
- Create or resolve the local user only after successful provider validation.
- Provide safe login, callback, logout, and failure behavior without leaking
  whether another account exists.

## Authorization and IDOR prevention

- Authorize every request against the authenticated principal and the resource's
  ownership boundary.
- Never use a client-supplied user ID as the authorization source.
- Repository queries for user-scoped data must include the authenticated owner
  constraint, not rely on a later application-side filter.
- Test horizontal access, object enumeration, deleted users, and stale sessions.

## CSRF and secure cookies

- Protect state-changing browser requests with same-site cookies and an explicit
  CSRF strategy appropriate to the authentication flow.
- Use `Secure`, `HttpOnly`, and an intentional `SameSite` setting for session
  cookies. Scope domain and path narrowly.
- Rotate session identifiers after authentication and invalidate them on logout
  or security-sensitive changes.
- Validate OAuth `state` and `nonce` values server-side, bind them to the
  initiating session, make them single-use, and expire them quickly.
- The session cookie is `HttpOnly` and is never returned in JSON. The CSRF
  cookie is not `HttpOnly` by design so a same-origin frontend can copy its
  opaque value into `X-CSRF-Token`; authenticated `/api/v1/auth/me` returns the
  same session-bound proof for an explicitly allowlisted cross-origin frontend.

## CORS and browser origins

- `FRONTEND_ORIGIN` is one exact absolute HTTP(S) origin. Paths, queries,
  fragments, credentials, wildcards, and arbitrary browser-supplied origins are
  rejected.
- Credentialed CORS allows only that configured origin, `GET`/`POST`, and the
  `Content-Type`/`X-CSRF-Token` headers. Wildcard origins are never combined
  with credentials. Production origins and redirect URIs must use HTTPS.
- Post-login redirects always use the configured frontend origin; no `next`,
  `redirect`, or other browser-controlled destination is accepted.

## OAuth state validation

The callback must reject missing, expired, reused, mismatched, or
cross-session `state` values and invalid `nonce` values. Do not use an open
redirect or allow a callback URL from an untrusted request parameter.

The configured Google redirect URI must target the fixed
`/api/v1/auth/google/callback` path. The legacy `/api/v1/auth/callback` path is
accepted only for existing explicitly registered clients and is not used as
the canonical configuration.

## Secrets management

- Keep secrets in environment variables or a managed secret store. `.env`
  files, secret values, provider tokens, private keys, and database credentials
  are never committed.
- Keep secret names in `.env.example` and `CONTEXT.md`, never secret values.
- Avoid logging secrets through exception messages, request dumps, debug pages,
  telemetry, prompts, or test output.
- Rotate exposed credentials immediately and invalidate the old value.

## Input validation

- Validate type, shape, length, range, encoding, content type, and allowed values
  at every trust boundary.
- Enforce request size and rate limits appropriate to the endpoint.
- Reject unknown fields where permissive parsing could change policy or model
  behavior.
- Normalize timestamps and reject impossible or ambiguous event data rather than
  silently changing it.

## File upload security

- Huckleberry imports must be limited to the expected CSV format, size, row
  count, encoding, and columns.
- Treat file names, MIME types, extensions, and CSV cells as untrusted. Do not
  execute file content or place uploads in a web-served directory.
- Store uploads outside the application source tree, scan where appropriate,
  use safe temporary files, and delete them according to the retention policy.
- Defend against CSV formula injection on export or display and against parser
  resource exhaustion.

## SQL injection prevention

- Use SQLAlchemy expressions or parameterized queries only.
- Do not concatenate table names, clauses, sort keys, or values from user
  input. Map client sort/filter names through explicit allowlists.
- Review raw SQL, migrations, and administrative scripts as security-sensitive
  code.

## XSS prevention

- Escape output by default and use framework-safe rendering.
- Do not render imported text or LLM output as raw HTML. Sanitize any narrowly
  required markup with a tested allowlist.
- Apply an appropriate Content Security Policy and avoid unsafe inline script
  patterns.

## SSRF prevention

- Do not fetch arbitrary URLs supplied by users, imported files, prompts, or
  provider responses.
- For required outbound integrations, use fixed provider hosts, HTTPS,
  explicit timeouts, bounded response sizes, and an egress policy that blocks
  loopback, link-local, private, metadata, and internal network addresses.
- Validate redirects or disable them; re-check destination addresses after DNS
  resolution where applicable.

## Command injection prevention

- Do not pass user input, file names, model output, or provider data to a shell.
- Prefer library APIs and argument arrays with a fixed executable when a process
  is unavoidable. Apply timeouts, resource limits, and an allowlist.

## Logging and privacy

- Log security events with request correlation IDs, outcome, and minimal
  metadata. Do not log raw baby routines, notes, OAuth tokens, cookies, prompts,
  model responses, or uploaded file contents.
- Redact authorization headers, cookies, connection strings, and provider
  payloads before logging.
- Define retention, access controls, deletion, and incident response before
  production data is accepted.
- Authentication responses use `Cache-Control: no-store`,
  `Referrer-Policy: no-referrer`, and `X-Content-Type-Options: nosniff` on the
  auth surface. The supported Uvicorn entrypoint disables raw access logs so
  callback codes and state values do not enter request-line logs.

## LLM prompt injection

- Treat all user/imported content as data, never as instructions.
- Keep system instructions separate from content, delimit content clearly, and
  bound its length and fields.
- Do not allow the model to choose tools, access secrets, make authorization
  decisions, or retrieve arbitrary URLs.
- Test direct and indirect prompt injection, instruction smuggling, data
  exfiltration, and denial-of-service inputs.

## AI output validation

- Validate Gemma output against a strict schema, maximum length, character and
  content policy, and the source prediction values.
- Reject fabricated times, medical claims, unsafe advice, secrets, raw private
  data, and instruction-like output. Use a deterministic safe fallback summary.
- The model may summarize a validated prediction; it may not create or alter
  the prediction, user permissions, or stored events.
- Record model/version and validation outcomes without storing unnecessary raw
  prompts or responses.

## Docker and deployment security

- Use minimal pinned base images, non-root users, a read-only filesystem where
  practical, dropped Linux capabilities, and no unnecessary network access.
- Do not bake secrets or `.env` files into images. Use runtime secret
  injection, health checks, resource limits, and explicit ports.
- Pin and review image dependencies, scan images, and keep deployment manifests
  free of credentials.

## Dependency security

- Pin or lock direct dependencies and review transitive changes.
- Run dependency and container vulnerability scans in CI and address
  `CRITICAL`/`HIGH` findings before completion.
- Prefer maintained packages, minimize dependencies, and review provider SDK
  permissions and data handling.

## Review and reporting

Every feature task must include a security review covering its trust boundaries,
authorization, data exposure, dependency changes, and tests. Report suspected
vulnerabilities privately to the project security owner; do not publish
exploitable details in an issue before a fix is available.
