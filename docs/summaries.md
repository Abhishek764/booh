# Guarded Gemma summaries

TASK-010 implements a standalone Python service for short nighttime summaries of
already validated predictions. The numerical prediction is created first by
`ml.prediction.service.PredictionService`; Gemma chooses reviewed wording for that
result. It cannot compute or change the prediction.

## Service boundary

```text
Authorized caller with a validated numerical PredictionResult
    ↓
SummaryService: project and validate three numeric fields
    ↓
GemmaProvider: fixed instructions + delimited prediction JSON
    ↓
OutputValidator: schema, limits, exact grounding and reviewed language
    ↓
Validated plain text or deterministic local fallback
```

The implementation is in `backend/app/services/summaries.py`,
`backend/app/providers/gemma.py`, `backend/app/summary_contracts.py`, and
`backend/app/summary_config.py`. The provider has no database, history, tools,
authorization, or numerical-model access.

The preferred caller interface is:

```python
from backend.app.services.summaries import build_summary_service

service = build_summary_service()
summary = await service.summarize_prediction(validated_prediction)
```

`summarize_prediction` validates the immutable `PredictionResult` and projects
only the three approved numbers. `summarize` also accepts the independent
`SummaryInput` DTO or an exact three-key dictionary for standalone callers and
tests. These interfaces do not establish resource ownership themselves: callers
must already have authorized the source prediction. TASK-011 owns authenticated
HTTP integration, ownership checks, prediction lifecycle, and persistence.

## Input and privacy

Only these fields enter the prompt:

| Field | Type and bounds | Meaning |
| --- | --- | --- |
| `expected_sleep_minutes` | Native integer, 0–10,080 | Validated remaining-sleep estimate |
| `wake_probability_60m` | Finite native float or integer, 0–1; no booleans | Validated wake-within-60-minutes estimate |
| `baseline_minutes` | Native integer, 0–10,080 | Explicit seven-day baseline comparison |

No extra keys, coercion from text, notes, imported CSV cells, histories, names,
ages, IDs, timestamps, feature metadata, or numerical model versions are allowed
in the minimal input. Invalid input causes a nonnumeric unavailable summary and
no provider call. The full-result interface discards metadata before prompting.
Provider input is a separate immutable copy; output is checked against an
independent trusted copy so a provider cannot change its validation source.

Instructions have a fixed system role. The user role contains only compact JSON
inside `<prediction_json>` delimiters. Provider requests contain no tools, use
temperature zero, have a 160-token generation limit, disable streaming, and ask
for strict JSON-schema output with `store: false`. That flag is a request to the
operator's provider, not proof of its retention policy.

The API key is used only in the outbound Authorization header. It never appears
in prompts, returned errors, summaries, or automatic settings representations.
The service does not log prompts, responses, inputs, or private exceptions.

## Output contract and grounding

The generated content must be one JSON object containing exactly `sentences`, an
array of one to three strings. Duplicate keys, nonfinite constants, unknown
fields, tool/refusal messages, incomplete generation, code fences, and malformed
JSON are rejected. Content is bounded to 1,024 JSON characters, 120 characters per
sentence, and 300 joined text characters.

Instead of relying on a keyword blacklist, the validator accepts only a closed
set of reviewed sentences populated from the source numbers:

- First: a remaining-sleep estimate, such as
  `About 47 minutes of sleep may remain.`
- Optional second: the source baseline estimate, the exact source wake
  percentage, or an uncertainty sentence.
- Optional third: an uncertainty sentence after a baseline/probability detail.

Other reviewed openings are `Estimated sleep remaining is about … minutes.` and
`Sleep may last about … more minutes.` Baseline details are
`The baseline estimate is about … minutes.` or
`The seven-day baseline estimate is … minutes.` The probability sentence is
`Estimated chance of waking within 60 minutes is …%.` Uncertainty choices are
`Timing can vary.`, `This is an estimate, not a guarantee.`, and
`Actual timing may vary.`

Numbers, units, order, and punctuation must match exactly. Percentages use 100
times the decimal representation of the supplied probability, without a guessed
rounding step or dependence on the application's decimal context. If an extremely
small probability would require an overlong percentage, that optional sentence
is excluded; fallback uses the baseline detail instead. Zero is displayed as
zero, including a numerical negative zero.

The model therefore selects among safe grounded wording; it does not have an
unrestricted prose channel. Invented wake times, diagnoses, medication/feeding
instructions, emergency advice, guarantees, private text, instructions, markup,
Unicode/control smuggling, or altered numerical values cannot satisfy the
language contract. Accepted text is plain ASCII prose, never raw HTML.

`SummaryResult` contains:

- `text`: the validated/fallback text.
- `used_fallback`: whether Gemma content was replaced or not requested.
- `reason`: an internal fixed outcome code, or `None` for validated content.
- `summary_version`: `sleep-summary-v1`.
- `provider_model`: the configured requested model identifier for attempted
  generations, or `None` when no generation was attempted.

