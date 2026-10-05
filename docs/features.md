# Sleep-history features, version 1

## Component and input contract

`ml.features.FeatureService` is a deterministic standard-library-only component.
It consumes normalized events and explicit prediction context, then returns an
immutable, validated numerical vector. It has no HTTP/request, FastAPI, database,
provider, model, filesystem-write, or logging dependency.

```python
from ml.features import FEATURE_NAMES, FeatureService

vector = FeatureService().build(
    authorized_event_history,
    baby_id=authorized_baby_id,
    as_of=prediction_time,
    timezone_name=baby_timezone,
    date_of_birth=baby_date_of_birth,  # Optional; never infer it from events.
)
model_columns = FEATURE_NAMES
model_values = vector.values
```

The caller authenticates and retrieves only the selected baby's authorized
history. The feature layer requires a UUID `baby_id` and checks **every** record
against it, including records that will be excluded by time. A foreign or invalid
record baby ID rejects the whole history with `invalid_history_scope`; records
missing required fields are malformed and produce `invalid_event`.

Input records satisfy the read-only `NormalizedEventLike` protocol:

- `baby_id`: UUID matching the selected baby;
- `event_type`: `sleep`, `feed`, or `wake` (string-valued enums are supported);
- `start_time`: aware datetime;
- `end_time`: aware datetime or `None`;
- `duration_seconds`: whole integer seconds or `None`.

The existing backend repository `EventRecord` satisfies this contract. Pure
offline callers can use `ml.features.HistoryEvent`. Additional record fields
(IDs, source, notes, feed amounts, audit dates, provider data) are not read.
Naive timestamps are rejected; the event/import boundary resolves local/DST
timestamps before supplying normalized history. Equivalent aware offsets are
converted to UTC. No current clock is read: `as_of` is always explicit.

All supplied records are validated, including old/future records. Invalid types,
unknown event kinds, negative/inconsistent/overlong durations, reversed end times,
timestamp overflow, and wake records with end/duration reject the whole history.
Intervals are at most seven elapsed days. Duration-only records derive their end
in UTC; end-only records derive elapsed duration during feature computation.
At most 10,000 input records are consumed, including duplicates and excluded
records. An oversized/infinite iterable stops at record 10,001.

## Feature order, units, bounds, and missing values

`FEATURE_VERSION = "sleep-history-v1"`. The order below is exactly
`FEATURE_NAMES` / `FeatureVector.values`. Definitions and validation bounds are
also machine-readable through `FEATURE_DEFINITIONS`.

All output values are finite numeric floats. Unknown optional timing/age values
use **`-1.0`**, which cannot collide with their nonnegative measured domain.
`metadata.missing_features` explicitly lists them in vector order. Booleans,
non-numeric values, NaN/Infinity, wrong dimensions/version, out-of-range values,
fractional counts/age, and inconsistent missing-feature metadata are rejected
when a vector is constructed. Features use raw documented units, without fitted
scaling or imputation. A model adapter must honor the version/order and explicit
missingness contract.

| Index | Feature | Definition | Valid measured range | Missing policy |
| --- | --- | --- | --- | --- |
| 0 | `hour_of_day` | Local hour + minute/60 + second/3600 + microsecond/3,600,000,000 at `as_of`, in the supplied IANA timezone. | `[0, 24)` hours | Always known from context. |
| 1 | `minutes_since_last_feed` | UTC elapsed minutes from the latest feed **start** in the seven-day window to `as_of`. Feed completion is not required. | `[0, 10,080]` minutes | `-1` if no eligible feed. A feed at `as_of` is known zero. |
| 2 | `last_sleep_duration_minutes` | Full UTC elapsed duration of the completed sleep with the latest end; latest start breaks equal-end ties. | `[0, 10,080]` minutes | `-1` if no eligible completed sleep. Zero-duration completed sleeps are known zero. |
| 3 | `recent_sleep_duration_minutes` | Arithmetic mean of the latest **up to three** eligible completed sleep durations, ordered as above. | `[0, 10,080]` minutes | `-1` if none. One/two observed bouts are averaged without fabricated observations. |
| 4 | `rolling_12h_sleep_minutes` | Union of completed sleep intervals intersected with the last 12 **elapsed UTC hours**. | `[0, 720]` minutes | Zero observed completed sleep if none; an observed lower bound, not evidence of no real sleep. |
| 5 | `rolling_24h_sleep_minutes` | Same union/intersection rule over 24 elapsed UTC hours. | `[0, 1,440]` minutes | Same observed-lower-bound policy. |
| 6 | `recent_wake_interval_minutes` | UTC elapsed minutes between the latest two distinct explicit wake starts in the seven-day window. It is an inter-wake gap, not inferred time awake. | `[0, 10,080]` minutes | `-1` if fewer than two distinct wakes. Sleep endings do not invent wakes. |
| 7 | `recent_feed_count` | Number of unique feed starts in the last 12 elapsed hours. | Integer `[0, 10,000]` | Zero observed records if none; logging completeness is unknown. |
| 8 | `recent_sleep_count` | Number of unique sleep starts in the last 12 elapsed hours, including incomplete sleeps. | Integer `[0, 10,000]` | Same observed-record policy. Sleeps beginning before the window do not count as new starts. |
| 9 | `day_of_life` | Local calendar date at `as_of` minus the supplied date of birth. Birth date is day **0**. | Integer `[0, 3,652,058]` days (Python date range) | `-1` if birth date is absent. Future local birth dates and non-date inputs are rejected. |
| 10 | `is_night` | `1` from local **19:00 inclusive to 07:00 exclusive**, otherwise `0`. A fixed product convention, not a medical sleep recommendation. | `{0, 1}` | Always known from context. |
| 11 | `incomplete_sleep_count` | Number of unique eligible sleep records with no effective end, or with an effective end after `as_of`. | Integer `[0, 10,000]` | Zero if none observed. Marks exclusion from duration/rolling features. |
| 12 | `history_span_minutes` | UTC elapsed minutes since the earliest eligible unique event start, clipped to the seven-day window. | `[0, 10,080]` minutes | Zero if there is no eligible history. Span is not proof of continuous logging. |

