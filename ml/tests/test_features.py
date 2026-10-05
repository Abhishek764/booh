from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from types import SimpleNamespace
from uuid import uuid4

import pytest

from ml.features import (
    FEATURE_DEFINITIONS,
    FEATURE_NAMES,
    FEATURE_VERSION,
    MAX_HISTORY_EVENTS,
    FeatureService,
    FeatureValidationError,
    HistoryEvent,
)

BABY = uuid4()
AS_OF = datetime(2026, 1, 2, 12, tzinfo=timezone.utc)


def event(kind, start_minutes_ago, *, duration=None, end_minutes_ago=None, baby_id=BABY):
    return HistoryEvent(
        baby_id, kind, AS_OF - timedelta(minutes=start_minutes_ago),
        None if end_minutes_ago is None else AS_OF - timedelta(minutes=end_minutes_ago),
        duration,
    )


def build(history, **kwargs):
    return FeatureService().build(
        history, baby_id=kwargs.pop("baby_id", BABY),
        as_of=kwargs.pop("as_of", AS_OF), timezone_name=kwargs.pop("timezone_name", "UTC"),
        **kwargs,
    )


def test_every_feature_has_a_deterministic_known_value_and_fixed_order():
    history = [
        event("feed", 36 * 60), event("feed", 60),
        event("sleep", 28 * 60, end_minutes_ago=26 * 60),
        event("sleep", 23 * 60, end_minutes_ago=21 * 60),
        event("sleep", 10 * 60, end_minutes_ago=8 * 60),
        event("sleep", 5 * 60, end_minutes_ago=4 * 60),
        event("sleep", 3 * 60, end_minutes_ago=2 * 60),
        event("wake", 8 * 60), event("wake", 4 * 60),
    ]
    vector = build(history, date_of_birth=date(2025, 12, 30))
    expected = {
        "hour_of_day": 12.0,
        "minutes_since_last_feed": 60.0,
        "last_sleep_duration_minutes": 60.0,
        "recent_sleep_duration_minutes": 80.0,
        "rolling_12h_sleep_minutes": 240.0,
        "rolling_24h_sleep_minutes": 360.0,
        "recent_wake_interval_minutes": 240.0,
        "recent_feed_count": 1.0,
        "recent_sleep_count": 3.0,
        "day_of_life": 3.0,
        "is_night": 0.0,
        "incomplete_sleep_count": 0.0,
        "history_span_minutes": 2160.0,
    }
    assert vector.as_dict() == expected
    assert tuple(expected) == FEATURE_NAMES
    assert vector.values == tuple(expected.values())
    assert vector.feature_version == FEATURE_VERSION
    assert all(type(value) is float for value in vector.values)
    assert vector.metadata.as_of_utc == AS_OF
    assert vector.metadata.window_start_utc == AS_OF - timedelta(days=7)
    assert vector.metadata.used_event_count == len(history)
    assert vector.metadata.insufficient_history is False
    assert vector.metadata.missing_features == ()
    assert build(reversed(history), date_of_birth=date(2025, 12, 30)) == vector


def test_empty_history_produces_finite_values_and_explicit_missingness():
    vector = build([])
    assert vector.metadata.insufficient_history is True
    assert vector.metadata.input_event_count == vector.metadata.used_event_count == 0
    assert vector.metadata.missing_features == (
        "minutes_since_last_feed", "last_sleep_duration_minutes",
        "recent_sleep_duration_minutes", "recent_wake_interval_minutes", "day_of_life",
    )
    for name in vector.metadata.missing_features:
        assert vector.as_dict()[name] == -1.0
    for name in ("recent_feed_count", "recent_sleep_count", "rolling_12h_sleep_minutes", "rolling_24h_sleep_minutes", "history_span_minutes"):
        assert vector.as_dict()[name] == 0.0


@pytest.mark.parametrize("kind", ["feed", "wake", "sleep"])
def test_first_ever_event_does_not_manufacture_history(kind):
    vector = build([event(kind, 0)])
    features = vector.as_dict()
    assert vector.metadata.insufficient_history is True
    assert vector.metadata.used_event_count == 1
    assert features["history_span_minutes"] == 0.0
    assert features["recent_wake_interval_minutes"] == -1.0
    assert features["last_sleep_duration_minutes"] == -1.0
    assert features["minutes_since_last_feed"] == (0.0 if kind == "feed" else -1.0)
    assert features["recent_feed_count"] == float(kind == "feed")
    assert features["recent_sleep_count"] == float(kind == "sleep")
    assert features["incomplete_sleep_count"] == float(kind == "sleep")


