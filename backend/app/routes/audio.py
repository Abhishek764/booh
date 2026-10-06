"""Thin authenticated routes for owner-scoped speech audio."""

from __future__ import annotations

import asyncio
import re
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict

from backend.app.audio_contracts import AudioAPIError, AudioRecord
from backend.app.dependencies import (
    get_audio_service,
    get_csrf_protected_principal,
    get_current_principal,
)
from backend.app.services.audio import AudioService
from backend.app.services.auth import Principal

router = APIRouter(tags=["audio"])


class AudioResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    baby_id: UUID
    prediction_id: UUID
    provider: str
    provider_version: str
    content_type: str
    byte_size: int
    duration_ms: int | None
    expires_at: datetime | None
    content_url: str


def _private(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"


def _response(record: AudioRecord, *, baby_id: UUID, prediction_id: UUID) -> AudioResponse:
    return AudioResponse(
        id=record.id,
        baby_id=baby_id,
        prediction_id=prediction_id,
        provider=record.provider,
        provider_version=record.provider_version,
        content_type=record.content_type,
        byte_size=record.byte_size,
        duration_ms=record.duration_ms,
        expires_at=record.expires_at,
        content_url=f"/api/v1/babies/{baby_id}/predictions/{prediction_id}/audio/content",
    )


async def _empty_body(request: Request) -> None:
    if request.query_params or any(
        len(request.headers.getlist(name)) > 1
        for name in ("content-length", "content-type", "origin", "x-csrf-token")
    ):
        raise AudioAPIError("invalid_request", 400)
    length = request.headers.get("content-length")
    if length is not None:
        if not re.fullmatch(r"\d{1,10}", length):
            raise AudioAPIError("invalid_request", 400)
        if int(length) != 0:
            raise AudioAPIError("invalid_request", 413)
    try:
        async with asyncio.timeout(5):
            async for chunk in request.stream():
                if chunk:
                    raise AudioAPIError("invalid_request", 413)
    except TimeoutError:
        raise AudioAPIError("invalid_request", 408) from None


@router.post(
    "/babies/{baby_id}/predictions/{prediction_id}/audio",
    response_model=AudioResponse,
    status_code=201,
)
async def create_audio(
    baby_id: UUID,
    prediction_id: UUID,
    request: Request,
    response: Response,
    principal: Annotated[Principal, Depends(get_csrf_protected_principal)],
    service: Annotated[AudioService, Depends(get_audio_service)],
) -> AudioResponse:
    await service.authorize(principal, baby_id=baby_id, prediction_id=prediction_id)
    await _empty_body(request)
    record = await service.synthesize(
        principal, baby_id=baby_id, prediction_id=prediction_id
    )
    _private(response)
    return _response(record, baby_id=baby_id, prediction_id=prediction_id)


@router.get(
    "/babies/{baby_id}/predictions/{prediction_id}/audio",
    response_model=AudioResponse,
)
async def get_audio(
    baby_id: UUID,
    prediction_id: UUID,
    response: Response,
    principal: Annotated[Principal, Depends(get_current_principal)],
    service: Annotated[AudioService, Depends(get_audio_service)],
) -> AudioResponse:
    record = await service.latest(
        principal, baby_id=baby_id, prediction_id=prediction_id
    )
    _private(response)
    return _response(record, baby_id=baby_id, prediction_id=prediction_id)


@router.get("/babies/{baby_id}/predictions/{prediction_id}/audio/content")
async def get_audio_content(
    baby_id: UUID,
    prediction_id: UUID,
    response: Response,
    principal: Annotated[Principal, Depends(get_current_principal)],
    service: Annotated[AudioService, Depends(get_audio_service)],
) -> Response:
    record, content = await service.content(
        principal, baby_id=baby_id, prediction_id=prediction_id
    )
    _private(response)
    return Response(
        content=content,
        media_type=record.content_type,
        headers={
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": "inline",
        },
    )


@router.delete(
    "/babies/{baby_id}/predictions/{prediction_id}/audio", status_code=204
)
async def delete_audio(
    baby_id: UUID,
    prediction_id: UUID,
    response: Response,
    principal: Annotated[Principal, Depends(get_csrf_protected_principal)],
    service: Annotated[AudioService, Depends(get_audio_service)],
) -> Response:
    await service.delete(principal, baby_id=baby_id, prediction_id=prediction_id)
    _private(response)
    return Response(status_code=204)


__all__ = ["AudioResponse", "router"]
