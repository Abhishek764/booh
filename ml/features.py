"""Versioned, deterministic features from one baby's normalized event history.

This module uses only the standard library. Authorization and history retrieval
belong to the calling service; this layer validates scope and computes features.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Protocol
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

FEATURE_VERSION = "sleep-history-v1"
LOOKBACK = timedelta(days=7)
MAX_HISTORY_EVENTS = 10000
MAX_EVENT_DURATION_SECONDS = 7 * 24 * 60 * 60
MISSING_VALUE = -1.0


class FeatureValidationError(ValueError):
    """Fixed error codes only; never include records or input values."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class NormalizedEventLike(Protocol):
    """Read-only projection satisfied by repository event records and HistoryEvent."""

    @property
    def baby_id(self) -> UUID: ...

    @property
    def event_type(self) -> str: ...

    @property
    def start_time(self) -> datetime: ...

    @property
    def end_time(self) -> datetime | None: ...

    @property
    def duration_seconds(self) -> int | None: ...


@dataclass(frozen=True, slots=True, repr=False)
class HistoryEvent:
    """Minimal offline input; no notes, account identity, or provider payloads."""

    baby_id: UUID
    event_type: str
    start_time: datetime
    end_time: datetime | None = None
    duration_seconds: int | None = None


@dataclass(frozen=True, slots=True)
class FeatureDefinition:
    name: str
    minimum: float
    maximum: float
    missing_allowed: bool = False
    integer: bool = False


# Order is part of the versioned model-input contract. Bounds include observations
# spanning the lookback; rolling totals are bounded by elapsed time, not bout sums.
FEATURE_DEFINITIONS = (
    FeatureDefinition("hour_of_day", 0.0, math.nextafter(24.0, 0.0)),
    FeatureDefinition("minutes_since_last_feed", 0.0, 10080.0, missing_allowed=True),
    FeatureDefinition("last_sleep_duration_minutes", 0.0, 10080.0, missing_allowed=True),
    FeatureDefinition("recent_sleep_duration_minutes", 0.0, 10080.0, missing_allowed=True),
    FeatureDefinition("rolling_12h_sleep_minutes", 0.0, 720.0),
    FeatureDefinition("rolling_24h_sleep_minutes", 0.0, 1440.0),
    FeatureDefinition("recent_wake_interval_minutes", 0.0, 10080.0, missing_allowed=True),
    FeatureDefinition("recent_feed_count", 0.0, 10000.0, integer=True),
    FeatureDefinition("recent_sleep_count", 0.0, 10000.0, integer=True),
    FeatureDefinition("day_of_life", 0.0, 3652058.0, missing_allowed=True, integer=True),
    FeatureDefinition("is_night", 0.0, 1.0, integer=True),
    FeatureDefinition("incomplete_sleep_count", 0.0, 10000.0, integer=True),
    FeatureDefinition("history_span_minutes", 0.0, 10080.0),
)
FEATURE_NAMES = tuple(definition.name for definition in FEATURE_DEFINITIONS)


@dataclass(frozen=True, slots=True, repr=False)
class FeatureMetadata:
    """Internal provenance and observation quality; not a confidence estimate."""

    as_of_utc: datetime
    window_start_utc: datetime
    timezone_name: str
    input_event_count: int
    used_event_count: int
    duplicate_event_count: int
    excluded_future_event_count: int
    excluded_old_event_count: int
    insufficient_history: bool
    missing_features: tuple[str, ...]


@dataclass(frozen=True, slots=True, repr=False)
class FeatureVector:
    """Immutable numerical values in FEATURE_NAMES order, validated at creation."""

    values: tuple[float, ...]
    metadata: FeatureMetadata
    feature_version: str = FEATURE_VERSION

    def __post_init__(self) -> None:
        if self.feature_version != FEATURE_VERSION:
            raise FeatureValidationError("invalid_feature_version")
        if not isinstance(self.values, tuple) or len(self.values) != len(FEATURE_NAMES):
            raise FeatureValidationError("invalid_feature_vector")
        missing: list[str] = []
        for definition, value in zip(FEATURE_DEFINITIONS, self.values, strict=True):
            if type(value) not in {float, int}:
                raise FeatureValidationError("invalid_feature_vector")
            if value == MISSING_VALUE and definition.missing_allowed:
                missing.append(definition.name)
                continue
            if not definition.minimum <= value <= definition.maximum or not math.isfinite(value):
                raise FeatureValidationError("invalid_feature_vector")
            if definition.integer and value != int(value):
                raise FeatureValidationError("invalid_feature_vector")
        if (
            not isinstance(self.metadata, FeatureMetadata)
            or self.metadata.missing_features != tuple(missing)
        ):
            raise FeatureValidationError("invalid_feature_metadata")

    def as_dict(self) -> dict[str, float]:
        """Return a detached mapping; feature values remain sensitive user data."""

        return dict(zip(FEATURE_NAMES, self.values, strict=True))