@pytest.mark.parametrize("history", [
    [event("sleep", 10, duration=300), event("sleep", 20, duration=300), event("feed", 5), event("wake", 9), event("wake", 19)],
    [event("feed", 1500), event("wake", 500), event("wake", 100)],
    [event("sleep", 1500, duration=300), event("sleep", 100, duration=300), event("wake", 500), event("wake", 10)],
    [event("sleep", 1500, duration=300), event("sleep", 100, duration=300), event("feed", 50), event("wake", 10)],
])
def test_short_or_missing_event_type_history_remains_insufficient(history):
    assert build(history).metadata.insufficient_history is True


def test_recent_duration_uses_only_the_latest_three_completed_bouts():
    vector = build([
        event("sleep", 2000, duration=6000),
        event("sleep", 900, duration=1800),
        event("sleep", 600, duration=3600),
        event("sleep", 300, duration=5400),
    ])
    assert vector.as_dict()["last_sleep_duration_minutes"] == 90.0
    assert vector.as_dict()["recent_sleep_duration_minutes"] == 60.0


def test_latest_completed_sleep_is_ordered_by_end_not_start():
    vector = build([
        event("sleep", 300, end_minutes_ago=60),
        event("sleep", 120, end_minutes_ago=90),
    ])
    assert vector.as_dict()["last_sleep_duration_minutes"] == 240.0


def test_future_end_values_do_not_influence_as_of_features():
    shorter = build([event("sleep", 60, end_minutes_ago=-60)])
    longer = build([event("sleep", 60, end_minutes_ago=-120)])
    assert shorter == longer


def test_future_completion_labels_cannot_change_duplicate_or_start_counts():
    unknown = event("sleep", 60)
    labeled = event("sleep", 60, end_minutes_ago=-120)
    vector = build([unknown, labeled])
    assert vector.as_dict()["recent_sleep_count"] == 1.0
    assert vector.as_dict()["incomplete_sleep_count"] == 1.0
    assert vector.metadata.duplicate_event_count == 1
    assert vector == build([unknown, unknown])
    assert build([event("feed", 30), event("feed", 30, end_minutes_ago=-10)]).as_dict()["recent_feed_count"] == 1.0


@pytest.mark.parametrize("record", [
    event("sleep", 60, duration=1800),
    event("sleep", 60, end_minutes_ago=30),
    event("sleep", 60, end_minutes_ago=30, duration=1800),
])
def test_end_only_duration_only_and_consistent_sleep_records_are_equivalent(record):
    features = build([record]).as_dict()
    assert features["last_sleep_duration_minutes"] == 30.0
    assert features["rolling_12h_sleep_minutes"] == 30.0
    assert features["incomplete_sleep_count"] == 0.0


@pytest.mark.parametrize("record", [
    event("sleep", 60),
    event("sleep", 60, end_minutes_ago=-60, duration=7200),
])
def test_unclosed_or_not_yet_completed_sleep_cannot_leak_a_duration(record):
    features = build([event("sleep", 300, duration=1800), record]).as_dict()
    assert features["last_sleep_duration_minutes"] == 30.0
    assert features["recent_sleep_duration_minutes"] == 30.0
    assert features["rolling_12h_sleep_minutes"] == 30.0
    assert features["rolling_24h_sleep_minutes"] == 30.0
    assert features["recent_sleep_count"] == 2.0
    assert features["incomplete_sleep_count"] == 1.0


def test_zero_length_completed_sleep_is_known_zero_not_missing():
    vector = build([event("sleep", 0, duration=0)])
    assert vector.as_dict()["last_sleep_duration_minutes"] == 0.0
    assert "last_sleep_duration_minutes" not in vector.metadata.missing_features
    assert vector.as_dict()["incomplete_sleep_count"] == 0.0


def test_fractional_seconds_are_preserved_without_rounding_elapsed_minutes():
    vector = build([
        HistoryEvent(BABY, "sleep", AS_OF - timedelta(seconds=90.5), AS_OF),
        HistoryEvent(BABY, "feed", AS_OF - timedelta(seconds=30.5)),
    ])
    assert vector.as_dict()["last_sleep_duration_minutes"] == pytest.approx(90.5 / 60.0)
    assert vector.as_dict()["minutes_since_last_feed"] == pytest.approx(30.5 / 60.0)


