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
- Baby list, read, update, and delete queries include the authenticated user's
  ID in the database predicate. The baby API rejects client-supplied `user_id`
  fields and returns the same not-found response for missing and foreign IDs.
- Event list/create queries verify the nested baby owner, while event update and
  delete queries join through the baby owner. Event mutations require the
  session-bound CSRF proof and configured origin.
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
- Credentialed CORS allows only that configured origin, `GET`/`POST`/`PATCH`/
  `DELETE`, and the `Content-Type`/`Content-Disposition`/`X-CSRF-Token` headers.
  Wildcard origins are never combined with credentials. Production origins and redirect URIs must
  use HTTPS.
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
- Event timestamps may be converted from an explicitly validated IANA timezone
  to UTC, but ambiguous daylight-saving and nonexistent local times are rejected.
- Event `source`, `baby_id`, ownership, and audit timestamps are server-managed;
  clients may not mass-assign them. Feed amounts, durations, event types, and
  start/end relationships are bounded and cross-validated.

## File upload security

- Huckleberry imports must be limited to the expected CSV format, size, row
  count, encoding, and columns.
- Treat file names, MIME types, extensions, and CSV cells as untrusted. Do not
  execute file content or place uploads in a web-served directory.
- The implemented raw-CSV endpoint never stores original uploads on disk. Any
  future storage must be outside the source tree and served directories, use
  safe temporary files, and have a reviewed deletion policy.
- Defend against CSV formula injection on export or display and against parser
  resource exhaustion.

### Implemented CSV import boundary (TASK-007)

- `POST /api/v1/babies/{baby_id}/imports` requires a live server session,
  session-bound CSRF proof, and the exact configured origin. Repository ownership
  is checked before body consumption and again inside the transaction. CSVs
  cannot supply ownership, source, or audit fields; foreign and missing babies
  have identical not-found errors.
- Accept only raw `text/csv`/`application/csv` bodies and UTF-8 (optional BOM).
  Reject multipart, executable/binary/archive MIME types, invalid encoding,
  duplicate upload metadata headers, and unsafe filename metadata. Filenames
  are short ASCII `.csv` basenames and are never used for filesystem access.
- Count actual streamed bytes independently of `Content-Length`. Default budgets
  are 2 MiB and 10,000 records; configurable hard ceilings are 10 MiB and 10,000
  records. Bound columns (32), cell characters (4,096), logical record characters
  (16,384), reported errors (100), receiving time (30 seconds), and concurrent
  imports (four per application service/process). Excess imports return `429`.
  Invalid limit configuration fails closed.
- Validate column allowlists, dates, IANA timezones/DST, decimals, units, durations,
  event types, and cross-field relationships. Check every cell, including ignored
  free text, for formula prefixes and unsafe control/format characters. Store
  only normalized typed events; discard notes, details, and condition text.
- Structural corruption and file-level budget failures abort without writes.
  Row-level errors are fixed codes and physical line numbers, never raw records.
  Transaction failures roll back all valid rows. PostgreSQL baby-row locking
  serializes imports; duplicate queries remain owner- and baby-scoped and batched.
- Uploaded bytes are never executed, evaluated, passed to shells, logged, rendered
  as raw HTML, used for URL fetches, or sent to Gemma or other providers. Buffers
  are request-scoped and originals have no retention. Imported events use the
  existing owner-authorized event/baby deletion path, including cascade deletion.
- Synthetic tests cover parser/streaming limits, formula/control injection,
  malicious text, filenames/traversal, MIME/encoding, CSRF, cross-user access,
  privacy of errors/logs, duplicates, timeout/concurrency, and transaction rollback.
  No new runtime dependency or database migration is introduced. No CRITICAL or
  HIGH finding was identified in this feature review. Full upload semantics and
  remaining live-provider/PostgreSQL verification are in `docs/imports.md`.

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

### Standalone Gemma summary boundary (TASK-010)

- SummaryService revalidates a completed numerical result and projects only
  expected remaining minutes, wake-within-60 probability, and baseline minutes.
  Unknown minimal-input fields, text coercion, invalid/nonfinite numbers, histories,
  imported notes, IDs, and personal data are rejected before provider invocation.
  Full prediction metadata never enters the prompt. Independent immutable copies
  isolate the caller and the output validator from provider-side input mutation.
- Fixed system instructions and delimited numeric JSON are the entire prompt.
  The provider has no tools, database/model access, request-selected host/model,
  or browser-visible credential. Secrets appear only in server-side headers.
