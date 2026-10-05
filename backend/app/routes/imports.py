"""Thin raw-CSV upload endpoint; auth executes before consuming the body."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from backend.app.dependencies import get_csrf_protected_principal, get_import_service
from backend.app.importers import (
    MAX_REPORTED_ERRORS,
    CsvImportError,
    DateOrder,
    ImporterKind,
)
from backend.app.services.auth import Principal
from backend.app.services.imports import ImportService

router = APIRouter(tags=["imports"])


class ImportOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: ImporterKind = "auto"
    timezone: str | None = Field(default=None, max_length=64)
    date_order: DateOrder = "ymd"


class ImportRowErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    row: int = Field(ge=2)
    code: str = Field(max_length=40)


class ImportSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    rows_processed: int = Field(ge=0)
    rows_imported: int = Field(ge=0)
    rows_skipped: int = Field(ge=0)
    rows_failed: int = Field(ge=0)
    duplicates: int = Field(ge=0)
    errors: list[ImportRowErrorResponse] = Field(max_length=MAX_REPORTED_ERRORS)
    errors_truncated: bool


@router.post("/babies/{baby_id}/imports", response_model=ImportSummaryResponse)
async def import_events(
    baby_id: UUID, request: Request, response: Response,
    principal: Annotated[Principal, Depends(get_csrf_protected_principal)],
    service: Annotated[ImportService, Depends(get_import_service)],
    options: Annotated[ImportOptions, Query()],
) -> ImportSummaryResponse:
    if any(len(request.headers.getlist(name)) > 1 for name in (
        "content-type", "content-disposition", "content-length",
    )):
        raise CsvImportError("invalid_request", 400)
    summary = await service.import_csv(
        principal, baby_id=baby_id, chunks=request.stream(),
        content_type=request.headers.get("content-type"),
        content_disposition=request.headers.get("content-disposition"),
        content_length=request.headers.get("content-length"),
        kind=options.format, timezone_name=options.timezone, date_order=options.date_order,
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return ImportSummaryResponse.model_validate(summary)