def test_rolling_windows_clip_sleep_spanning_each_boundary():
    features = build([event("sleep", 30 * 60, end_minutes_ago=10 * 60)]).as_dict()
    assert features["last_sleep_duration_minutes"] == 1200.0
    assert features["rolling_12h_sleep_minutes"] == 120.0
    assert features["rolling_24h_sleep_minutes"] == 840.0
    assert features["recent_sleep_count"] == 0.0


def test_maximum_duration_sleep_is_clipped_to_rolling_budgets():
    vector = build([event("sleep", 10080, duration=604800)])
    assert vector.as_dict()["last_sleep_duration_minutes"] == 10080.0
    assert vector.as_dict()["rolling_12h_sleep_minutes"] == 720.0
    assert vector.as_dict()["rolling_24h_sleep_minutes"] == 1440.0


def test_only_old_history_has_missing_timings_not_zero_elapsed_times():
    vector = build([event("feed", 10081), event("sleep", 11000, duration=60)])
    assert vector.metadata.used_event_count == 0
    assert vector.metadata.insufficient_history is True
    assert vector.as_dict()["minutes_since_last_feed"] == -1.0
    assert vector.as_dict()["last_sleep_duration_minutes"] == -1.0


def test_overlaps_and_touching_intervals_are_unioned_not_double_counted():
    vector = build([
        event("sleep", 240, end_minutes_ago=120),
        event("sleep", 180, end_minutes_ago=60),
        event("sleep", 60, end_minutes_ago=0),
    ])
    assert vector.as_dict()["rolling_12h_sleep_minutes"] == 240.0
    assert vector.as_dict()["rolling_24h_sleep_minutes"] == 240.0
    assert vector.as_dict()["recent_sleep_count"] == 3.0


def test_exact_recent_boundaries_and_events_at_as_of_have_explicit_semantics():
    vector = build([
        event("feed", 720), event("feed", 0),
        event("sleep", 720, end_minutes_ago=660),
        event("sleep", 1440, end_minutes_ago=1380),
        event("sleep", 1500, end_minutes_ago=1440),
    ])
    assert vector.as_dict()["recent_feed_count"] == 1.0
    assert vector.as_dict()["recent_sleep_count"] == 0.0
    assert vector.as_dict()["minutes_since_last_feed"] == 0.0
    assert vector.as_dict()["rolling_12h_sleep_minutes"] == 60.0
    assert vector.as_dict()["rolling_24h_sleep_minutes"] == 120.0


def test_lookback_excludes_old_point_events_but_keeps_overlapping_completed_sleep():
    vector = build([
        event("feed", 10080), event("wake", 10081), event("sleep", 10081),
        event("sleep", 10080 + 60, end_minutes_ago=10080 - 60),
    ])
    assert vector.metadata.excluded_old_event_count == 3
    assert vector.metadata.used_event_count == 1
    assert vector.as_dict()["history_span_minutes"] == 10080.0
    assert vector.as_dict()["last_sleep_duration_minutes"] == 120.0
    assert vector.as_dict()["minutes_since_last_feed"] == -1.0


def test_future_starts_are_excluded_in_retrospective_generation():
    current = build([event("feed", 30), event("wake", 90), event("wake", 10)])
    future = build([event("feed", 30), event("wake", 90), event("wake", 10), event("feed", -1), event("sleep", -30, duration=300)])
    assert future.values == current.values
    assert future.metadata.excluded_future_event_count == 2


def test_malformed_future_events_are_validated_before_exclusion():
    with pytest.raises(FeatureValidationError, match="invalid_event"):
        build([event("unknown", -10)])


def test_semantic_duplicates_offsets_and_duration_representations_do_not_inflate_counts():
    sleep = event("sleep", 60, duration=1800)
    equivalent_sleep = replace(sleep, end_time=AS_OF - timedelta(minutes=30), duration_seconds=None)
    feed = event("feed", 10)
    equivalent_feed = replace(feed, start_time=feed.start_time.astimezone(timezone(timedelta(hours=-5))))
    wake = event("wake", 5)
    vector = build([sleep, equivalent_sleep, feed, equivalent_feed, wake, wake])
    assert vector.metadata.duplicate_event_count == 3
    assert vector.metadata.used_event_count == 3
    assert vector.as_dict()["recent_feed_count"] == 1.0
    assert vector.as_dict()["recent_sleep_count"] == 1.0
    assert vector.as_dict()["rolling_12h_sleep_minutes"] == 30.0
    assert vector.as_dict()["recent_wake_interval_minutes"] == -1.0


def test_latest_wake_interval_is_between_distinct_explicit_wake_instants():
    vector = build([event("wake", 100), event("wake", 40), event("wake", 15)])
    assert vector.as_dict()["recent_wake_interval_minutes"] == 25.0


