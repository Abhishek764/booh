"""Minimal BOOH API application boundary.

Versioned routes belong in feature-specific modules and must call services
rather than implementing policy in the route layer.
"""

import asyncio
import os
from contextlib import asynccontextmanager
from threading import Lock
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from backend.app.audio_contracts import AudioAPIError
from backend.app.config import AuthSettings, ConfigurationError, ImportLimits
from backend.app.importers import CsvImportError
from backend.app.middleware import AuthPrivacyMiddleware
from backend.app.prediction_contracts import PredictionAPIError
from backend.app.routes.audio import router as audio_router
from backend.app.routes.auth import router as auth_router
from backend.app.routes.babies import router as babies_router
from backend.app.routes.events import router as events_router
from backend.app.routes.imports import router as imports_router
from backend.app.routes.predictions import router as predictions_router
from backend.app.services.auth import AuthError
from backend.app.services.babies import BabyError
from backend.app.services.events import EventError
from backend.app.services.prediction_models import PredictionModelRegistry
from backend.app.services.summaries import build_summary_service

API_V1_PREFIX = "/api/v1"
APPLICATION_VERSION = "0.1.0"


class HealthResponse(BaseModel):
    """Stable response contract for process and routing health checks."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"] = "ok"
    service: Literal["booh-api"] = "booh-api"
    version: str = APPLICATION_VERSION


async def request_validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Return a bounded error without echoing request data or internals."""

    del request, exc
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "invalid_request",
                "message": "The request could not be processed.",
            }
        },
        headers={"Cache-Control": "no-store"},
    )


async def auth_error_handler(request: Request, exc: AuthError) -> JSONResponse:
    """Return one bounded auth error shape without exposing provider details."""

    del request
    message = {
        "authentication_required": "Authentication is required.",
        "authentication_unavailable": "Authentication is temporarily unavailable.",
        "invalid_callback": "The authentication response could not be verified.",
        "csrf_failed": "The request could not be verified.",
        "origin_failed": "The request could not be verified.",
        "resource_not_found": "The requested resource was not found.",
    }.get(exc.code, "The request could not be authenticated.")
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": message}},
        headers={"Cache-Control": "no-store"},
    )


async def baby_error_handler(request: Request, exc: BabyError) -> JSONResponse:
    """Return a bounded baby-resource error without ownership details."""

    del request
    message = {
        "resource_not_found": "The requested resource was not found.",
        "invalid_request": "The request could not be processed.",
        "service_unavailable": "The service is temporarily unavailable.",
    }.get(exc.code, "The request could not be processed.")
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": message}},
        headers={"Cache-Control": "no-store"},
    )


async def event_error_handler(request: Request, exc: EventError) -> JSONResponse:
    """Return a bounded event-resource error without private event details."""

    del request
    message = {
        "resource_not_found": "The requested resource was not found.",
        "invalid_request": "The request could not be processed.",
        "service_unavailable": "The service is temporarily unavailable.",
    }.get(exc.code, "The request could not be processed.")
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": message}},
        headers={"Cache-Control": "no-store"},
    )


async def health() -> HealthResponse:
    """Report that the API process is running.

    Dependency health checks will be added with the database layer. This
    endpoint intentionally does not expose credentials, user data, or runtime
    internals.
    """

    return HealthResponse()


async def import_error_handler(request: Request, exc: CsvImportError) -> JSONResponse:
    del request
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": "The CSV import could not be processed."}},
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


async def prediction_error_handler(request: Request, exc: PredictionAPIError) -> JSONResponse:
    del request
    message = {
        "resource_not_found": "The requested resource was not found.",
        "insufficient_history": "More completed sleep history is needed for an estimate.",
        "invalid_history": "The sleep history could not be used for an estimate.",
        "history_changed": "The history changed. Please try again.",
        "history_too_large": "The prediction history limit was exceeded.",
        "invalid_request": "The request could not be processed.",
        "unsupported_media_type": "A JSON request is required.",
        "prediction_busy": "Predictions are temporarily busy.",
        "prediction_rate_limited": "Please wait before requesting another prediction.",
    }.get(exc.code, "The prediction service is temporarily unavailable.")
    return JSONResponse(status_code=exc.status_code, content={"error": {"code": exc.code, "message": message}},
                         headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff"})


async def audio_error_handler(request: Request, exc: AudioAPIError) -> JSONResponse:
    del request
    message = {
        "resource_not_found": "The requested resource was not found.",
        "invalid_request": "The request could not be processed.",
        "audio_busy": "Audio generation is temporarily busy.",
        "audio_timeout": "Audio generation timed out.",
    }.get(exc.code, "Audio is temporarily unavailable.")
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": message}},
        headers={
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
        },
    )


@asynccontextmanager
async def lifespan(application: FastAPI):
    try:
        yield
    finally:
        await asyncio.to_thread(application.state.prediction_models.close)


def create_app(
    auth_settings: AuthSettings | None = None, *, import_limits: ImportLimits | None = None
) -> FastAPI:
    """Freeze security configuration once and allow exactly one browser origin."""
    if auth_settings is None:
        try:
            auth_settings = AuthSettings.from_environment()
        except ConfigurationError:
            # An unconfigured local scaffold may serve health; auth still fails
            # closed. Non-local and misspelled environments cannot start insecurely.
            if os.getenv("APP_ENV", "development") not in {"development", "test"}:
                raise
    application = FastAPI(
        title="BOOH API", version=APPLICATION_VERSION,
        docs_url=None, redoc_url=None, openapi_url=None,
        lifespan=lifespan,
    )
    application.state.auth_settings = auth_settings
    application.state.auth_lock = Lock()
    application.state.baby_service = None
    application.state.event_service = None
    application.state.import_service = None
    application.state.import_limits = import_limits or ImportLimits.from_environment()
    application.state.prediction_service = None
    application.state.audio_service = None
    application.state.prediction_models = PredictionModelRegistry()
    summary_environment = {name: os.environ[name] for name in (
        "APP_ENV", "GEMMA_PROVIDER", "GEMMA_BASE_URL", "GEMMA_MODEL", "GEMMA_API_KEY",
    ) if name in os.environ}
    if auth_settings is not None:
        # The frozen application environment is authoritative for all providers.
        summary_environment["APP_ENV"] = auth_settings.app_env
    application.state.summary_service = build_summary_service(summary_environment)
    application.add_exception_handler(RequestValidationError, request_validation_error_handler)
    application.add_exception_handler(AuthError, auth_error_handler)
    application.add_exception_handler(BabyError, baby_error_handler)
    application.add_exception_handler(EventError, event_error_handler)
    application.add_exception_handler(CsvImportError, import_error_handler)
    application.add_exception_handler(PredictionAPIError, prediction_error_handler)
    application.add_exception_handler(AudioAPIError, audio_error_handler)
    application.include_router(auth_router, prefix=API_V1_PREFIX)
    application.include_router(babies_router, prefix=API_V1_PREFIX)
    application.include_router(events_router, prefix=API_V1_PREFIX)
    application.include_router(imports_router, prefix=API_V1_PREFIX)
    application.include_router(predictions_router, prefix=API_V1_PREFIX)
    application.include_router(audio_router, prefix=API_V1_PREFIX)
    application.add_api_route(
        f"{API_V1_PREFIX}/health", health, response_model=HealthResponse,
        tags=["system"], summary="Check API availability",
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[auth_settings.frontend_origin] if auth_settings else [],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "Content-Disposition", "X-CSRF-Token"],
        max_age=600,
    )
    application.add_middleware(AuthPrivacyMiddleware)
    return application


app = create_app()
