# Security Agent Result

TASK: TASK-004 — Google OAuth provider abstraction, sessions, and authorization boundary
STATUS: PASS
FILES CHANGED: `.agent/security/RESULT.md` only
API CHANGES: N/A — security review only; no application code changed
DATABASE CHANGES: N/A — security review only; no migration changed
TESTS: `.venv/bin/python -m pytest` — 37 passed, 2 existing Starlette/httpx deprecation warnings. `compileall` passed; `pip check` passed; `.venv/bin/pip-audit --local --strict` passed with no known vulnerabilities; isolated Alembic upgrade/check/rollback passed; `git diff --check` passed; independent SQLAlchemy PKCE persistence/consume probe passed; supported server logging probe passed.
SECURITY: PASS — no CRITICAL or HIGH findings remain in the reviewed TASK-004 implementation.
COMMIT: N/A — no commit requested or created
KNOWN ISSUES: Residual medium/low risks are listed below. Live Google and PostgreSQL services were unavailable, so provider transport and production database behavior were verified through fixed synthetic transports and isolated SQLite tests.
NEXT DEPENDENCY: TASK-005 — authenticated baby resource API

## Q&A check

Q&A check: no blocking questions.

## Review basis

Reviewed the actual current backend implementation, migration, backend tests,
supported server entrypoint, `.agent/backend/RESULT.md`, `AGENTS.md`,
`SECURITY.md`, and `TASKS.md`. The backend result was treated as a claim to
verify, not as evidence by itself. No application code, task metadata,
`CONTEXT.md`, frontend, ML, docs, or backend result files were modified.

## Control verification

### Provider-neutral identity and uniqueness — PASS

- `UserIdentity` stores `issuer` and `subject` with the database-level unique
  constraint `uq_user_identities_issuer_subject`
  (`backend/app/models.py:74-100`).
- Migration `0002_authentication_boundary` creates the same provider-neutral
  table, unique constraint, and owner foreign key
  (`backend/alembic/versions/0002_authentication_boundary.py:20-34`).
- The provider returns issuer/subject, the service validates the issuer, and the
  repository resolves identities by `(issuer, subject)` rather than email
  (`backend/app/providers/google.py:29-35, 213-262`; `backend/app/services/auth.py:275-284`;
  `backend/app/repositories/auth.py:101-140`).
- SQL and in-memory tests cover same-subject/different-issuer separation and
  mutable email updates.

### PKCE model, migration, repository, and flow — PASS

- `OAuthTransaction.code_challenge` is mapped as non-null `String(43)`
  (`backend/app/models.py:140-164`).
- Migration `0002` creates the matching non-null `String(43)` column
  (`backend/alembic/versions/0002_authentication_boundary.py:52-63`).
- The repository persists, matches, returns, and atomically consumes the exact
  challenge (`backend/app/repositories/auth.py:142-199`).
- The service generates the verifier/challenge, signs the verifier into the
  short-lived HttpOnly flow cookie, and sends the verifier only to the backend
  token exchange (`backend/app/services/auth.py:99-125, 143-174`). The provider
  uses S256 and sends the fixed configured redirect URI
  (`backend/app/providers/google.py:146-181`).
- SQL repository tests verify persistence, mismatch rejection, successful
  consume, and replay rejection (`backend/tests/test_auth_repository.py:69-102`).

### Atomic one-use OAuth transaction — PASS

The SQL repository uses a single conditional `UPDATE` requiring state hash,
browser binding hash, PKCE challenge, unused status, and unexpired status, then
accepts only `rowcount == 1` (`backend/app/repositories/auth.py:164-199`). The
in-memory concurrent replay test passes, and the SQL path was independently
verified for mismatch, successful one-use consumption, and replay rejection.

### Redirect, state, nonce, cross-session, replay, and concurrency — PASS

- Configuration rejects query/fragment/credential-bearing redirect URIs and
  requires the exact `/api/v1/auth/callback` path
  (`backend/app/config.py:51-59, 147-151`). Provider and post-login redirects
  are configuration-derived, never request-derived.
- State, nonce, browser binding, and PKCE values are random, short-lived,
  signed/hashed, and checked before local identity resolution
  (`backend/app/services/auth.py:99-180`).
- Callback validation rejects missing, malformed, mismatched, expired,
  cross-flow, nonce-failed, and reused transactions. Tests cover these cases and
  concurrent one-use behavior (`backend/tests/test_auth_service.py:93-169, 240-262`).

### Claims and bounded token validation — PASS

The provider enforces the fixed Google issuer, RS256/JWT header, key ID and
trusted fixed JWKS endpoint, signature, audience/`azp`, integer `exp`/`iat`/`nbf`,
bounded token lifetime, nonce, non-empty subject, and verified email
(`backend/app/providers/google.py:191-262`). Token, JWT segment, JWKS, and HTTP
response sizes are bounded, redirects are disabled, and provider failures are
normalized. Synthetic tests cover signature tampering, issuer, audience, nonce,
subject, expiry, old/future issue time, and lifetime failures
(`backend/tests/test_google_provider.py:79-169`).