def _utc(value: datetime, *, code: str) -> datetime:
    try:
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise FeatureValidationError(code)
        return value.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        raise FeatureValidationError(code) from None


def _zone(name: str) -> ZoneInfo:
    if (
        not isinstance(name, str) or not name or len(name) > 64
        or name != name.strip()
        or any(ord(char) < 32 or ord(char) == 127 for char in name)
    ):
        raise FeatureValidationError("invalid_timezone")
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise FeatureValidationError("invalid_timezone") from None


def _validated_event(record: NormalizedEventLike, baby_id: UUID) -> HistoryEvent:
    try:
        record_baby = record.baby_id
        kind = record.event_type
        start_value = record.start_time
        end_value = record.end_time
        duration = record.duration_seconds
    except (AttributeError, TypeError):
        raise FeatureValidationError("invalid_event") from None
    if not isinstance(record_baby, UUID) or record_baby != baby_id:
        raise FeatureValidationError("invalid_history_scope")
    if not isinstance(kind, str) or kind not in {"sleep", "feed", "wake"}:
        raise FeatureValidationError("invalid_event")
    # String-valued enums (including backend EventType) work without importing
    # an ORM/backend module. Canonical keys always use plain, allowlisted strings.
    kind = {"sleep": "sleep", "feed": "feed", "wake": "wake"}[kind]
    start = _utc(start_value, code="invalid_event")
    end = None if end_value is None else _utc(end_value, code="invalid_event")
    if duration is not None and (
        type(duration) is not int or not 0 <= duration <= MAX_EVENT_DURATION_SECONDS
    ):
        raise FeatureValidationError("invalid_event")
    if kind == "wake" and (end is not None or duration is not None):
        raise FeatureValidationError("invalid_event")
    if end is not None:
        seconds = (end - start).total_seconds()
        if not 0 <= seconds <= MAX_EVENT_DURATION_SECONDS:
            raise FeatureValidationError("invalid_event")
        if duration is not None and duration != seconds:
            raise FeatureValidationError("invalid_event")
    elif duration is not None:
        try:
            end = start + timedelta(seconds=duration)
        except OverflowError:
            raise FeatureValidationError("invalid_event") from None
    return HistoryEvent(baby_id, kind, start, end)


def normalize_history(
    history: Iterable[NormalizedEventLike], *, baby_id: UUID
) -> tuple[HistoryEvent, ...]:
    """Bounded, scope-checked UTC projection shared by features and numeric models."""

    if not isinstance(baby_id, UUID):
        raise FeatureValidationError("invalid_history_scope")
    try:
        records = iter(history)
    except TypeError:
        raise FeatureValidationError("invalid_history") from None
    result: list[HistoryEvent] = []
    for record in records:
        if len(result) >= MAX_HISTORY_EVENTS:
            raise FeatureValidationError("history_too_large")
        result.append(_validated_event(record, baby_id))
    return tuple(result)


def _rolling_sleep_minutes(
    sleeps: list[HistoryEvent], start: datetime, end: datetime
) -> float:
    """Clip completed intervals and measure their union to avoid double counting."""

    intervals = sorted(
        (max(event.start_time, start), min(event.end_time, end))
        for event in sleeps
        if event.end_time is not None and event.end_time > start and event.start_time < end
    )
    seconds = 0.0
    merged_start: datetime | None = None
    merged_end: datetime | None = None
    for lower, upper in intervals:
        if merged_start is None or merged_end is None:
            merged_start, merged_end = lower, upper
        elif lower <= merged_end:
            merged_end = max(merged_end, upper)
        else:
            seconds += (merged_end - merged_start).total_seconds()
            merged_start, merged_end = lower, upper
    if merged_start is not None and merged_end is not None:
        seconds += (merged_end - merged_start).total_seconds()
    return seconds / 60.0


