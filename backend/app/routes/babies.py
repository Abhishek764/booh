"""Thin authenticated routes for baby profile management."""

from __future__ import annotations

import unicodedata
from datetime import date, datetime, timezone
from typing import Annotated
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator, model_validator

from backend.app.dependencies import get_baby_service, get_current_principal
from backend.app.repositories.babies import BabyRecord
from backend.app.services.auth import Principal
from backend.app.services.babies import BabyError, BabyService


router = APIRouter(prefix="/babies", tags=["babies"])
MAX_BABY_BODY_BYTES = 4096
MAX_DISPLAY_NAME_LENGTH = 120
MAX_TIMEZONE_LENGTH = 64


def _validate_display_name(value: StrictStr | None) -> StrictStr | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized or len(normalized) > MAX_DISPLAY_NAME_LENGTH:
        raise ValueError("display_name must contain 1 to 120 characters")
    if any(unicodedata.category(character).startswith("C") for character in normalized):
        raise ValueError("display_name contains unsupported control characters")
    return normalized


def _validate_timezone(value: StrictStr | None) -> StrictStr | None:
    if value is None:
        return None
    if (
        not value
        or len(value) > MAX_TIMEZONE_LENGTH
        or value != value.strip()
        or any(unicodedata.category(character).startswith("C") for character in value)
    ):
        raise ValueError("timezone must be a valid IANA timezone")
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("timezone must be a valid IANA timezone") from exc
    return value


def _validate_date_of_birth(value: date | None) -> date | None:
    if value is not None and value > datetime.now(timezone.utc).date():
        raise ValueError("date_of_birth cannot be in the future")
    return value


class BabyCreateRequest(BaseModel):
    """Strict create contract; the authenticated user is never request data."""

    model_config = ConfigDict(extra="forbid")

    display_name: StrictStr | None = Field(default=None)
    date_of_birth: date | None = None
    timezone: StrictStr = "UTC"

    _display_name = field_validator("display_name")(_validate_display_name)
    _date_of_birth = field_validator("date_of_birth")(_validate_date_of_birth)
    _timezone = field_validator("timezone")(_validate_timezone)


class BabyPatchRequest(BaseModel):
    """Strict partial update contract with no empty patches."""

    model_config = ConfigDict(extra="forbid")

    display_name: StrictStr | None = None
    date_of_birth: date | None = None
    timezone: StrictStr | None = None

    _display_name = field_validator("display_name")(_validate_display_name)
    _date_of_birth = field_validator("date_of_birth")(_validate_date_of_birth)
    _timezone = field_validator("timezone")(_validate_timezone)

    @model_validator(mode="after")
    def require_change(self) -> "BabyPatchRequest":
        if not self.model_fields_set:
            raise ValueError("at least one baby field is required")
        if "timezone" in self.model_fields_set and self.timezone is None:
            raise ValueError("timezone cannot be null")
        return self


class BabyResponse(BaseModel):
    """Public baby representation; ownership identifiers are not exposed."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    display_name: str | None
    date_of_birth: date | None
    timezone: str
    created_at: datetime
    updated_at: datetime


def _response(baby: BabyRecord) -> BabyResponse:
    return BabyResponse(
        id=baby.id,
        display_name=baby.display_name,
        date_of_birth=baby.date_of_birth,
        timezone=baby.timezone,
        created_at=baby.created_at,
        updated_at=baby.updated_at,
    )


async def _check_body_size(request: Request) -> None:
    content_length = request.headers.get("content-length")
    if content_length is None:
        return
    try:
        length = int(content_length)
    except ValueError:
        raise BabyError("invalid_request", 400) from None
    if length < 0 or length > MAX_BABY_BODY_BYTES:
        raise BabyError("invalid_request", 413)


@router.get("", response_model=list[BabyResponse], status_code=200)
def list_babies(
    principal: Annotated[Principal, Depends(get_current_principal)],
    service: Annotated[BabyService, Depends(get_baby_service)],
) -> list[BabyResponse]:
    return [_response(baby) for baby in service.list_babies(principal)]


@router.post(
    "",
    response_model=BabyResponse,
    status_code=201,
    dependencies=[Depends(_check_body_size)],
)
def create_baby(
    payload: BabyCreateRequest,
    principal: Annotated[Principal, Depends(get_current_principal)],
    service: Annotated[BabyService, Depends(get_baby_service)],
) -> BabyResponse:
    return _response(
        service.create_baby(
            principal,
            display_name=payload.display_name,
            date_of_birth=payload.date_of_birth,
            timezone=payload.timezone,
        )
    )


@router.get("/{baby_id}", response_model=BabyResponse, status_code=200)
def get_baby(
    baby_id: UUID,
    principal: Annotated[Principal, Depends(get_current_principal)],
    service: Annotated[BabyService, Depends(get_baby_service)],
) -> BabyResponse:
    return _response(service.get_baby(principal, baby_id=baby_id))


@router.patch(
    "/{baby_id}",
    response_model=BabyResponse,
    status_code=200,
    dependencies=[Depends(_check_body_size)],
)
def patch_baby(
    baby_id: UUID,
    payload: BabyPatchRequest,
    principal: Annotated[Principal, Depends(get_current_principal)],
    service: Annotated[BabyService, Depends(get_baby_service)],
) -> BabyResponse:
    return _response(
        service.update_baby(
            principal,
            baby_id=baby_id,
            changes=payload.model_dump(exclude_unset=True),
        )
    )


@router.delete("/{baby_id}", status_code=204)
def delete_baby(
    baby_id: UUID,
    principal: Annotated[Principal, Depends(get_current_principal)],
    service: Annotated[BabyService, Depends(get_baby_service)],
) -> Response:
    service.delete_baby(principal, baby_id=baby_id)
    return Response(status_code=204)


__all__ = ["router"]