- Strict JSON shape and 1,024-character content, 120-character sentence,
  one-to-three sentence, and 300-character final-text limits are enforced locally.
  Only reviewed sentences exactly grounded in source values can pass. A closed
  grammar excludes medical/emergency/feeding advice, fabricated facts/times,
  guarantees, instructions, private text, markup, and Unicode/control smuggling.
  Invalid output always uses deterministic local language; numeric results remain
  unchanged. Version/requested-model/outcome metadata is internal and contains no
  rejected text or exception details.
- Enabled environment configuration requires an explicit approved APP_ENV.
  Hosted endpoints require HTTPS, and staging/production require a credential.
  Invalid configuration fails closed for outbound calls. Only explicitly named
  development/test loopback servers receive the local HTTP exception.
- All DNS answers must be public unicast outside that exception, including mixed
  answer sets. Validated addresses are pinned, TLS verifies the original host,
  environment proxies are ignored, and redirects/retries are disabled. Fixed
  path, status/MIME/encoding checks, and 8-KiB actual response counting bound I/O.
- Four service slots and four process-wide transport slots bound concurrency.
  The caller's await budget is five seconds; sockets have a four-second deadline
  with shutdown even for trickled headers. System DNS cannot be forcibly cancelled
  by Python; resolver stalls occupy at most four transport workers. Resolver and
  deployment-wide egress/capacity configuration are owned by devops in TASK-017.
- The service retains no history, prompt, raw response, or summary on disk or in
  caches; private exceptions and DTO/result representations are silent/redacted.
  Hosted retention review precedes production family data; `store: false` is not
  a provider retention guarantee. TASK-011 owns authenticated HTTP integration,
  ownership checks, and authorized persistence/deletion.
- All 180 added summary/provider tests use synthetic data, mocked DNS/TLS, or
  explicit loopback HTTP. No new runtime dependency or migration is introduced;
  all 515 backend/ML tests pass. Changed files pass Ruff/strict mypy. Installed
  indexed-package and pinned ML-release audits report no known vulnerabilities;
  the CPU-specific Torch wheel remains unindexed. No CRITICAL/HIGH findings remain
  in this feature review. Live Gemma verification is pending; full contracts and
  remaining operator/integration work are documented in `docs/summaries.md`.

### Numerical prediction boundary

- Numerical inference has no Gemma, LLM, prompt, or text-provider dependency.
  Immutable validated predictions are created before the guarded summary flow.
- The explicit last-seven-day baseline uses only the selected baby's completed
  bouts and requires three independent surviving samples; sparse evidence yields
  `insufficient_history`, not a fabricated time/probability.
- TabPFN is a local optional adapter. Train on one baby's bounded numerical
  snapshots, use chronological whole-bout holdout with labels available before
  the training cutoff, and evaluate MAE/Brier without hiding failures behind
  baseline scores. Only baseline-improving evaluated artifacts are eligible.
- Production inference cannot fit or evaluate; it checks baby/model/feature
  scope/version, training/validation time, staleness, missing features, and target
  support. Reject nonfinite, out-of-range, malformed, and invalid-shape SDK output.
  Default fallback is explicitly identified as `baseline-7d-v1`; fail-closed mode
  is available. Missing baseline evidence always fails safely.
- SDK execution uses a spawned, bounded CPU worker with sanitized environment,
  offline settings, Python network-socket guard, and silent logs/stdout/stderr.
  Checkpoints are trusted operator-provisioned local artifacts, verified against
  expected SHA-256 before loading, never user uploads or `auto` downloads.
- Workers receive numerical matrices and minimal training provenance, have finite row/process/memory/time
  budgets, and are explicitly closed on rejected candidates or replacement.
  Fitted user context stays in process memory; original histories are not written
  to model artifacts. TASK-011 closes process-local workers on owned baby deletion,
  changes, expiry, replacement, and shutdown. Account/multi-process deletion needs
  the coordinated lifecycle hooks documented in the API review below.
- Model files/fitted state are Git-ignored. Optional dependency review repaired
  the setuptools vulnerability by pinning 83.0.0. Installed-runtime and pinned
  TabPFN/PyTorch/setuptools release audits report no known vulnerabilities; the
  CPU-specific Torch wheel itself is not indexed by pip-audit and is checked via
  its matching base release. No CRITICAL/HIGH feature findings remain.
