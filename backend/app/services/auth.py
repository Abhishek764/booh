"""Authentication workflows and policy decisions."""

from __future__ import annotations

import hmac
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Protocol

from backend.app.config import AuthSettings
from backend.app.providers.google import ExternalIdentity, ProviderError
from backend.app.repositories.auth import (
    AuthRepository,
)
from backend.app.security import (
    SignedTokenCodec,
    SignedTokenError,
    digest,
    pkce_challenge,
    random_token,
    utc_now,
)


class AuthError(RuntimeError):
    """Safe, client-facing authentication failure."""

    def __init__(self, code: str, status_code: int = 401) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


class AuthProvider(Protocol):
    def authorization_url(
        self, *, state: str, nonce: str, code_challenge: str
    ) -> str: ...

    def exchange_code(
        self, *, code: str, expected_nonce: str, code_verifier: str
    ) -> ExternalIdentity: ...


@dataclass(frozen=True, slots=True)
class CookieNames:
    session: str
    csrf: str
    oauth_flow: str


@dataclass(frozen=True, slots=True)
class LoginStart:
    authorization_url: str
    oauth_flow_cookie: str
    max_age: int


@dataclass(frozen=True, slots=True)
class AuthenticationResult:
    session_cookie: str
    csrf_cookie: str
    max_age: int
    redirect_to: str


@dataclass(frozen=True, slots=True)
class Principal:
    user_id: uuid.UUID
    session_id: uuid.UUID
    email: str
    token_hash: str
    csrf_hash: str