class FeatureService:
    """Pure computations: explicit as-of time, no HTTP, DB, providers, or logging."""

    def build(
        self,
        history: Iterable[NormalizedEventLike],
        *,
        baby_id: UUID,
        as_of: datetime,
        timezone_name: str,
        date_of_birth: date | None = None,
    ) -> FeatureVector:
        if not isinstance(baby_id, UUID):
            raise FeatureValidationError("invalid_history_scope")
        current = _utc(as_of, code="invalid_context")
        zone = _zone(timezone_name)
        try:
            local = current.astimezone(zone)
            window_start = current - LOOKBACK
            recent_start = current - timedelta(hours=12)
            daily_start = current - timedelta(hours=24)
        except (OverflowError, ValueError):
            raise FeatureValidationError("invalid_context") from None
        if date_of_birth is not None and (
            type(date_of_birth) is not date or date_of_birth > local.date()
        ):
            raise FeatureValidationError("invalid_birth_date")
        events: list[HistoryEvent] = []
        keys: set[tuple[object, ...]] = set()
        input_count = duplicates = future = old = 0
        for event in normalize_history(history, baby_id=baby_id):
            input_count += 1
            if event.start_time > current:
                future += 1
                continue
            if event.end_time is not None and event.end_time > current:
                # Future completion labels must not change duplicate/start counts
                # either. Retain only the end visible at this historical instant.
                event = HistoryEvent(baby_id, event.event_type, event.start_time)
            if event.start_time <= window_start and not (
                event.event_type == "sleep"
                and event.end_time is not None and event.end_time > window_start
            ):
                old += 1
                continue
            key = (event.event_type, event.start_time, event.end_time)
            if key in keys:
                duplicates += 1
                continue
            keys.add(key)
            events.append(event)

        sleeps = [event for event in events if event.event_type == "sleep"]
        completed = sorted(
            (event for event in sleeps if event.end_time is not None and event.end_time <= current),
            key=lambda event: (event.end_time or event.start_time, event.start_time),
        )
        feeds = [event for event in events if event.event_type == "feed"]
        wakes = sorted(event.start_time for event in events if event.event_type == "wake")
        durations = [
            (event.end_time - event.start_time).total_seconds() / 60.0
            for event in completed if event.end_time is not None
        ]
        span = min(
            (current - min(event.start_time for event in events)).total_seconds() / 60.0,
            LOOKBACK.total_seconds() / 60.0,
        ) if events else 0.0
        values = (
            local.hour + local.minute / 60.0 + local.second / 3600.0 + local.microsecond / 3600000000.0,
            (current - max(event.start_time for event in feeds)).total_seconds() / 60.0 if feeds else MISSING_VALUE,
            durations[-1] if durations else MISSING_VALUE,
            math.fsum(durations[-3:]) / len(durations[-3:]) if durations else MISSING_VALUE,
            _rolling_sleep_minutes(completed, recent_start, current),
            _rolling_sleep_minutes(completed, daily_start, current),
            (wakes[-1] - wakes[-2]).total_seconds() / 60.0 if len(wakes) >= 2 else MISSING_VALUE,
            float(sum(event.start_time > recent_start for event in feeds)),
            float(sum(event.start_time > recent_start for event in sleeps)),
            float((local.date() - date_of_birth).days) if date_of_birth is not None else MISSING_VALUE,
            float(local.hour >= 19 or local.hour < 7),
            float(len(sleeps) - len(completed)),
            span,
        )
        missing = tuple(
            name for name, value in zip(FEATURE_NAMES, values, strict=True)
            if value == MISSING_VALUE
        )
        metadata = FeatureMetadata(
            as_of_utc=current, window_start_utc=window_start, timezone_name=timezone_name,
            input_event_count=input_count, used_event_count=len(events),
            duplicate_event_count=duplicates, excluded_future_event_count=future,
            excluded_old_event_count=old,
            insufficient_history=(
                span < 1440.0 or len(completed) < 2 or not feeds or len(wakes) < 2
            ),
            missing_features=missing,
        )
        return FeatureVector(values=values, metadata=metadata)


__all__ = [
    "FEATURE_DEFINITIONS", "FEATURE_NAMES", "FEATURE_VERSION", "LOOKBACK",
    "MAX_HISTORY_EVENTS", "MISSING_VALUE", "FeatureDefinition", "FeatureMetadata",
    "FeatureService", "FeatureValidationError", "FeatureVector", "HistoryEvent",
    "NormalizedEventLike",
    "normalize_history",
]
