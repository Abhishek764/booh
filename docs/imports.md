# CSV event imports

## API contract

`POST /api/v1/babies/{baby_id}/imports` requires an authenticated session, the
session-bound `X-CSRF-Token`, and the exact configured frontend `Origin`.
Ownership is checked before reading the upload and again in the write
transaction. Missing and foreign baby IDs return the same `404` response.

Send CSV bytes directly as the request body with `Content-Type: text/csv` or
`application/csv`. An optional `charset=utf-8` parameter is accepted. Multipart
forms, archives, binary formats, and other charsets are rejected. An optional
`Content-Disposition: attachment; filename="history.csv"` is validated as a
short ASCII CSV basename; the filename is never used for storage. Credentialed
CORS allows the `Content-Disposition` header for this upload flow.

Allowlisted query parameters:

| Name | Values / default | Meaning |
| --- | --- | --- |
| `format` | `auto` (default), `huckleberry`, `generic` | Adapter selection. Auto detection validates column schemas and prefers generic when both match. |
| `timezone` | IANA timezone; defaults to the owned baby profile's timezone | Conversion of local timestamps. A nonempty row timezone takes precedence. Aware timestamps keep their explicit offset. |
| `date_order` | `ymd` (default), `mdy`, `dmy` | Explicit interpretation of Huckleberry slash dates; never guessed. |

Unknown query parameters and invalid options are rejected. Event ownership,
source, and audit timestamps are server-controlled. Successful responses have
`Cache-Control: no-store` and `X-Content-Type-Options: nosniff`.

Example summary for the **synthetic** Huckleberry fixture:

```json
{
  "rows_processed": 6,
  "rows_imported": 3,
  "rows_skipped": 2,
  "rows_failed": 1,
  "duplicates": 1,
  "errors": [{"row": 7, "code": "invalid_date"}],
  "errors_truncated": false
}
```

The header is excluded from `rows_processed`. Blank records and explicitly
ignored activities count as skipped; duplicates are a subset of skipped rows.
On success, `rows_processed = rows_imported + rows_skipped + rows_failed`.
Errors report the one-based **physical starting line** of each failed record,
including multiline CSV records. They contain fixed codes, never cell values,
header values, filenames, SQL errors, or private event details. Only the first
100 errors are returned; failure totals remain complete.

## Supported schemas

The abstraction is `Importer` with independent `HuckleberryImporter` and
`GenericEventImporter` adapters. The shared parser uses Python's strict CSV
reader with comma delimiters, quoted cells, CRLF/LF, and quoted multiline text.
UTF-8 with an optional initial BOM is supported. Headers are case-insensitive,
whitespace-normalized, and underscore/space-equivalent. Reordering is supported.
Unknown, repeated, empty, and ambiguously mapped columns reject the file.

### Generic events

Required: `event_type`, `start_time`.

Optional: `end_time`, `duration_seconds`, `feed_amount_ml`, `timezone`, `notes`.

Types are `sleep`, `feed`, and `wake`. Dates use ISO `YYYY-MM-DD` with a time,
optional seconds/fractional seconds, and optional `Z` or `±HH:MM` offset.
Durations are whole seconds. Amounts are nonnegative decimal millilitres with
at most two decimal places; exponent, NaN, and Infinity forms are rejected.

### Huckleberry-style events

Required type aliases: `Type`, `Activity`, `Event Type`.
Required start aliases: `Start`, `Start Time`.

Optional: `End`/`End Time`, `Date` (split date/time exports), `Duration`,
`Amount`/`Amount (ml)`, `Units`/`Unit`, `Timezone`, `Notes`, `Details`,
`Start Condition`, `End Condition`. Only one alias per normalized field is allowed.

- `Sleep`/`Nap` become sleep; `Feed`/`Feeding`/`Bottle`/`Nursing`/`Breastfeeding`
  become feed; `Wake`/`Awake` become wake.
- `Diaper`, `Potty`, `Growth`, `Medicine`, `Pumping`, `Tummy Time`, and `Solids`
  are explicitly skipped because BOOH has no matching domain record. Other
  unknown types fail the row.
