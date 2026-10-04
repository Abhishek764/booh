"""FastAPI dependency wiring for authentication and owned resources."""

from __future__ import annotations

from typing import cast

from fastapi import Request
from sqlalchemy.exc import SQLAlchemyError

from backend.app.config import AuthSettings, ConfigurationError
from backend.app.database import create_database_engine, create_session_factory
from backend.app.providers.google import GoogleOAuthProvider
from backend.app.repositories.auth import SqlAlchemyAuthRepository
from backend.app.repositories.babies import SqlAlchemyBabyRepository
from backend.app.services.auth import AuthError, AuthService, Principal
from backend.app.services.babies import BabyError, BabyService


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


def build_baby_service() -> BabyService:
    """Construct the baby service from the explicitly configured database."""

    engine = create_database_engine()
    repository = SqlAlchemyBabyRepository(create_session_factory(engine))
    return BabyService(repository)


def get_baby_service(request: Request) -> BabyService:
    """Lazily construct the baby service without bypassing app configuration."""

    configured = getattr(request.app.state, "baby_service", None)
    if configured is not None:
        return cast(BabyService, configured)
    with request.app.state.auth_lock:
        configured = getattr(request.app.state, "baby_service", None)
        if configured is None:
            try:
                configured = build_baby_service()
            except (RuntimeError, SQLAlchemyError):
                raise BabyError("service_unavailable", 503) from None
            request.app.state.baby_service = configured
        return cast(BabyService, configured)


__all__ = [
    "build_auth_service",
    "build_baby_service",
    "get_auth_service",
    "get_baby_service",
    "get_current_principal",
]