@pytest.mark.parametrize("stamp,expected", [
    ("2026-01-02T06:59:59Z", 1.0), ("2026-01-02T07:00:00Z", 0.0),
    ("2026-01-02T18:59:59Z", 0.0), ("2026-01-02T19:00:00Z", 1.0),
])
def test_night_indicator_boundaries(stamp, expected):
    assert build([], as_of=datetime.fromisoformat(stamp)).as_dict()["is_night"] == expected


def test_local_midnight_day_of_life_and_fractional_offset_are_not_utc_dates():
    as_of = datetime(2026, 1, 2, 0, 30, tzinfo=timezone.utc)
    la = build([], as_of=as_of, timezone_name="America/Los_Angeles", date_of_birth=date(2026, 1, 1))
    assert la.as_dict()["hour_of_day"] == 16.5
    assert la.as_dict()["day_of_life"] == 0.0
    kathmandu = build([], as_of=as_of, timezone_name="Asia/Kathmandu")
    assert kathmandu.as_dict()["hour_of_day"] == 6.25
    assert kathmandu.as_dict()["is_night"] == 1.0


def test_aware_non_utc_reference_time_is_normalized_to_the_same_instant():
    reference = AS_OF.astimezone(timezone(timedelta(hours=5, minutes=30)))
    assert build([event("feed", 5)], as_of=reference) == build([event("feed", 5)])


@pytest.mark.parametrize("as_of,start,end,hour", [
    ("2025-11-02T06:30:00Z", "2025-11-02T01:15:00-04:00", "2025-11-02T01:15:00-05:00", 1.5),
    ("2025-03-09T08:30:00Z", "2025-03-09T01:30:00-05:00", "2025-03-09T03:30:00-04:00", 4.5),
])
def test_dst_folds_and_spring_forward_use_elapsed_utc_minutes(as_of, start, end, hour):
    vector = build([
        HistoryEvent(BABY, "sleep", datetime.fromisoformat(start), datetime.fromisoformat(end)),
    ], as_of=datetime.fromisoformat(as_of), timezone_name="America/New_York")
    assert vector.as_dict()["hour_of_day"] == hour
    assert vector.as_dict()["last_sleep_duration_minutes"] == 60.0
    assert vector.as_dict()["rolling_24h_sleep_minutes"] == 60.0


def test_day_of_life_changes_at_local_midnight_not_after_elapsed_24_hours():
    before = datetime(2026, 1, 2, 4, 59, tzinfo=timezone.utc)
    after = before + timedelta(minutes=1)
    assert build([], as_of=before, timezone_name="America/New_York", date_of_birth=date(2026, 1, 1)).as_dict()["day_of_life"] == 0.0
    assert build([], as_of=after, timezone_name="America/New_York", date_of_birth=date(2026, 1, 1)).as_dict()["day_of_life"] == 1.0


@pytest.mark.parametrize("record", [
    object(), {}, "synthetic-private-event", replace(event("wake", 10), event_type="unknown"),
    replace(event("wake", 10), event_type="=synthetic-private-event"),
    replace(event("wake", 10), event_type=42),
    replace(event("wake", 10), start_time="synthetic-private-timestamp"),
    replace(event("wake", 10), start_time=AS_OF.replace(tzinfo=None)),
    replace(event("sleep", 10), end_time=AS_OF.replace(tzinfo=None)),
    event("sleep", 10, end_minutes_ago=20),
    event("sleep", 30, end_minutes_ago=10, duration=600),
    event("wake", 10, duration=0), event("wake", 10, end_minutes_ago=0),
    event("sleep", 10, duration=-1), event("sleep", 10, duration=604801),
    event("sleep", 10, duration=True), event("sleep", 10, duration=30.0),
    event("sleep", 10, duration="30"), event("sleep", 10, duration=float("nan")),
    event("sleep", 8 * 24 * 60, end_minutes_ago=0),
    replace(event("sleep", 10), start_time=datetime.max.replace(tzinfo=timezone.utc), duration_seconds=1),
])
def test_malformed_events_fail_with_fixed_private_data_free_errors(record):
    with pytest.raises(FeatureValidationError) as failure:
        build([event("feed", 20), record])
    assert failure.value.code == "invalid_event"
    assert "synthetic-private" not in str(failure.value)


@pytest.mark.parametrize("zone", ["PST", "../etc/passwd", "/etc/passwd", "", " UTC", "UTC\x00", "x" * 65, None])
def test_invalid_timezone_names_are_rejected(zone):
    with pytest.raises(FeatureValidationError, match="invalid_timezone"):
        build([], timezone_name=zone)


