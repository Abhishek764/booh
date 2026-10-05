"""Thin authenticated prediction boundary with bounded streamed JSON input."""

import asyncio
import re
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response

from backend.app.dependencies import (
    get_csrf_protected_principal,
    get_current_principal,
    get_prediction_service,
)
from backend.app.prediction_contracts import (
    PredictionAPIError,
    PredictionListQuery,
    PredictionRecord,
    PredictionResponse,
    PredictRequest,
)
from backend.app.services.auth import Principal
from backend.app.services.predictions import PredictionPipelineService
from backend.app.summary_contracts import strict_json_object
from ml.prediction.contracts import BASELINE_VERSION

router = APIRouter(tags=["predictions"])
MAX_PREDICT_BODY_BYTES = 1024
BODY_TIMEOUT_SECONDS = 5.0


def _private(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"


def _response(record: PredictionRecord) -> PredictionResponse:
    numerical = record.numerical
    return PredictionResponse(
        id=record.id, baby_id=record.baby_id, prediction_timestamp=numerical.metadata.as_of_utc,
        expected_sleep_minutes=numerical.expected_sleep_minutes,
        wake_probability_60m=numerical.wake_probability_60m, baseline_minutes=numerical.baseline_minutes,
        model_version=numerical.model_version, feature_version="sleep-remaining-v1",
        baseline_version="baseline-7d-v1", used_baseline=numerical.model_version == BASELINE_VERSION,
        summary=record.summary, summary_used_fallback=record.summary_used_fallback,
    )


async def _input(request: Request) -> PredictRequest:
    if request.query_params or any(len(request.headers.getlist(name)) > 1 for name in (
        "content-type", "content-length", "origin", "x-csrf-token",
    )):
        raise PredictionAPIError("invalid_request", 400)
    length = request.headers.get("content-length")
    if length is not None:
        if not re.fullmatch(r"\d{1,10}", length):
            raise PredictionAPIError("invalid_request", 400)
        if int(length) > MAX_PREDICT_BODY_BYTES:
            raise PredictionAPIError("invalid_request", 413)
    payload = bytearray()
    try:
        async with asyncio.timeout(BODY_TIMEOUT_SECONDS):
            async for chunk in request.stream():
                if len(chunk) > MAX_PREDICT_BODY_BYTES - len(payload):
                    raise PredictionAPIError("invalid_request", 413)
                payload.extend(chunk)
    except TimeoutError:
        raise PredictionAPIError("invalid_request", 408) from None
    if not payload:
        return PredictRequest()
    if not re.fullmatch(r'application/json(?:;\s*charset=(?:utf-8|"utf-8"))?', request.headers.get("content-type", ""), re.IGNORECASE):
        raise PredictionAPIError("unsupported_media_type", 415)
    try:
        return PredictRequest.model_validate(strict_json_object(payload.decode("utf-8", errors="strict")))
    except (ValueError, RecursionError):
        raise PredictionAPIError("invalid_request", 422) from None


@router.post("/babies/{baby_id}/predict", response_model=PredictionResponse, status_code=201)
async def predict(
    baby_id: UUID, request: Request, response: Response,
    principal: Annotated[Principal, Depends(get_csrf_protected_principal)],
    service: Annotated[PredictionPipelineService, Depends(get_prediction_service)],
) -> PredictionResponse:
    await service.authorize_baby(principal, baby_id=baby_id)
    await _input(request)
    record = await service.predict(principal, baby_id=baby_id)
    _private(response)
    return _response(record)


@router.get("/babies/{baby_id}/predictions", response_model=list[PredictionResponse])
async def list_predictions(
    baby_id: UUID, response: Response,
    principal: Annotated[Principal, Depends(get_current_principal)],
    service: Annotated[PredictionPipelineService, Depends(get_prediction_service)],
    query: Annotated[PredictionListQuery, Query()],
) -> list[PredictionResponse]:
    records = await service.list_predictions(principal, baby_id=baby_id, limit=query.limit, offset=query.offset)
    _private(response)
    return [_response(record) for record in records]
