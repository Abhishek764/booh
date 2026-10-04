from __future__ import annotations

import base64
import json

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from backend.app.config import AuthSettings
from backend.app.providers.google import ExternalIdentity, GoogleOAuthProvider, ProviderError


def b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def provider_fixture() -> tuple[GoogleOAuthProvider, rsa.RSAPrivateKey]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = private_key.public_key().public_numbers()
    jwk = {
        "keys": [
            {
                "kid": "synthetic-key",
                "kty": "RSA",
                "alg": "RS256",
                "n": b64(public.n.to_bytes((public.n.bit_length() + 7) // 8, "big")),
                "e": b64(public.e.to_bytes((public.e.bit_length() + 7) // 8, "big")),
            }
        ]
    }

    class Transport:
        def fetch_jwks(self) -> dict[str, object]:
            return jwk

        def exchange_code(
            self, code: str, redirect_uri: str, code_verifier: str
        ) -> dict[str, str]:
            del code, redirect_uri, code_verifier
            return {}

    settings = AuthSettings(
        app_env="test",
        secret_key="synthetic-test-secret-key-with-at-least-32-bytes",
        frontend_origin="https://frontend.example.test",
        session_cookie_name="booh_session",
        session_cookie_secure=True,
        session_cookie_samesite="strict",
        google_client_id="synthetic-client-id",
        google_client_secret="synthetic-client-secret",
        google_redirect_uri="https://api.example.test/api/v1/auth/callback",
        google_issuer="https://accounts.google.com",
    )
    return GoogleOAuthProvider(
        settings, Transport(), clock=lambda: 1_700_000_000
    ), private_key


def signed_token(private_key: rsa.RSAPrivateKey, **overrides: object) -> str:
    claims: dict[str, object] = {
        "iss": "https://accounts.google.com",
        "aud": "synthetic-client-id",
        "sub": "synthetic-subject",
        "email": "synthetic@example.test",
        "email_verified": True,
        "nonce": "synthetic-nonce",
        "iat": 1_699_999_900,
        "exp": 1_700_000_300,
    }
    claims.update(overrides)
    header = b64(json.dumps({"alg": "RS256", "typ": "JWT", "kid": "synthetic-key"}, separators=(",", ":")).encode())
    payload = b64(json.dumps(claims, separators=(",", ":")).encode())
    signing_input = f"{header}.{payload}".encode("ascii")
    signature = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    return f"{header}.{payload}.{b64(signature)}"


def test_provider_validates_signature_and_required_claims() -> None:
    provider, private_key = provider_fixture()
    identity = provider.validate_id_token(
        signed_token(private_key), expected_nonce="synthetic-nonce"
    )
    assert identity == ExternalIdentity(
        "https://accounts.google.com", "synthetic-subject", "synthetic@example.test"
    )


def test_authorization_url_binds_s256_pkce_and_fixed_redirect() -> None:
    provider, _ = provider_fixture()
    from urllib.parse import parse_qs, urlsplit

    query = parse_qs(
        urlsplit(
            provider.authorization_url(
                state="synthetic-state",
                nonce="synthetic-nonce",
                code_challenge="C" * 43,
            )
        ).query
    )
    assert query["code_challenge"] == ["C" * 43]
    assert query["code_challenge_method"] == ["S256"]
    assert query["redirect_uri"] == [
        "https://api.example.test/api/v1/auth/callback"
    ]


def test_token_exchange_receives_server_side_pkce_verifier() -> None:
    provider, private_key = provider_fixture()
    original_transport = provider._transport

    class ExchangeTransport:
        verifier: str | None = None

        def fetch_jwks(self) -> object:
            return original_transport.fetch_jwks()

        def exchange_code(
            self, code: str, redirect_uri: str, code_verifier: str
        ) -> dict[str, str]:
            del code, redirect_uri
            self.verifier = code_verifier
            return {"id_token": signed_token(private_key)}

    transport = ExchangeTransport()
    exchanged = GoogleOAuthProvider(
        provider._settings, transport, clock=lambda: 1_700_000_000
    ).exchange_code(
        code="synthetic-code",
        expected_nonce="synthetic-nonce",
        code_verifier="A" * 43,
    )
    assert exchanged.subject == "synthetic-subject"
    assert transport.verifier == "A" * 43


@pytest.mark.parametrize(
    "overrides",
    [
        {"iss": "https://attacker.example.test"},
        {"aud": "another-client"},
        {"email_verified": False},
        {"nonce": "different-nonce"},
        {"exp": 1_699_999_999},
        {"iat": 1_699_990_000},
        {"exp": 1_700_005_000},
        {"sub": ""},
    ],
)
def test_provider_rejects_invalid_issuer_audience_nonce_and_expiry(
    overrides: dict[str, object],
) -> None:
    provider, private_key = provider_fixture()
    with pytest.raises(ProviderError):
        provider.validate_id_token(
            signed_token(private_key, **overrides), expected_nonce="synthetic-nonce"
        )


def test_provider_rejects_signature_tampering() -> None:
    provider, private_key = provider_fixture()
    token = signed_token(private_key)
    header, payload, signature = token.split(".")
    altered = ("A" if signature[0] != "A" else "B") + signature[1:]
    with pytest.raises(ProviderError):
        provider.validate_id_token(
            f"{header}.{payload}.{altered}", expected_nonce="synthetic-nonce"
        )
