# ElevenLabs speech and audio

TASK-012 adds an optional, owner-scoped speech flow:

```text
authenticated audio route
        ↓
AudioService → SpeechService → ElevenLabsProvider
        ↓                 ↓
audio reference      external audio storage
        ↓
PostgreSQL audio metadata
```

Routes remain thin. `SpeechService` owns text validation, timeout, concurrency,
disabled-mode behavior, and the optional bounded in-process cache. The provider
owns ElevenLabs protocol details. The audio service authorizes the prediction
and summary, persists only an external storage reference, and enforces expiry.

## Configuration

Names only are also listed in `.env.example`:

| Variable | Behavior |
| --- | --- |
| `TTS_DISABLED` | Set to `1` to run without a key, voice, storage root, or provider call. |
| `ELEVENLABS_API_KEY` | Server-side ElevenLabs credential. It never enters browser responses, audio text, or logs. |
| `ELEVENLABS_VOICE_ID` | Bounded operator-selected voice identifier. |
| `ELEVENLABS_MODEL` | Bounded operator-selected model identifier; defaults to `eleven_multilingual_v2`. |
| `TTS_TIMEOUT_SECONDS` | Provider/service timeout from 0.1 to 30 seconds; defaults to 10. |
| `TTS_CACHE_ENABLED` | Set to `1` for the bounded 128-entry in-process cache; disabled by default. |
| `TTS_CACHE_TTL_SECONDS` | Cache lifetime from 60 to 86,400 seconds; defaults to 3,600. |
| `AUDIO_STORAGE_ROOT` | Absolute operator-managed directory outside the database and web source tree. Required when TTS is enabled. |
| `AUDIO_RETENTION_SECONDS` | Reference/blob retention from 300 to 604,800 seconds; defaults to 86,400. |

When TTS is disabled, the application still serves health, authentication,
event, prediction, and summary functionality. An audio request returns a fixed
temporary-unavailable response; it does not attempt provider or storage access.
Missing/invalid enabled configuration fails closed for audio and does not make a
browser-supplied value authoritative.

## API behavior

`POST /api/v1/babies/{baby_id}/predictions/{prediction_id}/audio` requires the
live session, exact configured origin, and session-bound CSRF proof. Ownership is
checked before body validation and provider/storage use. It accepts no request
body and returns an expiring metadata reference. The latest unexpired reference
is available through the authenticated metadata and content GET routes. DELETE
removes the external bytes before deleting the owner-checked database reference.

The spoken source is the latest summary for the selected owned prediction. The
repository revalidates stored summary text against the validated numerical
prediction; tampered historical prose is replaced with the deterministic local
summary. Raw histories, identity, notes, imported CSV text, prompts, provider
responses, and storage bytes are not included in the API metadata.

Provider failures, malformed output, storage failures, timeouts, and capacity
limits return fixed private errors. They never alter the numerical prediction
or summary and never prevent the rest of the application from operating.

## Storage and retention

The database stores provider/version, content type, byte size, creation time,
expiry, and a generated opaque key. Audio bytes are not stored in PostgreSQL,
Git, the frontend bundle, or a web-served source directory. The current storage
adapter uses an operator-provided filesystem root as an external backing
implementation; a deployment may replace it behind `AudioStorage`.

`AudioService.purge_expired()` is the maintenance hook. It deletes the external
object before its expired database reference and is safe to retry. Baby/account
deletion orchestration must call the same external-object deletion path before
the database cascade is used in a production deployment.

## Security review

- Provider host and path are fixed to `https://api.elevenlabs.io`; voice/model
  values are bounded configuration, not request-selected URLs.
- DNS answers must all be public unicast addresses, one resolved destination is
  pinned, TLS uses the original host, proxies/redirects/retries are not used,
  and response MIME, encoding, status, actual byte count, and timeout are
  bounded.
- Summary text is capped at 300 reviewed ASCII characters. Output is limited to
  2 MiB of `audio/mpeg`; generated storage keys are opaque and traversal-safe.
- Provider keys are sent only in server-side headers. Exceptions use fixed
  codes, and no raw text, provider response, key, or audio bytes are logged.
- Session ownership is joined in repository queries for every read/write/delete;
  cross-user and missing resources share the same response.
- Cache entries are process-local, bounded, keyed by model plus validated text,
  and expire. The cache is disabled by default for privacy.

Synthetic tests cover disabled mode, configuration injection, mocked successful
and failing provider responses, timeout, cache reuse, authorization-before-
provider behavior, failed-persistence cleanup, storage traversal, and retention
configuration. No new runtime dependency or migration is required.
