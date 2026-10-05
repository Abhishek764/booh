"""Event tracking workflows, normalization, and ownership policy."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.exc import SQLAlchemyError

from backend.app.event_values import NormalizedEvent
from backend.app.models import EventType
from backend.app.repositories.events import EventRecord, OwnedEventRepository
from backend.app.security import utc_now
from backend.app.services.auth import Principal

MAX_EVENT_DURATION_SECONDS = 7 * 24 * 60 * 60
MAX_FEED_AMOUNT_ML = Decimal("10000.00")
MAX_FUTURE_SKEW_SECONDS = 300


class EventError(RuntimeError):
    """Safe, client-facing event resource failure."""

    def __init__(self, code: str, status_code: int = 404) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


def validate_timezone_name(value: str) -> str:
    """Validate an IANA timezone name without accepting filesystem-like input."""

    if (
        not value
        or len(value) > 64
        or value != value.strip()
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ValueError("timezone must be a valid IANA timezone")
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("timezone must be a valid IANA timezone") from exc
    return value


def _normalize_timestamp(value: datetime, zone: ZoneInfo) -> datetime:
    if value.tzinfo is not None and value.utcoffset() is not None:
        return value.astimezone(timezone.utc)

    candidates: list[datetime] = []
    for fold in (0, 1):
        candidate = value.replace(tzinfo=zone, fold=fold)
        round_trip = candidate.astimezone(timezone.utc).astimezone(zone)
        if round_trip.replace(tzinfo=None) == value:
            if not any(candidate.astimezone(timezone.utc) == existing for existing in candidates):
                candidates.append(candidate)
    if len(candidates) != 1:
        raise EventError("invalid_request", 422)
    return candidates[0].astimezone(timezone.utc)


def normalize_event(
    *,
    event_type: EventType,
    start_time: datetime,
    end_time: datetime | None,
    duration_seconds: int | None,
    feed_amount_ml: Decimal | None,
    timezone_name: str,
    now: datetime,
) -> NormalizedEvent:
    """Apply event policy and return UTC values suitable for the database."""

    try:
        zone = ZoneInfo(validate_timezone_name(timezone_name))
    except ValueError:
        raise EventError("invalid_request", 422) from None

    try:
        normalized_start = _normalize_timestamp(start_time, zone)
        normalized_end = (
            None if end_time is None else _normalize_timestamp(end_time, zone)
        )
    except EventError:
        raise
    except (TypeError, ValueError, OverflowError):
        raise EventError("invalid_request", 422) from None

    current = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    latest_allowed = current.timestamp() + MAX_FUTURE_SKEW_SECONDS
    if (
        normalized_start.timestamp() > latest_allowed
        or normalized_end is not None
        and normalized_end.timestamp() > latest_allowed
    ):
        raise EventError("invalid_request", 422)

    if normalized_end is not None and normalized_end < normalized_start:
        raise EventError("invalid_request", 422)
    if duration_seconds is not None and not 0 <= duration_seconds <= MAX_EVENT_DURATION_SECONDS:
        raise EventError("invalid_request", 422)
    if feed_amount_ml is not None and not 0 <= feed_amount_ml <= MAX_FEED_AMOUNT_ML:
        raise EventError("invalid_request", 422)
    if normalized_end is not None and duration_seconds is not None:
        elapsed = (normalized_end - normalized_start).total_seconds()
        if elapsed != duration_seconds:
            raise EventError("invalid_request", 422)
    if event_type is EventType.WAKE and (
        normalized_end is not None or duration_seconds is not None
    ):
        raise EventError("invalid_request", 422)
    if event_type is not EventType.FEED and feed_amount_ml is not None:
        raise EventError("invalid_request", 422)

    return NormalizedEvent(
        event_type=event_type,
        start_time=normalized_start,
        end_time=normalized_end,
        duration_seconds=duration_seconds,
        feed_amount_ml=feed_amount_ml,
    )


class EventService:
    """Apply authenticated baby ownership to every event operation."""

    def __init__(
        self,
        repository: OwnedEventRepository,
        *,
        clock: Callable[[], datetime] = utc_now,
        on_change: Callable[[uuid.UUID, uuid.UUID], None] | None = None,
    ) -> None:
        self._repository = repository
        self._clock = clock
        self._on_change = on_change

    def list_events(
        self,
        principal: Principal,
        *,
        baby_id: uuid.UUID,
        limit: int,
        offset: int,
    ) -> list[EventRecord]:
        try:
            events = self._repository.list_owned_for_baby(
                baby_id=baby_id,
                owner_id=principal.user_id,
                limit=limit,
                offset=offset,
            )
        except Exception as exc:
            raise self._service_error(exc) from None
        if events is None:
            raise EventError("resource_not_found", 404)
        return events

    def create_event(
        self,
        principal: Principal,
        *,
        baby_id: uuid.UUID,
        event_type: EventType,
        start_time: datetime,
        end_time: datetime | None,
        duration_seconds: int | None,
        feed_amount_ml: Decimal | None,
        timezone_name: str,
    ) -> EventRecord:
        normalized = normalize_event(
            event_type=event_type,
            start_time=start_time,
            end_time=end_time,
            duration_seconds=duration_seconds,
            feed_amount_ml=feed_amount_ml,
            timezone_name=timezone_name,
            now=self._clock(),
        )
        try:
            event = self._repository.create_owned_for_baby(
                baby_id=baby_id,
                owner_id=principal.user_id,
                event_type=normalized.event_type,
                start_time=normalized.start_time,
                end_time=normalized.end_time,
                duration_seconds=normalized.duration_seconds,
                feed_amount_ml=normalized.feed_amount_ml,
            )
        except Exception as exc:
            raise self._service_error(exc) from None
        if event is None:
            raise EventError("resource_not_found", 404)
        if self._on_change is not None:
            self._on_change(principal.user_id, baby_id)
        return event

    def get_event(self, principal: Principal, *, event_id: uuid.UUID) -> EventRecord:
        try:
            event = self._repository.get_owned_event(
                event_id=event_id, owner_id=principal.user_id
            )
        except Exception as exc:
            raise self._service_error(exc) from None
        if event is None:
            raise EventError("resource_not_found", 404)
        return event

    def update_event(
        self,
        principal: Principal,
        *,
        event_id: uuid.UUID,
        changes: dict[str, object],
    ) -> EventRecord:
        allowed = {
            "event_type",
            "start_time",
            "end_time",
            "duration_seconds",
            "feed_amount_ml",
            "timezone",
        }
        if not changes or not set(changes).issubset(allowed) or set(changes) == {"timezone"}:
            raise EventError("invalid_request", 422)
        try:
            existing = self._repository.get_owned_event(
                event_id=event_id, owner_id=principal.user_id
            )
        except Exception as exc:
            raise self._service_error(exc) from None
        if existing is None:
            raise EventError("resource_not_found", 404)

        timezone_name = str(changes.get("timezone", "UTC"))
        try:
            normalized = normalize_event(
                event_type=changes.get("event_type", existing.event_type),
                start_time=changes.get("start_time", existing.start_time),
                end_time=changes.get("end_time", existing.end_time),
                duration_seconds=changes.get(
                    "duration_seconds", existing.duration_seconds
                ),
                feed_amount_ml=changes.get(
                    "feed_amount_ml", existing.feed_amount_ml
                ),
                timezone_name=timezone_name,
                now=self._clock(),
            )
        except EventError:
            raise
        except (TypeError, ValueError):
            raise EventError("invalid_request", 422) from None

        try:
            updated = self._repository.update_owned_event(
                event_id=event_id,
                owner_id=principal.user_id,
                changes={
                    "event_type": normalized.event_type,
                    "start_time": normalized.start_time,
                    "end_time": normalized.end_time,
                    "duration_seconds": normalized.duration_seconds,
                    "feed_amount_ml": normalized.feed_amount_ml,
                },
            )
        except Exception as exc:
            raise self._service_error(exc) from None
        if updated is None:
            raise EventError("resource_not_found", 404)
        if self._on_change is not None:
            self._on_change(principal.user_id, updated.baby_id)
        return updated

    def delete_event(self, principal: Principal, *, event_id: uuid.UUID) -> None:
        existing = self.get_event(principal, event_id=event_id)
        try:
            deleted = self._repository.delete_owned_event(
                event_id=event_id, owner_id=principal.user_id
            )
        except Exception as exc:
            raise self._service_error(exc) from None
        if not deleted:
            raise EventError("resource_not_found", 404)
        if self._on_change is not None:
            self._on_change(principal.user_id, existing.baby_id)

    @staticmethod
    def _service_error(exc: Exception) -> EventError:
        if isinstance(exc, EventError):
            return exc
        if isinstance(exc, SQLAlchemyError):
            return EventError("service_unavailable", 503)
        return EventError("service_unavailable", 503)


__all__ = [
    "EventError",
    "EventService",
    "MAX_EVENT_DURATION_SECONDS",
    "MAX_FEED_AMOUNT_ML",
    "NormalizedEvent",
    "normalize_event",
    "validate_timezone_name",
]