- Synthetic numerical/privacy tests and the actual local CPU benchmark are
  documented in `docs/predictions.md`. Synthetic accuracy is not a real-family
  performance or medical claim; each selected baby's candidate must be evaluated.

### Authenticated prediction API boundary (TASK-011)

- POST `/api/v1/babies/{baby_id}/predict` and GET
  `/api/v1/babies/{baby_id}/predictions` require live server authentication. POST
  additionally requires session-bound CSRF and exact origin. Authentication and
  baby ownership precede body/history/ML/provider use; foreign and missing resources
  share fixed 404 responses. Dependencies cannot wire prediction DB/provider work
  before authenticating. The app's frozen environment is authoritative for Gemma.
- Accept empty/strict `{}` input only; server UTC time, profile, history, model,
  and numeric outputs cannot be mass-assigned. Bound actual body bytes to 1 KiB,
  receiving time to five seconds, queries to 8 KiB, list limit to 100 and offset
  to 10,000, and history to 10,000 plus a sentinel row. Reject unknown fields,
  nonfinite/duplicate JSON, text/URL/model smuggling, malformed IDs, and invalid
  metadata. Event snapshots and all persistence/list joins include the owner.
- Keep feature/model/baseline logic independent of HTTP/persistence. Only locally
  evaluated baby/revision-bound ApprovedModels are installable through a trusted
  offline Python interface; no request fits/evaluates/downloads or uploads models.
  Baseline evidence is mandatory; invalid model types/ranges/NaN/Infinity/booleans
  use the explicit baseline, while insufficient/invalid history fails safely.
- Revalidate final numerical/provenance output before writes. Immutable independent
  summary inputs and locally revalidated text prevent Gemma modifying any numerical
  source. The summary persistence method has no numerical write parameters.
  Stored numerical values/text are revalidated on GET; unsafe prose becomes local
  fallback. Public responses exclude private feature/provider/exception metadata.
- Recheck ownership/revision under coordinated PostgreSQL baby locks. History/profile
  changes during inference return conflict before writing/provider work. Numerical
  prediction plus local fallback summary commit atomically first; failures roll back
  without Gemma. Provider calls hold no DB locks. Final summary writes recheck owner;
  failure preserves the initial safe record and returns fixed 503. Deletion during
  provider work returns 404 and cascades persisted outputs. POST is not idempotent.
- Reviewed Alembic migration changes Numeric(5,4) to double precision, preserving
  the validated Python float across API/storage/summary grounding. Upgrade, schema
  parity, child preservation, rollback, and PG explicit-cast DDL tests pass. SQLite
  foreign-key-enabled batch parent rebuilds fail closed before possible cascades.
- Four pipeline slots/four actual process worker slots, 45-second await budget,
  and ten generations per owner per 60 seconds bound expensive work. Cancelled
  coroutines cannot release active worker capacity; pre-commit cancellation stops
  subsequent writes, but cannot undo an already-running commit. Deployers own DB
  connect/statement/lock deadlines and deployment-wide rates (devops, TASK-017).
- Two owner/baby models have serialized replacement/close leases, failed/stale/
  revision invalidation, mutation/import/profile/deletion callbacks, seven-day TTL,
  owner-clear hook, and shutdown close. Rejected offline candidates close. Expired
  cancelled timers cannot evict replacements. Multi-process/direct-account deletion
  requires coordinated lifecycle erasure before production family context retention
  (devops/security, TASK-015/TASK-017); no account deletion endpoint exists yet.
- Baby responses/errors have no-store/no-referrer/nosniff headers; raw histories,
  names, worker state, SQL/private exceptions, model/provider payloads, and secrets
  never enter errors/logs. No prompt/raw response/history arrays are persisted;
  only validated numerical metadata/summary text uses existing baby cascade retention.
- Full review and 89 added deterministic API/security/migration cases cover the
  requested authorization, cross-user, insufficient-history, model-failure,
  baseline-fallback, Gemma-failure, invalid-output, and persistence-failure paths,
  plus race/lifecycle/injection/budget/privacy regressions. All 604 tests pass;
  changed-file Ruff, strict core mypy, dependency consistency and indexed-runtime/
  pinned-release audits pass. No new runtime dependency, real data, credential,
  CRITICAL or HIGH feature finding. CPU Torch wheel is unindexed; matching base
  release checked. Live Gemma and PostgreSQL operational verification remain in
  `docs/prediction-api.md`, with deployment-item owners/targets recorded there.

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
