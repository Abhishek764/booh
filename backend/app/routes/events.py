"""Thin authenticated routes for sleep, feed, and wake event tracking."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator, model_validator

from backend.app.dependencies import (
    get_current_principal,
    get_event_service,
    get_csrf_protected_principal,
)
from backend.app.models import EventSource, EventType
from backend.app.repositories.events import EventRecord
from backend.app.services.auth import Principal
from backend.app.services.events import (
    EventError,
    EventService,
    MAX_EVENT_DURATION_SECONDS,
    MAX_FEED_AMOUNT_ML,
    validate_timezone_name,
)


router = APIRouter(tags=["events"])
MAX_EVENT_BODY_BYTES = 4096


class EventCreateRequest(BaseModel):
    """Strict event input; ownership and source are server-controlled."""

    model_config = ConfigDict(extra="forbid")

    event_type: EventType
    start_time: datetime
    end_time: datetime | None = None
    duration_seconds: StrictInt | None = Field(
        default=None, ge=0, le=MAX_EVENT_DURATION_SECONDS
    )
    feed_amount_ml: Decimal | None = Field(
        default=None, ge=0, le=MAX_FEED_AMOUNT_ML, max_digits=8, decimal_places=2
    )
    timezone: StrictStr = "UTC"

    _timezone = field_validator("timezone")(validate_timezone_name)


class EventPatchRequest(BaseModel):
    """Strict partial event input with no mass assignment fields."""

    model_config = ConfigDict(extra="forbid")

    event_type: EventType | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    duration_seconds: StrictInt | None = Field(
        default=None, ge=0, le=MAX_EVENT_DURATION_SECONDS
    )
    feed_amount_ml: Decimal | None = Field(
        default=None, ge=0, le=MAX_FEED_AMOUNT_ML, max_digits=8, decimal_places=2
    )
    timezone: StrictStr | None = None

    _timezone = field_validator("timezone")(validate_timezone_name)

    @model_validator(mode="after")
    def require_change(self) -> "EventPatchRequest":
        if not self.model_fields_set:
            raise ValueError("at least one event field is required")
        if any(
            field in self.model_fields_set and getattr(self, field) is None
            for field in ("event_type", "start_time", "timezone")
        ):
            raise ValueError("event field cannot be null")
        return self


class EventResponse(BaseModel):
    """Public event representation without user ownership internals."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    baby_id: UUID
    event_type: EventType
    source: EventSource
    start_time: datetime
    end_time: datetime | None
    duration_seconds: int | None
    feed_amount_ml: Decimal | None
    created_at: datetime
    updated_at: datetime


def _response(event: EventRecord) -> EventResponse:
    return EventResponse(
        id=event.id,
        baby_id=event.baby_id,
        event_type=event.event_type,
        source=event.source,
        start_time=event.start_time,
        end_time=event.end_time,
        duration_seconds=event.duration_seconds,
        feed_amount_ml=event.feed_amount_ml,
        created_at=event.created_at,
        updated_at=event.updated_at,
    )


async def _check_body_size(request: Request) -> None:
    content_length = request.headers.get("content-length")
    if content_length is None:
        return
    try:
        length = int(content_length)
    except ValueError:
        raise EventError("invalid_request", 400) from None
    if length < 0 or length > MAX_EVENT_BODY_BYTES:
        raise EventError("invalid_request", 413)


@router.get(
    "/babies/{baby_id}/events",
    response_model=list[EventResponse],
    status_code=200,
)
def list_events(
    baby_id: UUID,
    principal: Annotated[Principal, Depends(get_current_principal)],
    service: Annotated[EventService, Depends(get_event_service)],
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0, le=10000)] = 0,
) -> list[EventResponse]:
    return [
        _response(event)
        for event in service.list_events(
            principal, baby_id=baby_id, limit=limit, offset=offset
        )
    ]


@router.post(
    "/babies/{baby_id}/events",
    response_model=EventResponse,
    status_code=201,
    dependencies=[Depends(_check_body_size)],
)
def create_event(
    baby_id: UUID,
    payload: EventCreateRequest,
    principal: Annotated[Principal, Depends(get_csrf_protected_principal)],
    service: Annotated[EventService, Depends(get_event_service)],
) -> EventResponse:
    return _response(
        service.create_event(
            principal,
            baby_id=baby_id,
            event_type=payload.event_type,
            start_time=payload.start_time,
            end_time=payload.end_time,
            duration_seconds=payload.duration_seconds,
            feed_amount_ml=payload.feed_amount_ml,
            timezone_name=payload.timezone,
        )
    )


@router.patch(
    "/events/{event_id}",
    response_model=EventResponse,
    status_code=200,
    dependencies=[Depends(_check_body_size)],
)
def patch_event(
    event_id: UUID,
    payload: EventPatchRequest,
    principal: Annotated[Principal, Depends(get_csrf_protected_principal)],
    service: Annotated[EventService, Depends(get_event_service)],
) -> EventResponse:
    return _response(
        service.update_event(
            principal,
            event_id=event_id,
            changes=payload.model_dump(exclude_unset=True),
        )
    )


@router.delete("/events/{event_id}", status_code=204)
def delete_event(
    event_id: UUID,
    principal: Annotated[Principal, Depends(get_csrf_protected_principal)],
    service: Annotated[EventService, Depends(get_event_service)],
) -> Response:
    service.delete_event(principal, event_id=event_id)
    return Response(status_code=204)


__all__ = ["router"]