class AuthService:
    """Orchestrates provider validation, local identity, and session policy."""

    def __init__(
        self,
        settings: AuthSettings,
        provider: AuthProvider,
        repository: AuthRepository,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.settings = settings
        self._provider = provider
        self._repository = repository
        self._clock = clock
        self._codec = SignedTokenCodec(settings.secret_key)
        self.cookie_names = CookieNames(
            session=settings.session_cookie_name,
            csrf=f"{settings.session_cookie_name}_csrf",
            oauth_flow=f"{settings.session_cookie_name}_oauth",
        )

    def start_login(self) -> LoginStart:
        now = self._now()
        expires_at = now + timedelta(seconds=self.settings.oauth_transaction_ttl_seconds)
        state = random_token()
        binding = random_token()
        code_verifier = random_token()
        code_challenge = pkce_challenge(code_verifier)
        nonce = random_token()
        try:
            self._repository.create_oauth_transaction(
                state_hash=digest(state),
                nonce_hash=digest(nonce),
                binding_hash=digest(binding),
                code_challenge=code_challenge,
                created_at=now,
                expires_at=expires_at,
            )
            authorization_url = self._provider.authorization_url(
                state=state, nonce=nonce, code_challenge=code_challenge
            )
        except Exception as exc:
            raise AuthError("authentication_unavailable", 503) from exc
        return LoginStart(
            authorization_url=authorization_url,
            oauth_flow_cookie=self._codec.issue(
                f"{binding}|{code_verifier}|{nonce}", expires_at
            ),
            max_age=self.settings.oauth_transaction_ttl_seconds,
        )

    def complete_login(
        self, *, code: str, state: str | None, oauth_flow_cookie: str | None
    ) -> AuthenticationResult:
        now = self._now()
        if (
            not isinstance(code, str)
            or not 1 <= len(code) <= 2048
            or not isinstance(state, str)
            or not 1 <= len(state) <= 512
            or not state.isascii()
            or oauth_flow_cookie is None
        ):
            raise AuthError("invalid_callback")
        try:
            flow_payload, binding_expiry = self._codec.verify(oauth_flow_cookie, now)
        except SignedTokenError as exc:
            raise AuthError("invalid_callback") from exc
        if binding_expiry <= now:
            raise AuthError("invalid_callback")
        flow_values = flow_payload.split("|")
        if (
            len(flow_values) != 3
            or not all(self._safe_flow_value(value) for value in flow_values)
        ):
            raise AuthError("invalid_callback")
        binding, code_verifier, expected_nonce = flow_values
        code_challenge = pkce_challenge(code_verifier)
        try:
            transaction = self._repository.consume_oauth_transaction(
                state_hash=digest(state),
                binding_hash=digest(binding),
                code_challenge=code_challenge,
                now=now,
            )
        except Exception as exc:
            raise AuthError("authentication_unavailable", 503) from exc
        if transaction is None:
            raise AuthError("invalid_callback")
        if not hmac.compare_digest(transaction.nonce_hash, digest(expected_nonce)):
            raise AuthError("invalid_callback")
        try:
            identity = self._provider.exchange_code(
                code=code,
                expected_nonce=expected_nonce,
                code_verifier=code_verifier,
            )
        except (ProviderError, ValueError, TypeError) as exc:
            raise AuthError("invalid_callback") from exc
        except Exception as exc:
            raise AuthError("authentication_unavailable", 503) from exc
        if not self._valid_identity(identity):
            raise AuthError("invalid_callback")

        # Account resolution happens only after provider validation succeeds.
        try:
            user = self._repository.get_or_create_identity_user(
                issuer=identity.issuer,
                subject=identity.subject,
                email=identity.email,
                now=now,
            )
            session_token = random_token()
            csrf_token = random_token()
            session_expiry = now + timedelta(seconds=self.settings.session_ttl_seconds)
            self._repository.create_session(
                user_id=user.id,
                token_hash=digest(session_token),
                csrf_hash=digest(csrf_token),
                created_at=now,
                last_seen_at=now,
                expires_at=session_expiry,
            )
        except Exception as exc:
            raise AuthError("authentication_unavailable", 503) from exc
        return AuthenticationResult(
            session_cookie=self._codec.issue(session_token, session_expiry),
            csrf_cookie=csrf_token,
            max_age=self.settings.session_ttl_seconds,
            redirect_to=self.settings.frontend_origin,
        )

    def authenticate(self, session_cookie: str | None) -> Principal:
        if not session_cookie:
            raise AuthError("authentication_required")
        now = self._now()
        try:
            token, expiry = self._codec.verify(session_cookie, now)
        except SignedTokenError as exc:
            raise AuthError("authentication_required") from exc
        if expiry <= now:
            raise AuthError("authentication_required")
        try:
            record = self._repository.get_active_session(
                token_hash=digest(token),
                now=now,
                idle_after=now - timedelta(seconds=self.settings.session_idle_ttl_seconds),
            )
        except Exception as exc:
            raise AuthError("authentication_unavailable", 503) from exc
        if record is None:
            raise AuthError("authentication_required")
        return Principal(
            user_id=record.user.id,
            session_id=record.id,
            email=record.user.email,
            token_hash=record.token_hash,
            csrf_hash=record.csrf_hash,
        )

    def logout(
        self,
        *,
        session_cookie: str | None,
        csrf_cookie: str | None,
        csrf_header: str | None,
        origin: str | None,
    ) -> None:
        """Invalidate a valid session, requiring an explicit CSRF proof."""

        if origin != self.settings.frontend_origin:
            raise AuthError("origin_failed", 403)
        if not session_cookie:
            return
        principal = self.authenticate(session_cookie)
        if (
            not csrf_cookie
            or not csrf_header
            or len(csrf_cookie) > 128
            or len(csrf_header) > 128
            or not hmac.compare_digest(csrf_cookie, csrf_header)
            or not hmac.compare_digest(digest(csrf_cookie), principal.csrf_hash)
        ):
            raise AuthError("csrf_failed", 403)
        try:
            self._repository.revoke_session(
                token_hash=principal.token_hash, revoked_at=self._now()
            )
        except Exception as exc:
            raise AuthError("authentication_unavailable", 503) from exc

    def _now(self) -> datetime:
        current = self._clock()
        if current.tzinfo is None:
            return current.replace(tzinfo=timezone.utc)
        return current.astimezone(timezone.utc)

    def _valid_identity(self, identity: ExternalIdentity) -> bool:
        return bool(
            isinstance(identity, ExternalIdentity)
            and identity.issuer == self.settings.google_issuer
            and isinstance(identity.subject, str)
            and 1 <= len(identity.subject) <= 255
            and isinstance(identity.email, str)
            and 3 <= len(identity.email) <= 320
            and "@" in identity.email
        )

    @staticmethod
    def _safe_flow_value(value: str) -> bool:
        return bool(1 <= len(value) <= 128 and re.fullmatch(r"[A-Za-z0-9_-]+", value))


__all__ = [
    "AuthError",
    "AuthProvider",
    "AuthService",
    "AuthenticationResult",
    "CookieNames",
    "LoginStart",
    "Principal",
]