Version/outcome fields are internal integration metadata. The requested model
identifier is not an attestation of a remote server's actual weights. Automatic
DTO/result representations omit prediction and text fields.

## Deterministic fallback

Every provider/output failure uses local reviewed language derived from the same
unchanged numerical input. For the synthetic 47-minute/0.25/53-minute input:

> About 47 minutes of sleep may remain. Estimated chance of waking within 60
> minutes is 25%. Timing can vary.

When the input itself is invalid:

> A reliable sleep estimate is unavailable. Timing can vary.

Internal reasons are `invalid_summary_input`, `provider_disabled`,
`provider_configuration_invalid`, `provider_busy`, `provider_timeout`,
`provider_failed`, and `invalid_summary_output`. Exceptions and rejected text are
never copied into these codes. Caller cancellation propagates and releases the
service capacity; it is not converted into a fabricated success.

## Operator configuration and transport

Variable names are listed with empty values in `.env.example` and names only in
`CONTEXT.md`:

| Variable | Contract |
| --- | --- |
| `APP_ENV` | Required explicitly when enabling the provider; approved development/test/staging/production environment |
| `GEMMA_PROVIDER` | Empty or `disabled` uses local fallback; `openai` enables the Gemma OpenAI-compatible adapter |
| `GEMMA_BASE_URL` | Operator-controlled HTTP(S) origin, optionally ending in `/v1`; no credentials, query, fragment, or arbitrary path |
| `GEMMA_MODEL` | Reviewed Gemma identifier, optionally prefixed with `google/`; bounded ASCII identifier |
| `GEMMA_API_KEY` | Server-side credential; required for staging/production; never a browser or prompt field |

Invalid configuration disables outbound provider use while preserving local
fallback. HTTPS and a credential are required outside development/test. Only
explicit `localhost`, `127.0.0.1`, or `::1` development/test endpoints may use HTTP
or resolve to loopback. This enables a local Gemma-compatible server.

The fixed request path is `/v1/chat/completions`. For hosted endpoints, every DNS
answer must be public unicast; private, reserved, loopback, link-local, metadata,
shared-address, and multicast destinations are rejected, including mixed answer
sets. The connection pins the validated address without resolving again, uses
the original hostname for TLS verification/SNI and Host, and ignores environment
proxies. No redirects, automatic retries, or response-selected URLs are followed.

Budgets are four in-flight generations per service, four transport workers per
process, a five-second service await timeout, and a four-second transport deadline.
Socket timeouts plus a deadline-triggered shutdown bound connect/TLS/send/header/
body operations, including trickled responses. System DNS resolution runs in the
bounded worker pool; Python cannot forcibly interrupt `getaddrinfo`. The caller
still returns fallback within the service await budget, but a stuck resolver can
occupy up to four transport slots until the system resolver returns. Deployment
must configure resolver timeouts and egress/capacity controls (devops, TASK-017).

The response must have status 200, JSON UTF-8 MIME, no compression, and at most
8,192 actual body bytes. Declared lengths are checked but do not replace actual
byte counting. The compatible envelope requires one completed assistant choice
whose message contains only `role` and string `content`; unexpected tool/refusal
fields degrade to fallback. Strict-envelope incompatibility also degrades safely.

## Retention and integration state

No prompt, raw response, history, or summary is persisted or cached by this
standalone service. Buffers are call/worker-scoped and connections close on every
path. A hosted provider still sees the minimized numerical values: its handling
and retention must be reviewed before production family data is sent. Only a
reviewed configured endpoint should serve the selected Gemma weights.

The implementation is verified with synthetic stubs and actual loopback HTTP,
including deadline and failure paths. A live Gemma server/weights have not been
tested in this task. This is a bounded summary component, not evidence that Gemma
made numerical predictions or that the Hacktoberfest friend/demo goal is met.

## Verification

- `.venv/bin/python -m pytest backend/tests/test_summaries.py backend/tests/test_gemma_provider.py -q`
  — 180 synthetic safety/provider cases in the full suite.
- `.venv/bin/python -m pytest -q` — 515 backend/ML tests passed.
- Scoped Ruff (`E4,E7,E9,F,I`) and strict mypy on the four implementation files
  passed; dependency consistency and indexed installed/pinned-release audits
  passed. The CPU-specific Torch wheel is not indexed by pip-audit; its matching
  pinned base release was audited separately.

Tests cover exact grounding and percentage rendering, one-to-three sentence
shape/length, direct/indirect instruction smuggling, private-text exfiltration,
medical/guarantee/fabrication rejection, Unicode/control attacks, minimal full
prediction projection, defensive copying, silent errors, invalid configuration,
disabled/failing/busy/timed-out providers, cancellation, per-call isolation,
DNS/IP/SNI pinning, loopback HTTP, header-only credentials, redirects, MIME,
encoding, declared/actual byte limits, and trickled-header deadlines.