- Dates accept generic ISO or slash dates in the caller-selected order with
  24-hour or AM/PM times. Split `Date` plus start/end time columns are supported.
  Overnight split-time rows must supply a full timestamp instead; the importer
  does not silently move an end time to the next day.
- Durations accept `HH:MM`, `HH:MM:SS`, `1h 30m`-style units, or bare **minutes**.
- Amounts accept decimal `ml` or US fluid `oz`, as suffixes or a separate unit
  column. Ounces use `29.5735295625` ml per ounce, rounded half-up to two decimal
  places. Conflicting units fail. With no unit, amounts are interpreted as ml.

This allowlist is verified against synthetic fixtures, not private provider
exports. Provider schema/locale variants require a reviewed alias change and
synthetic regression coverage. Callers can explicitly select `huckleberry` when
a minimal header also matches the generic schema.

## Normalization, duplicates, and transactions

Both adapters reuse BOOH event validation: UTC timestamps, valid IANA timezones,
no guessed ambiguous/nonexistent DST times, bounded duration (seven days), feed
amount (10,000 ml), future skew (five minutes), and consistent type/start/end/
duration relationships. Imported events have server-managed `source=import`.
Missing end or duration is derived from the supplied counterpart using elapsed
UTC time. Wake records cannot have an end or duration.

Duplicate identity uses event type, UTC start, effective UTC end, and normalized
feed amount. It excludes source, notes, IDs, and audit timestamps. This detects
within-file, repeated-import, cross-format, and existing manual-event duplicates
for the selected baby only. Other babies and users have independent identities.

All rows are parsed before persistence. Malformed event rows are reported while
valid rows proceed. Structural CSV corruption, invalid file metadata, encoding,
header errors, and file-level resource-limit failures reject the entire import
without writes. Valid rows commit together; persistence failures roll back all batches.
The PostgreSQL transaction locks the owned baby to serialize concurrent imports,
and checks existing events only at incoming timestamps in bounded batches of 200.
SQLite supports deterministic isolated tests; PostgreSQL lock behavior still
requires the later live-service verification.

## Resource, privacy, and retention controls

- Default byte budget: 2 MiB (`MAX_UPLOAD_BYTES`), hard ceiling 10 MiB.
- Default row budget: 10,000 (`MAX_IMPORT_ROWS`), hard ceiling 10,000.
- At most 32 columns, 4,096 characters per cell, and 16,384 characters per logical
  CSV record, including quoted physical lines. Header/record/column budget
  violations abort; oversized cells fail their row.
- Actual streaming bytes are counted even with missing or false `Content-Length`.
  Upload reception has a 30-second deadline. At most four imports may receive,
  parse, or persist concurrently per application service/process; excess requests
  receive `429 import_busy` before reading the body.
- Missing/empty limit configuration uses finite defaults; invalid or out-of-range
  settings fail configuration. Deployment-wide rate/concurrency limits belong
  to the deployment boundary.
- All cells, including ignored notes, are checked for formula prefixes
  (`=`, `+`, `-`, `@`) after leading whitespace, and unsafe control/format
  characters. Unsafe rows are rejected. Only typed, normalized event values
  reach persistence; all free text is discarded.
- Uploads are never written to disk or a served directory, opened by filename,
  executed, evaluated, rendered as HTML, fetched as URLs, logged, or sent to
  Gemma or any other provider. Request-scoped buffers are released after the
  response; there is no retained original upload or background import artifact.
- Normalized events remain until the owner deletes the event or baby through
  the existing authorized APIs; baby deletion cascades to its events. Future
  backups/production retention are part of deployment/security review.

File-level errors use the standard JSON error shape with fixed codes:
`400` invalid metadata; `408 upload_timeout`; `413` resource budgets;
`415 unsupported_media_type`; `422` schema/encoding/CSV/option errors;
`429 import_busy`; `503 service_unavailable`. Authentication, CSRF, and ownership
errors retain their existing `401`/`403`/`404` contract.
