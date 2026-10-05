"""Validated configuration for the authentication boundary.

Configuration is read at the application boundary and is never inferred from a
browser request.  Authentication endpoints fail closed when a required value is
missing or unsafe.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import urlsplit


class ConfigurationError(RuntimeError):
    """Raised when authentication cannot be safely configured."""


_COOKIE_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_SAMESITE_VALUES = frozenset({"strict", "lax", "none"})
_GOOGLE_ISSUER = "https://accounts.google.com"
GOOGLE_CALLBACK_PATHS = frozenset({
    "/api/v1/auth/google/callback",
    "/api/v1/auth/callback",  # Compatibility with existing registered clients.
})


def _required(name: str, values: Mapping[str, str | None]) -> str:
    value = values.get(name)
    if value is None or not value.strip():
        raise ConfigurationError(f"{name} must be configured")
    return value.strip()


def _parse_bool(name: str, value: str) -> bool:
    normalized = value.lower()
    if normalized not in {"true", "false"}:
        raise ConfigurationError(f"{name} must be true or false")
    return normalized == "true"


def _validate_url(name: str, value: str, *, production: bool) -> None:
    if any(character.isspace() for character in value) or any(
        character in value for character in ("\\", "*", "%")
    ):
        raise ConfigurationError(f"{name} contains invalid URL characters")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise ConfigurationError(f"{name} must be a valid URL") from None
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or (port is not None and port == 0)
    ):
        raise ConfigurationError(f"{name} must be an absolute HTTP(S) URL without credentials")
    if parsed.scheme != "https" and (
        production or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
    ):
        raise ConfigurationError(f"{name} must use HTTPS except for local development")


def _validate_origin(name: str, value: str, *, production: bool) -> None:
    _validate_url(name, value, production=production)
    parsed = urlsplit(value)
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ConfigurationError(f"{name} must not contain a path or query")
    if parsed.username or parsed.password:
        raise ConfigurationError(f"{name} must not contain credentials")
    if production and parsed.scheme != "https":
        raise ConfigurationError(f"{name} must use HTTPS in production")


def _validate_redirect_uri(value: str, *, production: bool) -> None:
    _validate_url("GOOGLE_OAUTH_REDIRECT_URI", value, production=production)
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ConfigurationError("GOOGLE_OAUTH_REDIRECT_URI must be absolute")
    if parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise ConfigurationError("GOOGLE_OAUTH_REDIRECT_URI is invalid")
    if production and parsed.scheme != "https":
        raise ConfigurationError("GOOGLE_OAUTH_REDIRECT_URI must use HTTPS in production")


@dataclass(frozen=True, slots=True)
class AuthSettings:
    """Immutable settings used by provider, session, and route services.

    Sessions have a seven-day absolute lifetime and a thirty-minute idle
    lifetime by default.  Both limits are enforced server-side; the cookie's
    expiry represents only the absolute limit.
    """

    app_env: str
    secret_key: str = field(repr=False)
    frontend_origin: str
    session_cookie_name: str
    session_cookie_secure: bool
    session_cookie_samesite: str
    google_client_id: str
    google_client_secret: str = field(repr=False)
    google_redirect_uri: str
    google_issuer: str
    session_ttl_seconds: int = 60 * 60 * 24 * 7
    session_idle_ttl_seconds: int = 60 * 30
    oauth_transaction_ttl_seconds: int = 60 * 10
    cookie_path: str = "/api/v1"
    oauth_cookie_path: str = "/api/v1/auth"

    def __post_init__(self) -> None:
        if self.app_env not in {"development", "test", "staging", "production", "prod"}:
            raise ConfigurationError("APP_ENV must be an approved environment")
        production = self.app_env not in {"development", "test"}
        if len(self.secret_key.encode("utf-8")) < 32:
            raise ConfigurationError("SECRET_KEY must contain at least 32 bytes")
        if not _COOKIE_NAME.fullmatch(self.session_cookie_name):
            raise ConfigurationError("SESSION_COOKIE_NAME contains invalid characters")
        if self.session_cookie_samesite.lower() not in _SAMESITE_VALUES:
            raise ConfigurationError("SESSION_COOKIE_SAMESITE is invalid")
        if self.session_cookie_samesite.lower() == "none" and not self.session_cookie_secure:
            raise ConfigurationError("SameSite=None requires Secure cookies")
        if production and not self.session_cookie_secure:
            raise ConfigurationError("SESSION_COOKIE_SECURE must be true in production")
        if self.session_cookie_name.startswith(("__Secure-", "__Host-")) and not self.session_cookie_secure:
            raise ConfigurationError("Prefixed cookies require Secure")
        if self.session_cookie_name.startswith("__Host-") and (
            self.cookie_path != "/" or self.oauth_cookie_path != "/"
        ):
            raise ConfigurationError("__Host- cookies require Path=/")
        _validate_origin("FRONTEND_ORIGIN", self.frontend_origin, production=production)
        object.__setattr__(self, "frontend_origin", self.frontend_origin.rstrip("/"))
        object.__setattr__(self, "session_cookie_samesite", self.session_cookie_samesite.lower())
        if self.google_issuer != _GOOGLE_ISSUER:
            raise ConfigurationError("GOOGLE_OAUTH_ISSUER is not an allowed issuer")
        _validate_redirect_uri(self.google_redirect_uri, production=production)
        if urlsplit(self.google_redirect_uri).path not in GOOGLE_CALLBACK_PATHS:
            raise ConfigurationError("GOOGLE_OAUTH_REDIRECT_URI must target the callback")
        if not self.google_client_id.strip() or not self.google_client_secret.strip():
            raise ConfigurationError("Google OAuth credentials must be configured")
        if (
            self.session_ttl_seconds <= 0
            or self.session_idle_ttl_seconds <= 0
            or self.oauth_transaction_ttl_seconds <= 0
        ):
            raise ConfigurationError("session lifetimes must be positive")

    @classmethod
    def from_environment(cls, environ: dict[str, str] | None = None) -> "AuthSettings":
        """Build settings and reject missing or insecure production values."""

        values = dict(os.environ if environ is None else environ)
        app_env = _required("APP_ENV", values).lower()
        production = app_env not in {"development", "test"}
        secret_key = _required("SECRET_KEY", values)
        if len(secret_key.encode("utf-8")) < 32:
            raise ConfigurationError("SECRET_KEY must contain at least 32 bytes")

        frontend_origin = _required("FRONTEND_ORIGIN", values)
        _validate_origin("FRONTEND_ORIGIN", frontend_origin, production=production)

        cookie_name = _required("SESSION_COOKIE_NAME", values)
        if not _COOKIE_NAME.fullmatch(cookie_name):
            raise ConfigurationError("SESSION_COOKIE_NAME contains invalid characters")

        secure = _parse_bool(
            "SESSION_COOKIE_SECURE", _required("SESSION_COOKIE_SECURE", values)
        )
        if production and not secure:
            raise ConfigurationError("SESSION_COOKIE_SECURE must be true in production")

        samesite = _required("SESSION_COOKIE_SAMESITE", values).lower()
        if samesite not in _SAMESITE_VALUES:
            raise ConfigurationError("SESSION_COOKIE_SAMESITE is invalid")
        if samesite == "none" and not secure:
            raise ConfigurationError("SameSite=None requires Secure cookies")

        issuer = _required("GOOGLE_OAUTH_ISSUER", values).rstrip("/")
        if issuer != _GOOGLE_ISSUER:
            raise ConfigurationError("GOOGLE_OAUTH_ISSUER is not an allowed issuer")

        redirect_uri = _required("GOOGLE_OAUTH_REDIRECT_URI", values)
        _validate_redirect_uri(redirect_uri, production=production)
        redirect_parts = urlsplit(redirect_uri)
        if redirect_parts.path not in GOOGLE_CALLBACK_PATHS:
            raise ConfigurationError("GOOGLE_OAUTH_REDIRECT_URI must target the callback")

        return cls(
            app_env=app_env,
            secret_key=secret_key,
            frontend_origin=frontend_origin.rstrip("/"),
            session_cookie_name=cookie_name,
            session_cookie_secure=secure,
            session_cookie_samesite=samesite,
            google_client_id=_required("GOOGLE_OAUTH_CLIENT_ID", values),
            google_client_secret=_required("GOOGLE_OAUTH_CLIENT_SECRET", values),
            google_redirect_uri=redirect_uri,
            google_issuer=issuer,
        )


@dataclass(frozen=True, slots=True)
class ImportLimits:
    """Finite upload budgets; environment values cannot remove hard ceilings."""

    max_upload_bytes: int = 2 * 1024 * 1024
    max_rows: int = 10000

    def __post_init__(self) -> None:
        if type(self.max_upload_bytes) is not int or not 1 <= self.max_upload_bytes <= 10 * 1024 * 1024:
            raise ConfigurationError("MAX_UPLOAD_BYTES must be between 1 and 10485760")
        if type(self.max_rows) is not int or not 1 <= self.max_rows <= 10000:
            raise ConfigurationError("MAX_IMPORT_ROWS must be between 1 and 10000")

    @classmethod
    def from_environment(cls, environ: dict[str, str] | None = None) -> "ImportLimits":
        values = os.environ if environ is None else environ
        try:
            return cls(
                max_upload_bytes=int(values.get("MAX_UPLOAD_BYTES") or 2 * 1024 * 1024),
                max_rows=int(values.get("MAX_IMPORT_ROWS") or 10000),
            )
        except (TypeError, ValueError):
            raise ConfigurationError("Import limits must be bounded integers") from None


__all__ = ["AuthSettings", "ConfigurationError", "ImportLimits"]