Any change in order, semantics, units, missingness, windows, night convention, or
validation bounds requires a new feature version and corresponding model inputs.

## Time windows and incomplete records

- The metadata window is `(as_of - 7 days, as_of]` in UTC. Point events at its
  lower boundary are excluded; events starting exactly at `as_of` are included.
- Completed sleep that starts earlier but ends after the lower boundary is kept,
  allowing carry-in intervals. Callers must retrieve overlapping sleeps, not
  just starts inside the window. With a seven-day maximum duration, an upstream
  start-based query may need up to 14 days of records to include all carry-in
  sleeps; the component still enforces its input-count budget.
- Recent event counts use `(as_of - 12 hours, as_of]`. Sleep durations measure
  interval overlap, so a sleep starting exactly at the lower boundary contributes
  duration but is not a new-start count. A sleep ending exactly at the lower
  boundary contributes zero overlap.
- Durations are UTC elapsed time, not local clock subtraction. Spring-forward
  and repeated fall-back hours do not shorten/lengthen an interval incorrectly.
  Hour, night/day, and day of life use local time. A local day can be 23 or 25
  hours while a rolling 24-hour window remains exactly 24 elapsed hours.
- Starts after `as_of` are excluded with provenance counts. A sleep ending after
  `as_of` is incomplete for that historical snapshot; its eventual duration and
  rolling contribution are excluded, preventing future completion labels from
  leaking into features. Incomplete starts still count as observed starts.
- Start-only sleeps are never extended to `as_of`: an unclosed record could be
  stale. They contribute only to start/incomplete counts and observation span.
  A future snapshot can use the completed interval once an end is available.
- Rolling sleep merges overlapping/touching intervals before measuring duration.
  It never exceeds the window length. Bout averages and start counts describe
  unique recorded bouts; overlap does not manufacture additional elapsed sleep.
- Feature identity is `(event_type, UTC start, as-of-visible UTC end)`. An end
  after `as_of` is treated as absent before duplicate handling, so future labels
  cannot change duplicate or start counts. Exact
  duplicates, equivalent offsets, and duration-only/end-only equivalents are
  collapsed. Feed amount/source/record IDs do not change a feature observation.

## Sparse-history metadata

`FeatureVector.metadata` contains only provenance/quality fields, not history:

- `as_of_utc`, `window_start_utc`, `timezone_name`;
- `input_event_count`, `used_event_count`, `duplicate_event_count`;
- `excluded_future_event_count`, `excluded_old_event_count`;
- `missing_features` and `insufficient_history`.

`used_event_count` is unique time-eligible records. Counts reconcile as input =
used + duplicate + future + old. Future/old duplicates are counted in those
excluded categories because exclusion precedes duplicate handling.

`insufficient_history` is true when observation span is under 24 hours, fewer
than two sleeps have completed, no feed is observed, or fewer than two distinct
wakes are observed. This versioned conservative quality heuristic is **not**
model confidence, a readiness guarantee, or medical advice. An empty or first-ever
event history still yields a valid vector with explicit missingness. Missing birth
date alone does not change the history-quality heuristic.

Observed zeros/counts and short spans do not establish logging completeness.
Sparse-history policy in the future explicit baseline/model must consider the
metadata rather than manufacture confidence from a finite vector.

## Privacy, failures, and verification

- The component emits no logs, output, network calls, persistence, or model prompts.
  Its service is stateless; histories are neither cached nor pooled across calls.
- Input DTOs, vectors, and metadata omit sensitive fields from automatic `repr`.
  Numerical aggregates are still sensitive household data; explicit mappings or
  metadata must not be logged or sent to providers without a reviewed boundary.
- `FeatureValidationError` uses fixed codes: `invalid_history`,
  `invalid_history_scope`, `invalid_event`, `history_too_large`, `invalid_context`,
  `invalid_timezone`, `invalid_birth_date`, `invalid_feature_vector`,
  `invalid_feature_metadata`, and `invalid_feature_version`. Validation errors
  do not interpolate event contents, identifiers, timestamps, or input strings.
- Unit tests are synthetic and deterministic. They cover every feature, empty/
  first/sparse history, incomplete and future-completed sleeps, offsets/midnight/
  DST, exact window boundaries, overlaps, duplicates, malformed input, bounds,
  finite output, immutability, mixed-baby isolation, bounded iterables, stateless
  calls, silent logs/output, and a standard-library-only import boundary.

Run from the repository root: `.venv/bin/python -m pytest ml/tests -q`.
The root pytest configuration also discovers these tests during the full suite.
