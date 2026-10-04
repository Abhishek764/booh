"""FastAPI dependency wiring for the backend authentication boundary."""

from __future__ import annotations

from typing import cast

from fastapi import Request
from sqlalchemy.exc import SQLAlchemyError

from backend.app.config import AuthSettings, ConfigurationError
from backend.app.database import create_database_engine, create_session_factory
from backend.app.providers.google import GoogleOAuthProvider
from backend.app.repositories.auth import SqlAlchemyAuthRepository
from backend.app.services.auth import AuthError, AuthService, Principal


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


__all__ = ["build_auth_service", "get_auth_service", "get_current_principal"]