@pytest.mark.parametrize("as_of", [None, "synthetic-private-date", AS_OF.replace(tzinfo=None), datetime.min.replace(tzinfo=timezone.utc)])
def test_invalid_reference_times_are_rejected(as_of):
    with pytest.raises(FeatureValidationError, match="invalid_context"):
        build([], as_of=as_of)


@pytest.mark.parametrize("dob", [date(2026, 1, 3), "2026-01-01", AS_OF])
def test_invalid_or_future_birth_dates_are_rejected(dob):
    with pytest.raises(FeatureValidationError, match="invalid_birth_date"):
        build([], date_of_birth=dob)


def test_birthday_in_utc_today_but_local_tomorrow_is_rejected():
    with pytest.raises(FeatureValidationError, match="invalid_birth_date"):
        build([], as_of=datetime(2026, 1, 2, 0, 30, tzinfo=timezone.utc), timezone_name="America/Los_Angeles", date_of_birth=date(2026, 1, 2))


def test_mixed_baby_history_is_rejected_even_for_old_and_future_events():
    for minutes in (10, 20000, -10):
        with pytest.raises(FeatureValidationError, match="invalid_history_scope"):
            build([event("feed", 20), event("wake", minutes, baby_id=uuid4())])
    with pytest.raises(FeatureValidationError, match="invalid_history_scope"):
        build([replace(event("feed", 10), baby_id=str(BABY))])
    with pytest.raises(FeatureValidationError, match="invalid_history_scope"):
        build([], baby_id=str(BABY))


def test_missing_event_collection_is_malformed_but_an_empty_collection_is_valid():
    with pytest.raises(FeatureValidationError, match="invalid_history"):
        build(None)


def test_bounded_iterable_consumption_stops_before_an_unbounded_history_can_exhaust_memory():
    consumed = 0

    def history():
        nonlocal consumed
        while True:
            consumed += 1
            yield event("feed", 10)

    with pytest.raises(FeatureValidationError, match="history_too_large"):
        build(history())
    assert consumed == MAX_HISTORY_EVENTS + 1
    vector = build(event("feed", 10) for _ in range(MAX_HISTORY_EVENTS))
    assert vector.metadata.input_event_count == MAX_HISTORY_EVENTS
    assert vector.metadata.duplicate_event_count == MAX_HISTORY_EVENTS - 1


def test_structural_normalized_records_and_string_enums_need_no_backend_dependency():
    class Type(str, Enum):
        FEED = "feed"

    record = SimpleNamespace(
        baby_id=BABY, event_type=Type.FEED, start_time=AS_OF - timedelta(minutes=5),
        end_time=None, duration_seconds=None, notes="synthetic-private-note",
    )
    vector = build([record])
    assert vector.as_dict()["minutes_since_last_feed"] == 5.0
    assert "synthetic-private-note" not in repr(vector)


def test_output_values_and_mapping_are_immutable_and_missing_metadata_is_validated():
    vector = build([])
    with pytest.raises(FrozenInstanceError):
        vector.values = ()
    mapping = vector.as_dict()
    mapping["hour_of_day"] = -100.0
    assert vector.as_dict()["hour_of_day"] == 12.0
    with pytest.raises(FeatureValidationError, match="invalid_feature_metadata"):
        replace(vector, metadata=replace(vector.metadata, missing_features=()))
    with pytest.raises(FeatureValidationError, match="invalid_feature_version"):
        replace(vector, feature_version="unknown")


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), True, "private", -1.0, 24.0, 10**1000])
def test_numerical_vector_rejects_nonfinite_nonnumeric_and_out_of_range_values(value):
    vector = build([])
    values = (value,) + vector.values[1:]
    with pytest.raises(FeatureValidationError, match="invalid_feature_vector"):
        replace(vector, values=values)


def test_numerical_vector_rejects_wrong_shape_and_nonintegral_counts():
    vector = build([])
    for values in (vector.values[:-1], list(vector.values)):
        with pytest.raises(FeatureValidationError, match="invalid_feature_vector"):
            replace(vector, values=values)
    values = list(vector.values)
    values[FEATURE_NAMES.index("recent_feed_count")] = 0.5
    with pytest.raises(FeatureValidationError, match="invalid_feature_vector"):
        replace(vector, values=tuple(values))
    assert len({definition.name for definition in FEATURE_DEFINITIONS}) == len(FEATURE_NAMES)
