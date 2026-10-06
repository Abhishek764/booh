# TTS Agent Result

TASK: TASK-012 — ElevenLabs speech service and owner-scoped audio flow
STATUS: DONE
Q&A CHECK: No blocking questions. TASK-011 and the existing audio-reference
schema were complete; the user explicitly requested configurable voice/model,
timeout/error handling, optional caching, disabled mode, mocked-provider tests,
security review, documentation, and the completion commit.
FILES CHANGED:
- `backend/app/speech_config.py`; `backend/app/speech_contracts.py` — validated
  operator settings, disabled/cache/timeout policy, and bounded private speech
  output contracts.
- `backend/app/providers/elevenlabs.py` — fixed-host ElevenLabs adapter with
  public-DNS validation, address pinning, original-host TLS, server-only key
  headers, no redirects/retries/proxies, and bounded audio responses.
- `backend/app/services/speech.py` — `SpeechService` provider orchestration,
  TTS_DISABLED behavior, timeout/concurrency limits, and optional 128-entry
  expiring in-process cache.
- `backend/app/audio_contracts.py`; `backend/app/audio_storage.py` — fixed API
  errors, owner-scoped reference contracts, and traversal-safe external storage.
- `backend/app/repositories/audio.py`; `backend/app/services/audio.py` — joined
  baby/prediction/summary ownership, reviewed summary source selection, external
  byte persistence, expiry, content retrieval/deletion, and purge hook.
- `backend/app/routes/audio.py`; `backend/app/dependencies.py`; `backend/app/main.py`
  — authenticated metadata/content/create/delete routes, lazy provider/storage
  wiring after authentication, and private fixed audio errors.
- `backend/tests/test_speech.py` — synthetic mocked success/failure/timeout,
  malformed output, disabled mode, cache, authorization order, owner predicate,
  storage cleanup/traversal, and configuration tests.
- `.env.example`; `backend/README.md`; `docs/README.md`; `docs/speech.md`;
  `SECURITY.md`; `CONTEXT.md`; `TASKS.md`; this result — environment, API,
  retention, security, task-state, and project-memory updates.
API CHANGES: Added authenticated owner-scoped `POST`, metadata `GET`, content
`GET`, and CSRF-protected `DELETE` routes at
`/api/v1/babies/{baby_id}/predictions/{prediction_id}/audio` and its
`/content` child. TTS-disabled or provider/storage failure returns a fixed
temporary-unavailable response; prediction and summary APIs remain independent.
DATABASE CHANGES: N/A. The existing audio-reference table is reused; no
migration or runtime dependency was added. Audio bytes remain outside PostgreSQL.
TESTS:
- `.venv/bin/python -m pytest -q` — 621 passed, one existing Starlette/AnyIO
  deprecation warning.
- Scoped Ruff `--isolated --select E4,E7,E9,F,I` on changed speech/audio Python
  files — passed.
- Strict mypy with silent follow imports on the nine changed core speech/audio
  files — passed.
- No new dependency or migration was introduced; existing full regression tests
  remained green.
SECURITY: Reviewed authentication/CSRF/origin ordering, owner-joined source and
  reference queries, foreign/missing resource equivalence, fixed ElevenLabs host,
  public-DNS filtering, pinned TLS destination, disabled proxies/redirects/
  retries, server-only API key, bounded reviewed text/audio, timeout/concurrency,
  optional privacy-default-off cache, MIME/encoding/actual-byte checks, opaque
  traversal-safe storage keys, restrictive file modes, expiry/deletion ordering,
  fixed private errors, and absence of raw text/provider/secret/audio logging.
  No CRITICAL or HIGH findings remain in this feature review.
COMMIT: `feat: add ElevenLabs voice service`
KNOWN ISSUES: Live ElevenLabs account/voice/model verification, provider data
retention review, production external-storage durability, multi-process expiry,
and account-deletion orchestration remain operational work. The local filesystem
adapter is an external backing implementation; deployment may replace it behind
the storage protocol. Resolver stalls and cluster-wide egress/rate controls stay
with TASK-017. No real family data or credentials were used.
NEXT DEPENDENCY: TASK-013 — accessible nighttime dashboard and prediction
presentation.
ASSUMPTIONS: Speech is advisory narration of an already validated summary. The
provider never predicts, authorizes, reads history, or changes numerical results.
TTS_DISABLED=1 is the safe default operation when no provider is configured;
enabled deployments provide an operator-managed absolute storage root and
retention policy. Cross-directory changes were required for provider/service,
authorized API/storage, tests, environment names, docs, security review, task
state, and project memory.
