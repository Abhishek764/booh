"""FastAPI dependency wiring for authentication and owned resources."""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import Depends, Header, Request
from sqlalchemy.exc import SQLAlchemyError

from backend.app.config import AuthSettings, ConfigurationError
from backend.app.database import create_database_engine, create_session_factory
from backend.app.importers import CsvImportError
from backend.app.prediction_contracts import PredictionAPIError
from backend.app.providers.google import GoogleOAuthProvider
from backend.app.repositories.auth import SqlAlchemyAuthRepository
from backend.app.repositories.babies import SqlAlchemyBabyRepository
from backend.app.repositories.events import SqlAlchemyEventRepository
from backend.app.repositories.imports import SqlAlchemyImportRepository
from backend.app.repositories.predictions import SqlAlchemyPredictionRepository
from backend.app.services.auth import AuthError, AuthService, Principal
from backend.app.services.babies import BabyError, BabyService
from backend.app.services.events import EventError, EventService
from backend.app.services.imports import ImportService
from backend.app.services.prediction_models import PredictionModelRegistry
from backend.app.services.predictions import PredictionPipelineService


def build_auth_service(settings: AuthSettings | None = None) -> AuthService:
    """Construct production auth dependencies only from validated configuration."""

    settings = settings or AuthSettings.from_environment()
    engine = create_database_engine()
    repository = SqlAlchemyAuthRepository(create_session_factory(engine))
    provider = GoogleOAuthProvider(settings)
    return AuthService(settings, provider, repository)


def get_auth_service(request: Request) -> AuthService:
    configured = getattr(request.app.state, "auth_service", None)
    if configured is not None:
        return cast(AuthService, configured)
    with request.app.state.auth_lock:
        configured = getattr(request.app.state, "auth_service", None)
        if configured is None:
            try:
                configured = build_auth_service(request.app.state.auth_settings)
            except (ConfigurationError, RuntimeError, SQLAlchemyError):
                raise AuthError("authentication_unavailable", 503) from None
            request.app.state.auth_service = configured
        return cast(AuthService, configured)


def get_current_principal(request: Request) -> Principal:
    service = get_auth_service(request)
    return service.authenticate(
        request.cookies.get(service.cookie_names.session)
    )


def get_csrf_protected_principal(
    request: Request,
    csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> Principal:
    """Authenticate and validate the CSRF proof for state-changing requests."""

    service = get_auth_service(request)
    principal = service.authenticate(
        request.cookies.get(service.cookie_names.session)
    )
    service.validate_csrf(
        principal,
        csrf_cookie=request.cookies.get(service.cookie_names.csrf),
        csrf_header=csrf_header,
        origin=request.headers.get("origin"),
    )
    return principal


def build_baby_service(models: PredictionModelRegistry | None = None) -> BabyService:
    """Construct the baby service from the explicitly configured database."""

    engine = create_database_engine()
    repository = SqlAlchemyBabyRepository(create_session_factory(engine))
    return BabyService(repository, on_change=None if models is None else models.invalidate)


def get_baby_service(request: Request) -> BabyService:
    """Lazily construct the baby service without bypassing app configuration."""

    configured = getattr(request.app.state, "baby_service", None)
    if configured is not None:
        return cast(BabyService, configured)
    with request.app.state.auth_lock:
        configured = getattr(request.app.state, "baby_service", None)
        if configured is None:
            try:
                configured = build_baby_service(request.app.state.prediction_models)
            except (RuntimeError, SQLAlchemyError):
                raise BabyError("service_unavailable", 503) from None
            request.app.state.baby_service = configured
        return cast(BabyService, configured)


def build_event_service(models: PredictionModelRegistry | None = None) -> EventService:
    """Construct the event service from the explicitly configured database."""

    engine = create_database_engine()
    repository = SqlAlchemyEventRepository(create_session_factory(engine))
    return EventService(repository, on_change=None if models is None else models.invalidate)


def get_event_service(request: Request) -> EventService:
    """Lazily construct the owner-scoped event service."""

    configured = getattr(request.app.state, "event_service", None)
    if configured is not None:
        return cast(EventService, configured)
    with request.app.state.auth_lock:
        configured = getattr(request.app.state, "event_service", None)
        if configured is None:
            try:
                configured = build_event_service(request.app.state.prediction_models)
            except (RuntimeError, SQLAlchemyError):
                raise EventError("service_unavailable", 503) from None
            request.app.state.event_service = configured
        return cast(EventService, configured)


def get_import_service(request: Request) -> ImportService:
    """Lazily wire owner-scoped import persistence with frozen upload limits."""

    configured = getattr(request.app.state, "import_service", None)
    if configured is not None:
        return cast(ImportService, configured)
    with request.app.state.auth_lock:
        configured = getattr(request.app.state, "import_service", None)
        if configured is None:
            try:
                engine = create_database_engine()
                repository = SqlAlchemyImportRepository(create_session_factory(engine))
                configured = ImportService(repository, limits=request.app.state.import_limits,
                                           on_change=request.app.state.prediction_models.invalidate)
            except (RuntimeError, SQLAlchemyError):
                raise CsvImportError("service_unavailable", 503) from None
            request.app.state.import_service = configured
        return cast(ImportService, configured)


def get_prediction_service(
    request: Request, principal: Annotated[Principal, Depends(get_current_principal)],
) -> PredictionPipelineService:
    del principal  # Authentication must run before constructing database/provider wiring.
    configured = getattr(request.app.state, "prediction_service", None)
    if configured is not None:
        return cast(PredictionPipelineService, configured)
    with request.app.state.auth_lock:
        configured = getattr(request.app.state, "prediction_service", None)
        if configured is None:
            try:
                engine = create_database_engine()
                configured = PredictionPipelineService(
                    SqlAlchemyPredictionRepository(create_session_factory(engine)),
                    summaries=request.app.state.summary_service, models=request.app.state.prediction_models,
                )
            except (RuntimeError, SQLAlchemyError):
                raise PredictionAPIError("service_unavailable") from None
            request.app.state.prediction_service = configured
        return cast(PredictionPipelineService, configured)


__all__ = [
    "build_auth_service",
    "build_baby_service",
    "build_event_service",
    "get_auth_service",
    "get_baby_service",
    "get_csrf_protected_principal",
    "get_current_principal",
    "get_event_service",
    "get_import_service",
    "get_prediction_service",
]
