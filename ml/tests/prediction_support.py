"""Synthetic history only; never provider exports or family records."""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from ml.features import HistoryEvent

BABY = UUID(int=1)
AS_OF = datetime(2026, 1, 8, tzinfo=timezone.utc)


def synthetic_history(bouts: int = 42) -> tuple[HistoryEvent, ...]:
    records: list[HistoryEvent] = []
    durations = (45, 75, 90, 110, 50, 80)
    for index in range(bouts):
        start = AS_OF - timedelta(hours=4 * (bouts - index))
        end = start + timedelta(minutes=durations[index % len(durations)])
        records.extend((
            HistoryEvent(BABY, "feed", start - timedelta(minutes=10)),
            HistoryEvent(BABY, "sleep", start, end),
            HistoryEvent(BABY, "wake", end),
        ))
    return tuple(records)
