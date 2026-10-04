"""Google OAuth provider adapter.

Routes only receive a validated :class:`ExternalIdentity`; OAuth URLs, token
exchange, JWKS retrieval, and JWT verification remain inside this module.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from dataclasses import dataclass
from time import time
from typing import Any, Callable, Mapping, Protocol
from urllib.parse import urlencode

import httpx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from backend.app.config import AuthSettings


class ProviderError(RuntimeError):
    """Raised when Google cannot produce a trusted identity."""


@dataclass(frozen=True, slots=True)
class ExternalIdentity:
    """Minimum provider identity accepted by the local account boundary."""

    issuer: str
    subject: str
    email: str


class GoogleTransport(Protocol):
    """Narrow transport seam for deterministic tests and fixed egress."""

    def exchange_code(
        self, code: str, redirect_uri: str, code_verifier: str
    ) -> Mapping[str, Any]: ...

    def fetch_jwks(self) -> Mapping[str, Any]: ...


class HttpxGoogleTransport:
    """HTTPS-only Google transport with fixed hosts and bounded responses."""

    _TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
    _JWKS_ENDPOINT = "https://www.googleapis.com/oauth2/v3/certs"
    _TIMEOUT_SECONDS = 5.0
    _MAX_RESPONSE_BYTES = 256 * 1024

    def __init__(self, settings: AuthSettings) -> None:
        self._settings = settings

    def exchange_code(
        self, code: str, redirect_uri: str, code_verifier: str
    ) -> Mapping[str, Any]:
        payload = {
            "code": code,
            "client_id": self._settings.google_client_id,
            "client_secret": self._settings.google_client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
            "code_verifier": code_verifier,
        }
        return self._request_json("POST", self._TOKEN_ENDPOINT, data=payload)

    def fetch_jwks(self) -> Mapping[str, Any]:
        return self._request_json("GET", self._JWKS_ENDPOINT)

    def _request_json(self, method: str, url: str, **kwargs: Any) -> Mapping[str, Any]:
        """Read a fixed provider response incrementally before parsing JSON."""

        body = bytearray()
        try:
            with httpx.stream(
                method,
                url,
                timeout=self._TIMEOUT_SECONDS,
                follow_redirects=False,
                **kwargs,
            ) as response:
                response.raise_for_status()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > self._MAX_RESPONSE_BYTES:
                        raise ProviderError("provider response is too large")
            decoded = json.loads(bytes(body))
        except ProviderError:
            raise
        except (httpx.HTTPError, UnicodeDecodeError, ValueError) as exc:
            raise ProviderError("provider request failed") from exc
        if not isinstance(decoded, dict):
            raise ProviderError("provider response is invalid")
        return decoded


_B64URL = re.compile(r"^[A-Za-z0-9_-]+$")


def _decode_segment(segment: str, *, max_bytes: int) -> bytes:
    if not segment or len(segment) > max_bytes * 2 or not _B64URL.fullmatch(segment):
        raise ProviderError("identity token is malformed")
    try:
        value = base64.urlsafe_b64decode(segment + "===")
    except (binascii.Error, ValueError) as exc:
        raise ProviderError("identity token is malformed") from exc
    if len(value) > max_bytes:
        raise ProviderError("identity token is too large")
    return value


def _json_object(segment: str) -> dict[str, Any]:
    try:
        value = json.loads(_decode_segment(segment, max_bytes=16 * 1024))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderError("identity token is malformed") from exc
    if not isinstance(value, dict):
        raise ProviderError("identity token is malformed")
    return value


class GoogleOAuthProvider:
    """Provider adapter that validates Google OIDC tokens before identity use."""

    _AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
    _MAX_ID_TOKEN_LIFETIME_SECONDS = 60 * 60

    def __init__(
        self,
        settings: AuthSettings,
        transport: GoogleTransport | None = None,
        *,
        clock: Callable[[], float] = time,
    ) -> None:
        if settings.google_issuer != "https://accounts.google.com":
            raise ProviderError("provider issuer is not allowed")
        self._settings = settings
        self._transport = transport or HttpxGoogleTransport(settings)
        self._clock = clock

    def authorization_url(
        self, *, state: str, nonce: str, code_challenge: str
    ) -> str:
        if (
            not self._safe_oauth_value(state)
            or not self._safe_oauth_value(nonce)
            or not self._safe_pkce_challenge(code_challenge)
        ):
            raise ProviderError("oauth transaction is invalid")
        query = urlencode(
            {
                "client_id": self._settings.google_client_id,
                "redirect_uri": self._settings.google_redirect_uri,
                "response_type": "code",
                "scope": "openid email",
                "state": state,
                "nonce": nonce,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            }
        )
        return f"{self._AUTHORIZATION_ENDPOINT}?{query}"

    def exchange_code(
        self, *, code: str, expected_nonce: str, code_verifier: str
    ) -> ExternalIdentity:
        if not isinstance(code, str) or not 1 <= len(code) <= 2048:
            raise ProviderError("oauth callback is invalid")
        if not self._safe_oauth_value(expected_nonce) or not self._safe_pkce_verifier(
            code_verifier
        ):
            raise ProviderError("oauth transaction is invalid")
        try:
            response = self._transport.exchange_code(
                code, self._settings.google_redirect_uri, code_verifier
            )
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError("provider request failed") from exc
        id_token = response.get("id_token")
        if not isinstance(id_token, str) or len(id_token) > 16 * 1024:
            raise ProviderError("provider identity is invalid")
        return self.validate_id_token(id_token, expected_nonce=expected_nonce)

    def validate_id_token(self, token: str, *, expected_nonce: str) -> ExternalIdentity:
        if not isinstance(token, str) or not 1 <= len(token) <= 16 * 1024:
            raise ProviderError("identity token is malformed")
        parts = token.split(".")
        if len(parts) != 3:
            raise ProviderError("identity token is malformed")
        header_segment, payload_segment, signature_segment = parts
        header = _json_object(header_segment)
        claims = _json_object(payload_segment)
        if header.get("alg") != "RS256" or header.get("typ") != "JWT":
            raise ProviderError("identity token algorithm is invalid")
        kid = header.get("kid")
        if not isinstance(kid, str) or not 1 <= len(kid) <= 256:
            raise ProviderError("identity token key is invalid")
        signature = _decode_segment(signature_segment, max_bytes=1024)
        signing_input = f"{header_segment}.{payload_segment}".encode("ascii")
        key = self._find_key(kid)
        try:
            key.verify(signature, signing_input, padding.PKCS1v15(), hashes.SHA256())
        except Exception as exc:
            raise ProviderError("identity token signature is invalid") from exc

        issuer = claims.get("iss")
        if issuer != self._settings.google_issuer:
            raise ProviderError("identity token issuer is invalid")
        audience = claims.get("aud")
        if isinstance(audience, str):
            audience_values = [audience]
        elif isinstance(audience, list) and all(isinstance(item, str) for item in audience):
            audience_values = audience
        else:
            raise ProviderError("identity token audience is invalid")
        if self._settings.google_client_id not in audience_values:
            raise ProviderError("identity token audience is invalid")
        if len(audience_values) > 1 and claims.get("azp") != self._settings.google_client_id:
            raise ProviderError("identity token authorized party is invalid")

        now = self._clock()
        exp = claims.get("exp")
        iat = claims.get("iat")
        if type(exp) is not int or exp <= now:
            raise ProviderError("identity token is expired")
        if type(iat) is not int or iat > now + 60:
            raise ProviderError("identity token issue time is invalid")
        if (
            now - iat > self._MAX_ID_TOKEN_LIFETIME_SECONDS + 60
            or exp - iat > self._MAX_ID_TOKEN_LIFETIME_SECONDS + 60
            or exp - now > self._MAX_ID_TOKEN_LIFETIME_SECONDS + 60
        ):
            raise ProviderError("identity token lifetime is invalid")
        nbf = claims.get("nbf")
        if nbf is not None and (
            type(nbf) is not int or nbf > now + 60
        ):
            raise ProviderError("identity token is not active")
        token_nonce = claims.get("nonce")
        if not isinstance(token_nonce, str) or not self._safe_oauth_value(token_nonce):
            raise ProviderError("identity token nonce is invalid")
        if not _constant_time_equal(token_nonce, expected_nonce):
            raise ProviderError("identity token nonce is invalid")

        subject = claims.get("sub")
        email = claims.get("email")
        if not isinstance(subject, str) or not 1 <= len(subject) <= 255:
            raise ProviderError("identity token subject is invalid")
        if not isinstance(email, str) or not 3 <= len(email) <= 320 or "@" not in email:
            raise ProviderError("identity token email is invalid")
        if claims.get("email_verified") is not True:
            raise ProviderError("identity token email is not verified")
        return ExternalIdentity(
            issuer=self._settings.google_issuer, subject=subject, email=email
        )

    def _find_key(self, kid: str) -> rsa.RSAPublicKey:
        try:
            jwks = self._transport.fetch_jwks()
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError("provider key request failed") from exc
        keys = jwks.get("keys")
        if not isinstance(keys, list):
            raise ProviderError("provider keys are invalid")
        matching = next(
            (key for key in keys if isinstance(key, dict) and key.get("kid") == kid),
            None,
        )
        if not isinstance(matching, dict) or matching.get("kty") != "RSA":
            raise ProviderError("provider key is unavailable")
        if matching.get("alg") != "RS256":
            raise ProviderError("provider key algorithm is invalid")
        modulus_text = matching.get("n")
        exponent_text = matching.get("e")
        if not isinstance(modulus_text, str) or not isinstance(exponent_text, str):
            raise ProviderError("provider key is invalid")
        modulus_bytes = _decode_segment(modulus_text, max_bytes=4096)
        exponent_bytes = _decode_segment(exponent_text, max_bytes=8)
        modulus = int.from_bytes(modulus_bytes, "big")
        exponent = int.from_bytes(exponent_bytes, "big")
        if modulus.bit_length() < 2048 or exponent < 3 or exponent % 2 == 0:
            raise ProviderError("provider key is invalid")
        try:
            return rsa.RSAPublicNumbers(exponent, modulus).public_key()
        except ValueError as exc:
            raise ProviderError("provider key is invalid") from exc

    @staticmethod
    def _safe_oauth_value(value: str) -> bool:
        return bool(1 <= len(value) <= 512 and re.fullmatch(r"[A-Za-z0-9_-]+", value))

    @staticmethod
    def _safe_pkce_verifier(value: str) -> bool:
        return bool(
            43 <= len(value) <= 128 and re.fullmatch(r"[A-Za-z0-9._~-]+", value)
        )

    @staticmethod
    def _safe_pkce_challenge(value: str) -> bool:
        return bool(len(value) == 43 and re.fullmatch(r"[A-Za-z0-9_-]+", value))


def _constant_time_equal(left: str, right: str) -> bool:
    import hmac

    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


__all__ = ["ExternalIdentity", "GoogleOAuthProvider", "GoogleTransport", "ProviderError"]