### Cookies, CSRF, Origin, and session fixation — PASS

- Session cookies are HttpOnly, Secure when configured, SameSite-controlled,
  host-only, and scoped to `/api/v1`; the OAuth flow cookie is HttpOnly/Secure,
  SameSite=Lax, and scoped to `/api/v1/auth`
  (`backend/app/routes/auth.py:25-55, 64-72`). Production configuration fails
  closed if Secure is disabled (`backend/app/config.py:86-97, 131-141`).
- Logout requires the exact configured frontend Origin plus a matching
  double-submit CSRF cookie/header and server-side CSRF hash
  (`backend/app/services/auth.py:238-267`). Route tests cover missing and
  untrusted Origin and missing CSRF proof.
- Authentication creates a new random session token, so the pre-auth flow value
  is not reused as an authenticated session identifier.

### No-store responses and bounded errors — PASS

Login, callback, logout, `/auth/me`, validation errors, and auth errors set
`Cache-Control: no-store` (`backend/app/routes/auth.py:58-62, 100-106, 124-161`;
`backend/app/main.py:43-79`). Error bodies are bounded and do not expose stack
traces, provider details, secrets, or account-existence information.

### Session idle/absolute expiry, rotation, revocation, and stale users — PASS

`AuthSession` stores creation, last-seen, absolute expiry, and revocation state
(`backend/app/models.py:105-137`; migration lines 36-50). Active-session queries
enforce revocation, absolute expiry, and idle expiry while updating last-seen
(`backend/app/repositories/auth.py:226-254`). Tests cover distinct session
rotation, idle and absolute expiry, logout revocation, and deleted-user/stale
session rejection (`backend/tests/test_auth_service.py:172-237`).

### Owner-constrained authorization and IDOR — PASS for TASK-004 surface

`EventRepository.get_owned_event` places both the resource ID and authenticated
owner ID in the SQL predicate (`backend/app/repositories/events.py:13-22`).
`AuthorizationService` returns the same non-enumerating not-found result for
missing or foreign resources (`backend/app/services/authorization.py:20-29`),
with synthetic horizontal-access coverage
(`backend/tests/test_authorization.py:16-51`). Broader resource CRUD ownership
coverage is part of dependent TASK-005/TASK-006 work; no such routes are exposed
by TASK-004.

### Logging and supported Uvicorn entrypoint — PASS

- The supported command is `.venv/bin/python -m backend.app.server`
  (`README.md:81-92`; `backend/README.md:15-27`).
- `backend/app/server.py:17-26` invokes Uvicorn with `access_log=False` and
  `log_config=None`, preventing default request-line access logging for OAuth
  callback query parameters. The server regression test asserts both settings
  and checks that request-line/query logging code is absent
  (`backend/tests/test_server.py:8-24`).
- No application logging emits callback URLs, codes, state/nonce values,
  authorization headers, cookies, tokens, raw claims, provider payloads,
  household data, or database URLs. Generic application error handlers do not
  log provider exceptions or expose them to clients.

### Provider egress and response limits — PASS for application boundary

The provider adapter uses fixed HTTPS Google authorization, token, and JWKS
hosts; five-second timeouts; disabled redirects; and incremental 256 KiB
response limits (`backend/app/providers/google.py:48-99, 130-167`). No URL is
accepted from a browser or provider response as an outbound destination.

### Dependencies and layering — PASS

Provider HTTP/JWT details remain in the provider adapter; routes call services;
repositories own database access; provider SDK details do not reach routes or
the frontend. Runtime dependencies are pinned in `backend/requirements.txt`.
`pip check` passed and `.venv/bin/pip-audit --local --strict` reported no known
vulnerabilities. No dependency is imported from a browser boundary.

## Residual medium/low risks

- **MEDIUM:** Login/callback rate limiting and a bound on outstanding short-lived
  OAuth transactions are not visible. Add abuse controls before production use.
- **MEDIUM:** The application fixes provider hosts, but deployment-level DNS,
  proxy, and egress policy must still block private, loopback, link-local, and
  metadata destinations and should be verified with deployment tests.
- **MEDIUM:** Live Google and PostgreSQL integration was unavailable during this
  review. Synthetic provider transports and isolated SQLite/Alembic checks passed;
  perform a controlled staging smoke test before production.
- **LOW:** Direct dependencies are pinned but no hash-locked requirements
  artifact is present; add reproducible hash/lock generation before deployment.
- **LOW:** Existing Starlette/httpx deprecation warnings should be resolved to
  keep the security test harness current.

## Review decision

**PASS.** No CRITICAL or HIGH security finding remains in the current TASK-004
implementation. The previous PKCE persistence mismatch and unsafe default access
logging path are fixed and independently verified. Residual items above are
MEDIUM/LOW hardening or deployment verification risks and do not block TASK-004.
