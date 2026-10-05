"""Persistence-independent normalized event values and duplicate identity."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from backend.app.models import EventType


@dataclass(frozen=True, slots=True)
class NormalizedEvent:
    """Validated event values ready for persistence in UTC."""

    event_type: EventType
    start_time: datetime
    end_time: datetime | None
    duration_seconds: int | None
    feed_amount_ml: Decimal | None


def event_identity(event: NormalizedEvent) -> tuple[object, ...]:
    """Compare semantic values, independent of source and duration representation."""

    start = event.start_time.replace(tzinfo=timezone.utc) if event.start_time.tzinfo is None else event.start_time.astimezone(timezone.utc)
    end = event.end_time
    if end is not None:
        end = end.replace(tzinfo=timezone.utc) if end.tzinfo is None else end.astimezone(timezone.utc)
    elif event.duration_seconds is not None:
        end = start + timedelta(seconds=event.duration_seconds)
    return (EventType(event.event_type), start, end, event.feed_amount_ml)
