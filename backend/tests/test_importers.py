from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from backend.app.config import ImportLimits
from backend.app.importers import (
    CsvImportError,
    GenericEventImporter,
    HuckleberryImporter,
    select_importer,
)
from backend.app.models import EventType

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
FIXTURES = Path(__file__).parent / "fixtures" / "imports"


def parse(payload, *, importer=None, zone="UTC", date_order="ymd", limits=None):
    if isinstance(payload, str):
        payload = payload.encode()
    return (importer or select_importer("auto", payload)).parse(
        payload, limits=limits or ImportLimits(), timezone_name=zone,
        date_order=date_order, now=NOW,
    )


def test_supported_synthetic_fixtures_normalize_to_the_same_events():
    huckleberry = parse((FIXTURES / "huckleberry.csv").read_bytes())
    generic = parse((FIXTURES / "generic.csv").read_bytes())
    assert huckleberry.events == generic.events
    assert huckleberry.summary.rows_processed == 6
    assert huckleberry.summary.rows_skipped == 2
    assert huckleberry.summary.duplicates == 1
    assert huckleberry.summary.rows_failed == 1
    assert huckleberry.summary.errors[0].row == 7
    assert huckleberry.summary.errors[0].code == "invalid_date"
    assert huckleberry.events[0].duration_seconds == 5400
    assert huckleberry.events[1].feed_amount_ml == Decimal("118.29")
    assert huckleberry.events[2].event_type is EventType.WAKE


def test_column_alias_detection_reordering_bom_crlf_and_quoted_multiline_notes():
    payload = '\ufeffNotes, START , ACTIVITY ,End\r\n"synthetic, note\r\nsecond line",2025-12-30T18:00:00-05:00,Nap,2025-12-30T19:00:00-05:00\r\n'
    result = parse(payload)
    assert result.summary.rows_processed == 1
    assert result.summary.rows_failed == 0
    assert result.events[0].start_time == datetime(2025, 12, 30, 23, tzinfo=timezone.utc)
    assert result.events[0].duration_seconds == 3600


@pytest.mark.parametrize("order,date", [("mdy", "12/30/2025"), ("dmy", "30/12/2025"), ("ymd", "2025/12/30")])
def test_explicit_date_order_and_split_date_time(order, date):
    result = parse(
        f"Type,Date,Start Time,Duration\nSleep,{date},10:30 PM,1h 30m\n",
        zone="America/New_York", date_order=order,
    )
    assert result.events[0].start_time == datetime(2025, 12, 31, 3, 30, tzinfo=timezone.utc)
    assert result.events[0].end_time == datetime(2025, 12, 31, 5, tzinfo=timezone.utc)


def test_slash_dates_are_not_guessed_and_generic_requires_iso():
    assert parse("Type,Start\nWake,12/30/2025 10:00 PM\n").summary.rows_failed == 1
    assert parse(
        "event_type,start_time\nwake,12/30/2025 10:00 PM\n", date_order="mdy"
    ).summary.rows_failed == 1


@pytest.mark.parametrize("local", ["2025-11-02T01:30:00", "2025-03-09T02:30:00"])
def test_dst_ambiguity_and_nonexistent_times_fail_without_guessing(local):
    result = parse(f"event_type,start_time\nwake,{local}\n", zone="America/New_York")
    assert result.summary.rows_failed == 1
    assert result.events == []


def test_explicit_offset_resolves_dst_and_elapsed_duration_crosses_dst():
    result = parse(
        "event_type,start_time,duration_seconds,timezone\n"
        "sleep,2025-11-02T01:30:00-04:00,3600,America/New_York\n"
    )
    assert result.events[0].start_time.hour == 5
    assert result.events[0].end_time.hour == 6


@pytest.mark.parametrize("row", [
    "sleep,2025-12-30T22:00:00Z,2025-12-30T21:00:00Z,,",
    "sleep,2025-12-30T22:00:00Z,2025-12-30T23:00:00Z,30,",
    "sleep,2025-12-30T22:00:00Z,,,100",
    "wake,2025-12-30T22:00:00Z,2025-12-30T23:00:00Z,,",
    "feed,2025-12-30T22:00:00Z,,,10001",
    "feed,2025-12-30T22:00:00Z,,,NaN",
    "feed,2025-12-30T22:00:00Z,,,Infinity",
    "feed,2025-12-30T22:00:00Z,,,1e2",
    "feed,2025-12-30T22:00:00Z,,,1.234",
    "sleep,2025-12-30T22:00:00Z,,604801,",
    "sleep,2025-12-01T22:00:00Z,2025-12-30T23:00:00Z,,",
    "wake,2999-12-30T22:00:00Z,,,",
    "wake,2025-12-30T22:00:00Z,extra",
    "wake,2025-12-30T22:00:00Z,,,,unexpected",
])
def test_impossible_numbers_relationships_and_ragged_rows_are_reported(row):
    result = parse("event_type,start_time,end_time,duration_seconds,feed_amount_ml\n" + row + "\n")
    assert result.summary.rows_processed == result.summary.rows_failed == 1
    assert result.events == []
    assert result.summary.errors[0].row == 2


@pytest.mark.parametrize("header", [
    "", "Type", "Type,Start,Start", "Type,Activity,Start",
    "Type,Start,user_id", "Type,Start,baby_id", "Type,Start,source",
    "Type,Start,unknown", "=CMD(),Start", ",Start",
])
def test_invalid_and_ownership_columns_reject_the_file(header):
    with pytest.raises(CsvImportError):
        parse(header + "\n")


def test_blank_rows_and_allowlisted_non_domain_activities_are_skipped():
    result = parse("Type,Start\n\n,\nDiaper,2025-12-30T22:00:00Z\nUnexpected,2025-12-30T22:00:00Z\n")
    assert result.summary.rows_processed == 4
    assert result.summary.rows_skipped == 3
    assert result.summary.rows_failed == 1


def test_duplicate_detection_uses_normalized_timezone_and_elapsed_duration():
    result = parse(
        "event_type,start_time,end_time,duration_seconds\n"
        "sleep,2025-12-30T22:00:00Z,2025-12-30T23:00:00Z,\n"
        "sleep,2025-12-30T17:00:00-05:00,,3600\n"
    )
    assert len(result.events) == 1
    assert result.summary.duplicates == result.summary.rows_skipped == 1


def test_importer_abstraction_exposes_both_independent_adapters():
    assert isinstance(select_importer("generic", b""), GenericEventImporter)
    assert isinstance(select_importer("huckleberry", b""), HuckleberryImporter)
    assert isinstance(select_importer("auto", b"Event Type,Start Time,Duration\n"), HuckleberryImporter)


@pytest.mark.parametrize("value,expected", [("01:30", 5400), ("01:30:15", 5415), ("90", 5400), ("1h 30m", 5400)])
def test_huckleberry_duration_formats(value, expected):
    result = parse(f"Type,Start,Duration\nSleep,2025-12-30T00:00:00Z,{value}\n")
    assert result.events[0].duration_seconds == expected


def test_conflicting_or_unrecognized_feed_units_fail():
    result = parse("Type,Start,Amount,Units\nBottle,2025-12-30T00:00:00Z,4 oz,ml\nBottle,2025-12-30T00:00:00Z,4,litres\n")
    assert result.summary.rows_failed == 2
