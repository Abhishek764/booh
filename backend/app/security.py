"""Small, dependency-free security primitives used by auth services."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timezone


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def random_token() -> str:
    return secrets.token_urlsafe(32)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def pkce_challenge(verifier: str) -> str:
    """Return the RFC 7636 S256 challenge for an opaque verifier."""

    return base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")


class SignedTokenError(ValueError):
    """Raised for malformed, tampered, or expired signed cookie values."""


class SignedTokenCodec:
    """Sign short-lived opaque token values without putting identity in cookies."""

    def __init__(self, secret_key: str) -> None:
        self._secret = secret_key.encode("utf-8")

    def issue(self, token: str, expires_at: datetime) -> str:
        expiry = int(expires_at.timestamp())
        payload = f"{token}.{expiry}"
        signature = hmac.new(
            self._secret, payload.encode("ascii"), hashlib.sha256
        ).digest()
        encoded_signature = base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")
        return f"{payload}.{encoded_signature}"

    def verify(self, value: str, now: datetime | None = None) -> tuple[str, datetime]:
        if not value or len(value) > 512:
            raise SignedTokenError("invalid signed value")
        parts = value.split(".")
        if len(parts) != 3 or not parts[0] or not parts[1] or not parts[2]:
            raise SignedTokenError("invalid signed value")
        token, expiry_text, supplied_signature = parts
        if (
            not token.isascii()
            or not expiry_text.isascii()
            or not supplied_signature.isascii()
            or not expiry_text.isdecimal()
            or len(token) > 256
            or len(supplied_signature) > 128
        ):
            raise SignedTokenError("invalid signed value")
        try:
            expiry = int(expiry_text)
            expiry_at = datetime.fromtimestamp(expiry, timezone.utc)
        except (OverflowError, ValueError, OSError) as exc:
            raise SignedTokenError("invalid signed value") from exc
        payload = f"{token}.{expiry_text}".encode("ascii")
        expected = hmac.new(self._secret, payload, hashlib.sha256).digest()
        try:
            supplied = base64.urlsafe_b64decode(supplied_signature + "===")
        except (ValueError, UnicodeEncodeError) as exc:
            raise SignedTokenError("invalid signed value") from exc
        if not hmac.compare_digest(expected, supplied):
            raise SignedTokenError("invalid signed value")
        current = now or utc_now()
        if current >= expiry_at:
            raise SignedTokenError("expired signed value")
        return token, expiry_at


__all__ = [
    "SignedTokenCodec",
    "SignedTokenError",
    "digest",
    "pkce_challenge",
    "random_token",
    "utc_now",
]
