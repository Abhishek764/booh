"""Minimal BOOH API application boundary.

Versioned routes belong in feature-specific modules and must call services
rather than implementing policy in the route layer.
"""

from typing import Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from backend.app.routes.auth import router as auth_router
from backend.app.services.auth import AuthError

API_V1_PREFIX = "/api/v1"
APPLICATION_VERSION = "0.1.0"


class HealthResponse(BaseModel):
    """Stable response contract for process and routing health checks."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"] = "ok"
    service: Literal["booh-api"] = "booh-api"
    version: str = APPLICATION_VERSION


app = FastAPI(
    title="BOOH API",
    version=APPLICATION_VERSION,
    description="Versioned API boundary for the BOOH nighttime dashboard.",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

app.include_router(auth_router, prefix=API_V1_PREFIX)


@app.exception_handler(RequestValidationError)
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


@app.exception_handler(AuthError)
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


@app.get(
    f"{API_V1_PREFIX}/health",
    response_model=HealthResponse,
    status_code=200,
    tags=["system"],
    summary="Check API availability",
)
async def health() -> HealthResponse:
    """Report that the API process is running.

    Dependency health checks will be added with the database layer. This
    endpoint intentionally does not expose credentials, user data, or runtime
    internals.
    """

    return HealthResponse()
